# Vercel web with the backend on your PC

Current target: publish the animated, clearly labelled illustrative website; keep the existing API, SQLite files, agents and any later execution processes on the owner's PC. No separate Vercel API service, database or daemon is configured. No tunnel or deployment was opened during implementation.

## Routing

`vercel.json` imports the repository root as a single `web` service rooted at `apps/web`. All public paths go to that Next.js service. Browser requests retain `/api/...`; a Node route handler reads `API_ORIGIN` and `PROXY_TOKEN` at **request time** and calls the PC through HTTPS. There is no build-time localhost URL and no service binding: the PC backend is external to Vercel Services.

For the requested appearance preview, the hosted proxy allows only GET `/api/v1/product/state` and `/api/v1/research`. Mutations, wallet endpoints and arbitrary proxy destinations are refused. Vercel supplies the verified client address; incoming `X-Lobster-*` values are discarded. The shared proxy secret is injected server-side. Redirects, oversized responses and failures are bounded, private headers are not relayed, and failed requests are not retried. The operator page is unavailable on Vercel; the hosted wallet panel has no connect/sign buttons.

Vercel builds set the public **boolean** hosted-preview flag automatically. This enables the existing illustrative money figures on public hostnames, retaining the preview badge. It does not expose any backend URL, credential or key. Money figures remain frontend fixtures; market candles/research remain PC observations. The source `LOCAL_LAUNCH_PREVIEW_ENABLED=false` setting still disables invented figures after a rebuild.

## 1. Import only the web on Vercel

Import this GitHub repository with the Vercel project Root Directory set to the **repository root**, so the root `vercel.json` is found. It declares the Next.js service root; do not also set the project root to `apps/web`.

The initial website can build without a connected PC. Market data will remain unavailable until the following steps are complete. Keep the production website address for `WEB_ORIGIN`, for example `https://your-project.vercel.app`.

## 2. Prepare and run the API on the PC

From the repository root, after the usual Python/Node dependency setup:

```powershell
npm run setup:pc
```

This creates ignored `.env.pc` with two different random secrets and never prints them. Set `WEB_ORIGIN` in that file to the exact production website origin, without a trailing slash. The prepared preset uses Hyperliquid public market data and **paper execution**, with no paid model calls. Agent research can be configured locally later using the provider/model/key settings in that file; the generated key names are proxy/operator access secrets, not a model key or trading API wallet.

```powershell
npm run api:pc:check
npm run api:pc
```

The API listens on **127.0.0.1:8000**, not a public network interface. Existing public-mode checks require the proxy secret and verified client address before accepting any tunneled request. All account/database files remain on your PC. Starting this API does not start real order/payout runners.

## 3. Connect an owner-started HTTPS tunnel

Install `cloudflared` from Cloudflare's official distribution. In a second terminal, start a temporary tunnel, replacing the hostname with the host from `WEB_ORIGIN`:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000 --http-host-header your-project.vercel.app
```

**The HTTP Host override is required**: it lets the local TrustedHost boundary see the configured website host, while the external HTTPS request still addresses the tunnel hostname. Do not bypass TLS certificate checks or disable the API boundary. The tunnel URL does not grant access without the shared proxy secret.

Cloudflare prints a temporary HTTPS address such as `https://random-name.trycloudflare.com`. Quick tunnels change address on restart and do not support SSE; this product uses five-second polling, and the hosted proxy does not expose the internal event stream. A named tunnel can later provide a stable hostname. For a named tunnel set the same `originRequest.httpHostHeader` value.

## 4. Set two private Vercel variables

| Vercel variable | Value |
| --- | --- |
| `API_ORIGIN` | The HTTPS tunnel **origin**, without `/api`, query or path. |
| `PROXY_TOKEN` | Exactly the `PROXY_TOKEN` from the ignored PC `.env.pc`. |

Set them in the appropriate Vercel environment and apply them through a new deployment. Never prefix them with `NEXT_PUBLIC_`. Do not upload `.env.pc`, `OPERATOR_TOKEN`, model credentials or Hyperliquid private keys to GitHub/Vercel for this setup. No bound URL variable is manually set because there is no internal API service.

With the PC API and tunnel running, `/api/v1/product/state` through the website should show actual Hyperliquid BTC candles. Direct tunnel requests without proxy credentials must return 403. The financial figures are still marked illustrative and do not prove trades or donations.

## Operation and verification limits

The PC must remain on, awake and connected; both the API terminal and tunnel terminal must stay running. If either stops, the website still loads and animates its illustrative money, while market/research reads report unavailable. A changed temporary tunnel URL requires updating `API_ORIGIN` and applying a new deployment. No port forwarding on the router is required.

Use `vercel dev -L` for Vercel-local routing when a supported Vercel CLI is available; normal `npm run dev` continues using the original loopback API rewrite and supports the complete local workspace. The hosted view is deliberately read-only for the owner-selected appearance review. Real trading, public wallet submissions and continuous availability need separate later acceptance; a model key does not activate them.

Local verification: ordinary and `VERCEL=1` production builds passed, 81 client checks and 20 existing API boundary cases passed. The production HTTP smoke confirmed `/` 200, `/operator` 404, missing tunnel configuration 503, wallet API reads 404 and writes 405. Vercel CLI 65 detected the single web service in `vercel dev -L`, but the Windows service launcher stopped with `spawn cmd.exe ENOENT`; complete CLI-local and cloud/tunnel acceptance remain unobserved. No account was linked and no deployment occurred.

References: [Vercel service routing](https://vercel.com/docs/services/routing), [runtime bindings](https://vercel.com/docs/services/bindings), [Vercel request headers](https://vercel.com/docs/headers/request-headers), [Cloudflare quick tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), [Cloudflare origin configuration](https://developers.cloudflare.com/tunnel/configuration/).
