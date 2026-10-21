import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('hosted login binds the exact HTTPS page origin and still rejects another origin or changed message', () => {
  const module = new URL('../src/lib/wallet-auth.ts',import.meta.url).href;
  const script = `
    import assert from 'node:assert/strict';
    process.env.NEXT_PUBLIC_HOSTED_PREVIEW='true';
    delete process.env.NEXT_PUBLIC_WEB_ORIGIN;
    globalThis.window={location:{protocol:'https:',origin:'https://desk.example.test'}};
    const {AUTH_ORIGIN,AUTH_STATEMENT,validateAuthChallenge}=await import(${JSON.stringify(module)});
    assert.equal(AUTH_ORIGIN,'https://desk.example.test');
    assert.ok(!AUTH_STATEMENT.includes('local '));
    const address='0x'+'a'.repeat(40), nonce='1'.repeat(32), challenge_id='2'.repeat(32);
    const issued_at=new Date().toISOString(), expires_at=new Date(Date.parse(issued_at)+120000).toISOString();
    const c={address,nonce,challenge_id,issued_at,expires_at,origin:AUTH_ORIGIN,chain_id:42161,scope:'mainnet:preview',order_submission_enabled:false,fee_collection_enabled:false,
      message:AUTH_ORIGIN+' wants you to sign in with your Ethereum account:\\n'+address+'\\n\\n'+AUTH_STATEMENT.replace('testnet','mainnet')+'\\n\\nURI: '+AUTH_ORIGIN+'\\nVersion: 1\\nChain ID: 42161\\nNonce: '+nonce+'\\nIssued At: '+issued_at+'\\nExpiration Time: '+expires_at+'\\nRequest ID: '+challenge_id};
    assert.equal(validateAuthChallenge(c,address,AUTH_ORIGIN,'0xa4b1',Date.now(),'mainnet').address,address);
    assert.throws(()=>validateAuthChallenge(c,address,'https://other.example.test','0xa4b1',Date.now(),'mainnet'));
    assert.throws(()=>validateAuthChallenge({...c,message:c.message+' extra'},address,AUTH_ORIGIN,'0xa4b1',Date.now(),'mainnet'));
  `;
  const result=spawnSync(process.execPath,['--experimental-strip-types','--input-type=module','-e',script],{encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,result.stderr);
});
