// Server-only implementation: imported by the Node route handler, never a client component.
import { isIP } from "node:net";

const reads = new Set(["/api/v1/product/state", "/api/v1/research"]);
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const fail = (status: number, detail: string) => Response.json({ detail }, { status, headers });

export async function proxyPCRead(request: Request, env: Record<string, string | undefined>, fetcher: typeof fetch = fetch) {
  if (request.method !== "GET") return fail(405, "This website currently supports viewing only.");
  const incoming = new URL(request.url);
  if (!reads.has(incoming.pathname) || incoming.search) return fail(404, "This API route is not available on the hosted preview.");
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
    const response = await fetcher(target, { method: "GET", redirect: "error", cache: "no-store", signal,
      headers: { "Accept": "application/json", "X-Lobster-Proxy-Token": secret, "X-Lobster-Client-IP": peer } });
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
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    // Only public JSON from these two reads is exposed. Never relay cookies,
    // proxy credentials, redirects or internal upstream response headers.
    return new Response(body, { status: response.status, headers: { ...headers, "Content-Type": "application/json" } });
  } catch { return fail(signal.aborted ? 504 : 502, "The PC backend is offline or the tunnel is unavailable."); }
}
