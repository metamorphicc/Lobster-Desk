# Public single-host server preparation

This is deployable-source preparation, **not a completed deployment or launch approval**. `deploy/compose.yaml` defines one API/worker, standalone Next.js server and Caddy HTTPS proxy on one host. Only the proxy publishes ports. Financial runner processes are deliberately absent from the default stack; creating or starting the web stack cannot activate trading, donation or token signers.

## Boundary and identity

`DEPLOYMENT_MODE=public-single-host` requires an exact canonical HTTPS `WEB_ORIGIN`, distinct random proxy/operator secrets of at least 32 characters and one file-backed SQLite worker owner. The existing OS database lease rejects a duplicate worker. This packaging does not support multiple hosts/replicas or distributed leadership. Local mode retains exact loopback hosts/origins and its previous defaults.

Caddy overwrites `X-Lobster-Proxy-Token` and `X-Lobster-Client-IP`. The public-mode API accepts only that configured token and one valid proxy-supplied client IP; arbitrary `X-Forwarded-For` cannot become rate-limit identity. Exact origin checks remain separate. Uvicorn's generic forwarded-header trust is disabled. The API keeps private wallet routes owner-authenticated and financial proof admission explicitly gated. Public pitches remain bounded anonymous proposals: persistent per-peer windows, queue limits and hard model-call budgets still apply; a pitch does not grant financial authority. The proxy token alone cannot call operator routes.

The API bounds request bodies/time and public active application requests (128 global, eight per verified peer); Uvicorn also caps connections/tasks at 128 and uses a short idle timeout. These are single-host limits, not protection against an upstream bandwidth attack. Public server capacity and edge controls must be provisioned for actual traffic. SQLite admission is shared by all code using this database, while process-local sessions intentionally expire on API restart.

Wallet sign-in messages use the configured exact origin. Browser builds pin the same non-secret origin through `NEXT_PUBLIC_WEB_ORIGIN`; the browser never trusts an arbitrary current host as its signing domain. Build and backend configuration must agree. Security headers prevent framing, disable unused browser permissions and prohibit plugin objects; this is not a claim of a complete nonce-based CSP. API bodies have no-store/nosniff headers. All data remains English; no geographic rule or legal registration is invented.

## Owner-run server steps

1. Run `node scripts/python.mjs scripts/server-config.py` locally. It creates ignored `.env.server` with separate random secrets and does not print them; existing files are preserved. Fill a domain you control and any model credentials locally. Review host/DNS, TLS, backups, operator access, cost/loss limits and independent security review before public exposure.
2. On the target host, validate only: `docker compose --env-file .env.server -f deploy/compose.yaml config --quiet`. Do not paste expanded `docker compose config` output, which can contain private environment values.
3. Build and deploy only as a separate owner action after review. Commands that create containers, request certificates or publish ports were **not run** during implementation. Keep a single worker and one durable data volume. The images run API/web as non-root with read-only root filesystems; the API data volume remains writable. Protect that volume and keep signing keys in separate owner processes.
4. The Dockerfiles build from official Python/Node images; package versions are pinned in repository locks. Base-image tags are currently mutable. Resolve/review immutable image digests and perform image scans on the actual release host before acceptance; no digest was invented. Caddy's official image manages its own certificate/config volumes.

Default web mode is paper. Mainnet public market data still does not enable execution. Configuring `AGENT_PROVIDER=anthropic` requires the model/key and enables paid model requests only within coded call budgets. Token mint, native gas, treasury funding, partner credentials and separate financial enablement remain explicit operational inputs.

## Verified and unverified

52 focused public/local boundary, auth and release tests pass, including exact public-origin EOA sign-in, proxy secret refusal, forged forwarded identity and concurrent-connection refusal. The 58 Node wallet/consent tests and standalone Next production build pass. Compose parses successfully using synthetic reserved-domain credentials without contacting a remote host.

Docker CLI 29.0.1 is installed, but its Linux daemon is unavailable on this workstation (`dockerDesktopLinuxEngine` pipe missing). Consequently, container image builds, Caddy config execution, Linux runtime UID/volume behavior, actual HTTPS, host restore and network/firewall acceptance remain **unverified**. The implementation does not start Docker Desktop or deploy a server to hide that gap. Off-machine backup/notification code is a separate substage, and independent review remains external work.

References: [Compose profiles](https://docs.docker.com/compose/how-tos/profiles/), [Caddy reverse proxy/header behavior](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), installed Next.js `output`/standalone documentation. The repository's applied [security-launch-audit skill](C:/Users/User/.codex/skills/security-launch-audit/SKILL.md) informed the review; it does not certify the application.
