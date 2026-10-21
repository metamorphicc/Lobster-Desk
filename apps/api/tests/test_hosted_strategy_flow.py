"""Actual Node proxy/wallet contract -> isolated Python API. Unfunded fixture only."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
from threading import Thread

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import pytest

from lobster.agents import DemoReviewer
from lobster.config import Settings
from lobster.domain import Snapshot, utcnow
from lobster.main import Runtime, create_app
from lobster.pipeline import Pipeline
from test_user_orders import ADDRESS, KEY


def test_hosted_connect_signin_submit_retry_review_logout(tmp_path, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the cross-runtime integration check")
    origin = "https://desk.example.test"
    proxy_secret = "offline-proxy-" + "1" * 40

    async def idle(*args):
        await asyncio.Event().wait()

    for method in ("market_loop", "decision_loop", "product_market_loop"):
        monkeypatch.setattr(Runtime, method, idle)
    app = create_app(Settings(_env_file=None, deployment_mode="public-single-host", web_origin=origin,
        proxy_token=proxy_secret, operator_token="offline-operator-" + "2" * 40,
        database_url=f"sqlite:///{tmp_path/'app.db'}", treasury_path=str(tmp_path/'book.db'), paper_funding_enabled=False))
    with TestClient(app, base_url=origin) as client:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path == "/fixture/sign":
                    value = json.loads(body)
                    signature = Account.sign_message(encode_defunct(text=value["message"]), KEY).signature.hex()
                    status, output = 200, json.dumps({"signature": "0x" + signature.removeprefix("0x")}).encode()
                elif self.path == "/fixture/review":
                    async def review():
                        pipeline = Pipeline(app.state.runtime.store, DemoReviewer())
                        for _ in range(4):
                            await pipeline.step(Snapshot(source="hyperliquid", price="60000", timestamp=utcnow()))
                    asyncio.run(review())
                    status, output = 200, b'{}'
                else:
                    response = client.request(self.command, self.path, headers=dict(self.headers), content=body)
                    status, output = response.status_code, response.content
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = Path(__file__).resolve().parents[3]
        source = r'''
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
process.env.NEXT_PUBLIC_WEB_ORIGIN='https://desk.example.test';
const {WalletSession}=await import('./apps/web/src/lib/wallet.ts');
const {proxyPCRead}=await import('./apps/web/src/lib/pc-api-proxy.ts');
const origin=process.env.NEXT_PUBLIC_WEB_ORIGIN;
const base=process.env.FIXTURE_BASE;
const env={API_ORIGIN:'https://pc.example.test',PROXY_TOKEN:process.env.FIXTURE_PROXY};
const owner=process.env.FIXTURE_OWNER;
const upstream=(url,init)=>fetch(base+new URL(url).pathname,{...init,headers:{...init.headers,Host:new URL(origin).host}});
async function api(path,method='GET',body,headers={}) {
  const request=new Request(origin+'/api/v1/users/mainnet/'+path,{method,
    headers:{'x-vercel-forwarded-for':'203.0.113.11',...(method==='POST'?{origin,'content-type':'application/json'}:{}),...headers},
    body:body===undefined?undefined:JSON.stringify(body)});
  return proxyPCRead(request,env,upstream);
}
class Provider extends EventEmitter {
  calls=[];
  async request({method,params}) {
    this.calls.push(method);
    if(method==='eth_accounts'||method==='eth_requestAccounts') return [owner];
    if(method==='eth_chainId') return '0xa4b1';
    if(method==='personal_sign') {
      const response=await fetch(base+'/fixture/sign',{method:'POST',body:JSON.stringify({message:Buffer.from(params[0].slice(2),'hex').toString('utf8')})});
      return (await response.json()).signature;
    }
    throw new Error('Unexpected wallet action: '+method);
  }
}
const provider=new Provider(), wallet=new WalletSession();
await wallet.connect(provider);
assert.equal(provider.calls.includes('personal_sign'),false);
const challenge=await (await api('auth/challenge','POST',{address:owner})).json();
const signature=await wallet.signMainnetAuthentication(challenge,origin);
const verify=await api('auth/verify','POST',{challenge_id:challenge.challenge_id,signature});
assert.equal(verify.status,200);
const session=await verify.json(), authorization='Bearer '+session.access_token;
assert.equal(session.order_submission_enabled,false);
const pitch={author:'Hosted QA',symbol:'BTC',direction:'long',entry:'60000',stop:'59400',target:'61800',leverage:1,thesis:'An isolated historical price breakout hypothesis for the integration check.'};
const headers={authorization,'idempotency-key':'hosted-fixture-001'};
const submitted=await api('strategy-pitches','POST',pitch,headers);
assert.equal(submitted.status,201); const episode=await submitted.json();
assert.equal((await (await api('strategy-pitches','POST',pitch,headers)).json()).id,episode.id);
assert.equal((await api('strategy-pitches','POST',{...pitch,target:'62000'},headers)).status,409);
let history=await (await api('strategy-earnings','GET',undefined,{authorization})).json();
assert.equal(history.submissions.length,1); assert.equal(history.submissions[0].status,'queued');
await fetch(base+'/fixture/review',{method:'POST'});
history=await (await api('strategy-earnings','GET',undefined,{authorization})).json();
assert.equal(history.submissions[0].status,'approved');
assert.ok(history.submissions[0].reviews.analyst);
assert.equal(history.balance,null);
assert.equal((await api('auth/logout','POST',{}, {authorization})).status,200);
assert.equal((await api('strategy-earnings','GET',undefined,{authorization})).status,401);
assert.equal(provider.calls.some(x=>/sendTransaction|signTypedData/.test(x)),false);
wallet.disconnect();
'''
        try:
            import os
            result = subprocess.run([node, "--experimental-strip-types", "--input-type=module", "-e", source],
                cwd=root, env=os.environ | {"FIXTURE_BASE": f"http://127.0.0.1:{server.server_port}",
                    "FIXTURE_PROXY": proxy_secret, "FIXTURE_OWNER": ADDRESS}, capture_output=True, text=True, timeout=40)
            assert result.returncode == 0, result.stderr
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
