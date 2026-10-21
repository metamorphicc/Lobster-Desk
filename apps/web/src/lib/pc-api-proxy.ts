// Server-only implementation: imported by the Node route handler, never a client component.
import { isIP } from "node:net";

const reads = new Set(["/api/v1/product/state", "/api/v1/research"]);
const userPrefix = "/api/v1/users/mainnet/";
const privateRead = userPrefix + "strategy-earnings";
const writes = new Set(["auth/challenge", "auth/verify", "auth/logout", "strategy-pitches"].map(path => userPrefix + path));
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const fail = (status: number, detail: string) => Response.json({ detail }, { status, headers });

export async function proxyPCRead(request: Request, env: Record<string, string | undefined>, fetcher: typeof fetch = fetch) {
  const incoming = new URL(request.url);
  const path = incoming.pathname;
  const write = request.method === "POST" && writes.has(path);
  if (request.method !== "GET" && !write) return fail(405, "This operation is not available on the website.");
  if (incoming.search || (!write && !reads.has(path) && path !== privateRead)) return fail(404, "This API route is not available on the website.");
  if (write && request.headers.get("origin") !== incoming.origin) return fail(403, "Submit from this website's own origin.");
  const upstreamHeaders: Record<string, string> = { Accept: "application/json" };
  if (path === privateRead || path === userPrefix + "auth/logout" || path === userPrefix + "strategy-pitches") {
    const authorization = request.headers.get("authorization") || "";
    if (!/^Bearer [A-Za-z0-9_-]{43}$/.test(authorization)) return fail(401, "Sign in to submit and view your strategies.");
    upstreamHeaders.Authorization = authorization;
  }
  if (path === userPrefix + "strategy-pitches") {
    const key = request.headers.get("idempotency-key") || "";
    if (!/^[a-zA-Z0-9_-]{8,64}$/.test(key)) return fail(422, "A valid strategy request identity is required.");
    upstreamHeaders["Idempotency-Key"] = key;
  }
  let body: Uint8Array | undefined;
  if (write) {
    if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get("content-type") || "") || request.headers.has("content-encoding")) return fail(415, "Send a JSON request.");
    const length = request.headers.get("content-length");
    if (length && (!/^\d{1,8}$/.test(length) || Number(length) > 8192)) return fail(413, "The request is too large.");
    const reader = request.body?.getReader();
    if (!reader) return fail(400, "A JSON request body is required.");
    const deadline = AbortSignal.any([request.signal, AbortSignal.timeout(5000)]);
    const cancel = () => { void reader.cancel().catch(() => {}); };
    deadline.addEventListener("abort", cancel, { once: true });
    const chunks: Uint8Array[] = []; let size = 0;
    try {
      if (deadline.aborted) return fail(408, "Request upload timed out.");
      while (true) {
        const item = await reader.read();
        if (deadline.aborted) return fail(408, "Request upload timed out.");
        if (item.done) break;
        size += item.value.byteLength;
        if (size > 8192) { await reader.cancel(); return fail(413, "The request is too large."); }
        chunks.push(item.value);
      }
      body = new Uint8Array(size); let offset = 0;
      for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
      JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
    } catch { return fail(deadline.aborted ? 408 : 400, "A valid JSON request body is required."); }
    finally { deadline.removeEventListener("abort", cancel); reader.releaseLock(); }
    upstreamHeaders["Content-Type"] = "application/json";
    upstreamHeaders.Origin = incoming.origin;
  }
  let target: URL;
  try {
    target = new URL(env.API_ORIGIN || "");
    if (target.protocol !== "https:" || target.username || target.password || target.search || target.hash
        || target.pathname !== "/" || !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$/.test(target.hostname) || isIP(target.hostname)
        || target.hostname.endsWith(".localhost") || target.hostname.endsWith(".local")) throw new Error();
  } catch { return fail(503, "The PC backend HTTPS address is not configured."); }
  const secret = env.PROXY_TOKEN;
  if (!secret || secret.length < 32) return fail(503, "The PC backend connection is not configured.");
  // Vercel supplies this header. Never trust client-provided X-Lobster-* headers.
  // This function is exposed by the hosted route only when VERCEL=1.
  const peer = request.headers.get("x-vercel-forwarded-for");
  if (!peer || !isIP(peer)) return fail(400, "A verified hosting client address is required.");
  const signal = AbortSignal.any([request.signal, AbortSignal.timeout(12000)]);
  try {
    target.pathname = incoming.pathname; // Preserve the API's existing /api prefix.
    const response = await fetcher(target, { method: request.method, redirect: "error", cache: "no-store", signal, body: body as BodyInit | undefined,
      headers: { ...upstreamHeaders, "X-Lobster-Proxy-Token": secret, "X-Lobster-Client-IP": peer } });
    if (response.status >= 300 && response.status < 400) return fail(502, "The PC backend returned an unexpected redirect.");
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) return fail(502, "The PC backend returned an unexpected response.");
    const reader = response.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      try {
        while (true) {
          const item = await reader.read();
          if (item.done) break;
          size += item.value.byteLength;
          if (size > 1024 * 1024) { await reader.cancel(); return fail(502, "The PC backend response exceeded its limit."); }
          chunks.push(item.value);
        }
      } finally { reader.releaseLock(); }
    }
    const responseBody = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { responseBody.set(chunk, offset); offset += chunk.byteLength; }
    // Only allowlisted JSON is exposed. Never relay cookies,
    // proxy credentials, redirects or internal upstream response headers.
    const retryAfter = response.headers.get("retry-after");
    return new Response(responseBody, { status: response.status, headers: { ...headers, "Content-Type": "application/json",
      ...(retryAfter && /^\d{1,6}$/.test(retryAfter) ? { "Retry-After": retryAfter } : {}) } });
  } catch { return fail(signal.aborted ? 504 : 502, "The PC backend is offline or the tunnel is unavailable."); }
}
