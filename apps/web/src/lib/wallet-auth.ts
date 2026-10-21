/** Exact local sign-in message contract. Never signs orders or builder consent. */
// Hosted sign-in is bound to the page's HTTPS origin. The PC independently
// generates the exact configured WEB_ORIGIN message; other domains cannot sign in.
export const AUTH_ORIGIN = process.env.NEXT_PUBLIC_WEB_ORIGIN ||
  (process.env.NEXT_PUBLIC_HOSTED_PREVIEW === "true" && typeof window !== "undefined" && window.location.protocol === "https:"
    ? window.location.origin : "http://127.0.0.1:3000");
export const AUTH_STATEMENT = `Sign in to the ${AUTH_ORIGIN === "http://127.0.0.1:3000" ? "local " : ""}Claw Desk testnet workspace. This grants no trading, transfer or fee approval.`;
export type AuthChallenge = {
  challenge_id: string; address: string; origin: string; chain_id: number; nonce: string;
  issued_at: string; expires_at: string; message: string; scope: string;
  order_submission_enabled: false; fee_collection_enabled: false;
};

export function validateAuthChallenge(value: unknown, address: string, origin: string, chainId: string, now = Date.now(), network: "testnet" | "mainnet" = "testnet"): AuthChallenge {
  const expectedChain = network === "testnet" ? 421614 : 42161;
  if (origin !== AUTH_ORIGIN || !/^0x[0-9a-f]+$/i.test(chainId) || BigInt(chainId) !== BigInt(expectedChain)) {
    throw new Error(`Sign-in requires ${AUTH_ORIGIN} and wallet chain ${expectedChain}. Select it manually, then reconnect.`);
  }
  if (!value || typeof value !== "object") throw new Error("Invalid sign-in challenge.");
  const c = value as AuthChallenge;
  if (c.origin !== origin || c.chain_id !== expectedChain || c.address !== address || c.scope !== `${network}:preview` ||
      c.order_submission_enabled !== false || c.fee_collection_enabled !== false ||
      typeof c.challenge_id !== "string" || !/^[a-f0-9]{32}$/.test(c.challenge_id) ||
      typeof c.nonce !== "string" || !/^[a-f0-9]{32}$/.test(c.nonce) || typeof c.message !== "string" ||
      typeof c.issued_at !== "string" || typeof c.expires_at !== "string") throw new Error("The sign-in challenge does not match this wallet or local scope.");
  const issued = Date.parse(c.issued_at), expires = Date.parse(c.expires_at);
  if (!Number.isFinite(issued) || !Number.isFinite(expires) || issued > now + 2000 || now >= expires || expires - issued !== 120000) {
    throw new Error("The sign-in challenge expired or has an invalid clock. Prepare a fresh message.");
  }
  const displayAddress = c.message.split("\n")[1];
  if (!/^0x[0-9a-fA-F]{40}$/.test(displayAddress || "") || displayAddress.toLowerCase() !== address) throw new Error("The sign-in message has a different account.");
  const expected = `${origin} wants you to sign in with your Ethereum account:\n${displayAddress}\n\n${AUTH_STATEMENT.replace("testnet", network)}\n\nURI: ${origin}\nVersion: 1\nChain ID: ${expectedChain}\nNonce: ${c.nonce}\nIssued At: ${c.issued_at}\nExpiration Time: ${c.expires_at}\nRequest ID: ${c.challenge_id}`;
  if (c.message !== expected) throw new Error("Unexpected sign-in message. No signature was requested.");
  return c;
}

export function messageHex(message: string): string {
  return "0x" + Array.from(new TextEncoder().encode(message), byte => byte.toString(16).padStart(2, "0")).join("");
}

export type AuthResult = { address: string; access_token: string; expires_at: string; scope: "testnet:preview" | "mainnet:preview";
  token_type: "Bearer"; authenticated: true; network: "testnet" | "mainnet"; order_submission_enabled: false; fee_collection_enabled: false };

export function validateAuthResult(value: unknown, address: string, now = Date.now(), network: "testnet" | "mainnet" = "testnet"): AuthResult {
  const result = value as AuthResult | null;
  if (!result || result.address !== address || result.authenticated !== true || result.scope !== `${network}:preview` ||
      result.network !== network || result.token_type !== "Bearer" || result.order_submission_enabled !== false ||
      result.fee_collection_enabled !== false || typeof result.access_token !== "string" ||
      !/^[A-Za-z0-9_-]{43}$/.test(result.access_token) || typeof result.expires_at !== "string" ||
      !Number.isFinite(Date.parse(result.expires_at)) || Date.parse(result.expires_at) <= now ||
      Date.parse(result.expires_at) > now + 902000) throw new Error("The sign-in result does not match this wallet or preview scope.");
  return result;
}
