import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { proxyPCRead } from '../src/lib/pc-api-proxy.ts';

const env = {API_ORIGIN:'https://pc-tunnel.example.test',PROXY_TOKEN:'public-test-proxy-secret-0000000000000000'};
const request = (path='/api/v1/product/state', init={}) => new Request(`https://desk.example.test${path}`, {
  ...init,headers:{'x-vercel-forwarded-for':'203.0.113.10',...init.headers}});

test('Vercel contains only a public web service; the PC backend is not an internal service', () => {
  const config = JSON.parse(readFileSync(new URL('../../../vercel.json',import.meta.url),'utf8'));
  assert.deepEqual(config.services,{web:{root:'apps/web',framework:'nextjs'}});
  assert.deepEqual(config.rewrites,[{source:'/(.*)',destination:{service:'web'}}]);
});

test('runtime PC proxy preserves /api and supplies only its own trusted identity and secret', async () => {
  let calls=0;
  const response=await proxyPCRead(request('/api/v1/product/state',{headers:{
    'x-lobster-proxy-token':'spoofed','x-lobster-client-ip':'8.8.8.8','authorization':'private-browser-value'}}),env,async (url,init)=>{
    calls++;
    assert.equal(String(url),'https://pc-tunnel.example.test/api/v1/product/state');
    assert.equal(init.headers['X-Lobster-Proxy-Token'],env.PROXY_TOKEN);
    assert.equal(init.headers['X-Lobster-Client-IP'],'203.0.113.10');
    assert.equal(init.headers.authorization,undefined);
    assert.equal(init.redirect,'error');
    assert.equal(init.method,'GET');
    return Response.json({market:null},{headers:{'Set-Cookie':'private','X-Lobster-Proxy-Token':env.PROXY_TOKEN}});
  });
  assert.equal(calls,1); assert.equal(response.status,200);
  assert.equal(response.headers.get('set-cookie'),null);
  assert.equal(response.headers.get('x-lobster-proxy-token'),null);
  assert.equal(response.headers.get('cache-control'),'no-store');
  assert.equal((await response.text()).includes(env.PROXY_TOKEN),false);
});

test('writes, wallet routes, arbitrary paths and query injection never reach the PC', async () => {
  const never=async()=>{throw new Error('Unexpected upstream call');};
  for (const path of ['/api/v1/users/mainnet/config','/api/v1/operator','/api/v1/research?url=https://evil.test'])
    assert.equal((await proxyPCRead(request(path),env,never)).status,404);
  for (const method of ['POST','PUT','DELETE'])
    assert.equal((await proxyPCRead(request('/api/v1/product/state',{method}),env,never)).status,405);
});

test('HTTPS destination, private secret and a single platform IP are mandatory', async () => {
  let calls=0; const never=async()=>{calls++;throw new Error();};
  for (const API_ORIGIN of ['', 'http://127.0.0.1:8000','https://localhost.','https://127.0.0.1','https://user:secret@example.test','https://example.test/path','https://example.test/?a=b'])
    assert.equal((await proxyPCRead(request(),{...env,API_ORIGIN},never)).status,503);
  assert.equal((await proxyPCRead(request(),{...env,PROXY_TOKEN:''},never)).status,503);
  for (const ip of ['', 'spoofed', '203.0.113.1, 203.0.113.2'])
    assert.equal((await proxyPCRead(request('/api/v1/product/state',{headers:{'x-vercel-forwarded-for':ip}}),env,never)).status,400);
  assert.equal(calls,0);
});

test('redirects, offline backends and oversized responses are bounded and never retried', async () => {
  let calls=0;
  const offline=await proxyPCRead(request(),env,async()=>{calls++;throw new Error('private upstream diagnostic');});
  assert.equal(offline.status,502); assert.equal(calls,1);
  assert.equal((await offline.text()).includes('private upstream diagnostic'),false);
  assert.equal((await proxyPCRead(request(),env,async()=>new Response(null,{status:302}))).status,502);
  assert.equal((await proxyPCRead(request(),env,async()=>new Response('x'.repeat(1024*1024+1),{headers:{'content-type':'application/json'}}))).status,502);
});
