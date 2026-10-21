import { proxyPCRead } from "@/lib/pc-api-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (process.env.VERCEL !== "1") return Response.json({ detail: "Use the local API proxy for this environment." }, { status: 503 });
  return proxyPCRead(request, process.env);
}

export const POST = GET;
