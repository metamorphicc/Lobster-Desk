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

const token = 'Bearer ' + 'a'.repeat(43);
const user = '/api/v1/users/mainnet/';
const post = (path, body = '{}', headers = {}) => request(user + path, {method:'POST',body,
  headers:{origin:'https://desk.example.test','content-type':'application/json',...headers}});

test('hosted auth and attributed pitches forward only bounded same-origin requests', async () => {
  for (const path of ['auth/challenge','auth/verify','auth/logout','strategy-pitches']) {
    const response = await proxyPCRead(post(path,'{"fixture":true}',{authorization:token,'idempotency-key':'setup-request-001'}),env,async(url,init)=>{
      assert.equal(String(url),'https://pc-tunnel.example.test'+user+path);
      assert.equal(init.method,'POST');
      assert.equal(new TextDecoder().decode(init.body),'{"fixture":true}');
      assert.equal(init.headers.Origin,'https://desk.example.test');
      if (path === 'strategy-pitches' || path === 'auth/logout') assert.equal(init.headers.Authorization,token);
      else assert.equal(init.headers.Authorization,undefined);
      if (path === 'strategy-pitches') assert.equal(init.headers['Idempotency-Key'],'setup-request-001');
      return Response.json({accepted:true});
    });
    assert.equal(response.status,200);
  }
});

test('authenticated reads keep bearer tokens private and retain server-side throttling', async () => {
  assert.equal((await proxyPCRead(request(user+'strategy-earnings'),env)).status,401);
  const response=await proxyPCRead(request(user+'strategy-earnings',{headers:{authorization:token,cookie:'private-cookie'}}),env,async(url,init)=>{
    assert.equal(init.headers.Authorization,token); assert.equal(init.headers.cookie,undefined);
    return Response.json({detail:'Wait'},{status:429,headers:{'Retry-After':'30','Set-Cookie':'private'}});
  });
  assert.equal(response.status,429); assert.equal(response.headers.get('retry-after'),'30');
  assert.equal(response.headers.get('set-cookie'),null); assert.equal(response.headers.get('cache-control'),'no-store');
});

test('cross-origin, malformed, oversized and anonymous writes never reach the PC', async () => {
  let calls=0; const never=async()=>{calls++;throw new Error();};
  assert.equal((await proxyPCRead(post('auth/challenge','{}',{origin:'https://evil.example'}),env,never)).status,403);
  assert.equal((await proxyPCRead(post('auth/challenge','{}',{origin:''}),env,never)).status,403);
  assert.equal((await proxyPCRead(post('strategy-pitches'),env,never)).status,401);
  assert.equal((await proxyPCRead(post('strategy-pitches','{}',{authorization:token}),env,never)).status,422);
  assert.equal((await proxyPCRead(post('auth/challenge','x'.repeat(8193)),env,never)).status,413);
  assert.equal((await proxyPCRead(post('auth/challenge','{invalid'),env,never)).status,400);
  assert.equal((await proxyPCRead(post('auth/challenge','{}',{'content-type':'text/plain'}),env,never)).status,415);
  assert.equal(calls,0);
});

test('write origin follows the HTTP Host when Next reconstructs an internal request URL', async () => {
  const incoming = new Request('http://localhost:3000'+user+'auth/challenge',{
    method:'POST',body:'{}',headers:{host:'desk.example.test',origin:'https://desk.example.test',
      'content-type':'application/json','x-vercel-forwarded-for':'203.0.113.10'}});
  const response=await proxyPCRead(incoming,env,async(url,init)=>{
    assert.equal(init.headers.Origin,'https://desk.example.test');
    return Response.json({ok:true});
  });
  assert.equal(response.status,200);
  assert.equal((await proxyPCRead(post('auth/challenge','{}',{host:'different.example.test'}),env)).status,403);
  assert.equal((await proxyPCRead(post('auth/challenge','{}',{origin:'http://desk.example.test'}),env)).status,403);
});

test('financial, operator, anonymous and testnet paths stay closed on the hosted site', async () => {
  let calls=0; const never=async()=>{calls++;throw new Error();};
  for(const path of ['financial/prepare','capital/refresh','order-preview','permissions','auth/verify/extra'])
    assert.equal((await proxyPCRead(post(path),env,never)).status,405);
  for(const path of ['/api/v1/pitches','/api/v1/operator','/api/v1/users/testnet/auth/challenge'])
    assert.equal((await proxyPCRead(request(path,{method:'POST',body:'{}'}),env,never)).status,405);
  assert.equal(calls,0);
});

test('an uncertain pitch is not retried and its explicit retry keeps the same identity', async () => {
  let calls=0; const keys=[];
  const upstream=async(url,init)=>{calls++;keys.push(init.headers['Idempotency-Key']);throw new Error('connection reset');};
  for(let attempt=0;attempt<2;attempt++) {
    const response=await proxyPCRead(post('strategy-pitches','{}',{authorization:token,'idempotency-key':'stable-request-001'}),env,upstream);
    assert.equal(response.status,502); assert.equal(calls,attempt+1);
  }
  assert.deepEqual(keys,['stable-request-001','stable-request-001']);
});
