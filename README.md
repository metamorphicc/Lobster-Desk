# Lobster Desk

A collective trading desk on Hyperliquid: pitch a BTC strategy, follow three crustacean agents and track decisions and trades.

**Local development. No mainnet order execution, deposits, token, or fee collection is enabled.** Market data and execution modes are independent: live Hyperliquid data can drive simulated trades.

## Structure

- `docs/FEATURES.md`: agreed product features, fee distribution, own-agent donation reserve and implementation status.
- `docs/LAUNCH-PREVIEW.md`: temporary illustrative figures on the local homepage, sidebar preview badge and the source switch for disabling them.
- `docs/VERCEL-PC.md`: web-only Vercel import, with a private runtime HTTPS proxy to the API/agents on your PC; the current hosted view is read-only.
- `apps/api`: FastAPI, deterministic risk/capital controls, paper broker, market feeds, agent adapters, persistent audit journal.
- `apps/web`: Next.js trading tank and pitch interface.
- `docs/ROADMAP.md`: stages, substages, acceptance criteria, and completion status.
- `docs/ARCHITECTURE.md`: financial authority, data flow, and safety boundaries.
- `docs/BACKUP-RESTORE.md`: verified SQLite snapshots and isolated recovery drills.
- `docs/OPERATIONS.md`: local readiness panel, scoped alerts and loopback probe command.
- `docs/RELEASE.md`: local source packages and explicit public-release prerequisites.
- `docs/HANDOFF.md`: current delivery, local operator commands and remaining external/integration gates.
- `docs/ECONOMICS.md` and `docs/BUYBACK-REPORTING.md`: private receipt accounting and disabled token-operation reporting.

## Run locally

Requires Node.js 22+ and Python 3.12+. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements.lock
.\.venv\Scripts\python.exe -m pip install -e apps/api --no-deps
npm install
npm run dev
```

On macOS/Linux, use `python3 -m venv .venv`, then `.venv/bin/python` for the two pip commands. The Node scripts select the local virtual environment automatically on either platform.

Open **http://127.0.0.1:3000**. The API is at **http://127.0.0.1:8000**, with interactive documentation at `/docs`. Stop both services with Ctrl+C. Ports 3000 and 8000 must be available.

The main site reads actual public BTC candles without credentials. It publishes only registered mainnet project setups/fills and fresh project capital observations; missing account data appears as `—`. It does not expose the internal seeded balance or synthetic trade history. Fee allocation is documented in `docs/DISTRIBUTION.md`, outside the main navigation.

The separate `/operator` workspace retains treasury reporting, testnet tools, diagnostics and the paper journal. This read-only workspace is not an authentication boundary; financial controls still require server-side operator authorization, and deployment should restrict operational access. SQLite creates `data/lobster.db` on first launch and stays ignored by Git. The internal $1,000 is simulated capital; `INITIAL_CAPITAL` only applies to a new paper database. It never becomes a public account balance.

To configure the optional modes, copy `.env.example` to `.env` at the repository root:

- `MARKET_SOURCE=hyperliquid` uses read-only public BTC data. Execution stays paper.
- `AGENT_PROVIDER=anthropic` requires your own `ANTHROPIC_API_KEY` and an explicit `ANTHROPIC_MODEL` supporting structured outputs. Model calls incur provider charges. No paid calls were made during development.
- `MAX_REVIEW_CALLS_PER_DAY=100` caps review attempts across restarts, using a UTC day. A normal pitch uses at most two calls. Interrupted calls are not automatically retried.
- Validated pitch requests are limited persistently to 10 per transport peer per 60 seconds; the global review queue holds at most 20 pending setups. See [operational limits](docs/OPERATIONS.md#pitch-admission), including shared proxy budgets and clock behavior.
- `OPERATOR_TOKEN` enables pause/resume/close controls; use at least 24 characters. It is never exposed in the public state response.
- `MARKET_SOURCE=hyperliquid-testnet` evaluates setups on public testnet data. Use a new paper `DATABASE_URL`. The **Testnet** tab can inspect readiness and stage an intent locally; exchange submission requires a separate owner-run signer. See [the testnet guide](docs/TESTNET.md).
- Use a separate `DATABASE_URL` when switching between demo and live-market experiments. Switching feeds with an open position or pending reviewed setup is blocked.
- One paper worker owns each local SQLite database at a time. Duplicate worker startup is refused; the OS releases ownership on exit. Worker-enabled PostgreSQL requires a separate leadership implementation and is refused. See [worker ownership](docs/OPERATIONS.md#local-worker-ownership).

## Try the flow

1. Open **Pitch a setup**, choose long or short, and use sample levels or supply your own.
2. Send the pitch. Watch analyst, risk and capital stages in the shared tank and decision feed.
3. Approved setups wait for their entry trigger. Gaps beyond the allowed deviation expire instead of chasing price.
4. Inspect **Trade journal** for levels, reasons, reviewer metadata, approval binding and closed-trade PnL.
5. Inspect **Treasury** for simulated capital, modeled fees and a clearly hypothetical builder-fee calculator.
6. **Export journal** downloads the complete append-only application event history as JSON.
7. **Testnet → Your testnet account** connects an injected wallet for public data or watches an address. Inspect balances, orders, builder approval, cost illustrations and unsigned consent plans. A separate optional sign-in message establishes a local EOA preview session; public watching grants none. Neither grants trading authority; see [USER-ACCOUNTS.md](docs/USER-ACCOUNTS.md).
8. A verified local session can request a private **user order preview** for an approved, unexpired testnet setup. It sizes against the user's own fresh account with a $50 cap, saves an immutable record and shows the outstanding execution blockers. It sends no exchange order and installs no stop.
9. Under that preview, **Review execution permissions** shows the operator-configured public profile, prepares exact unsigned local/SDK payloads and lists recent private intents. Exports contain no session token. Financial wallet signing and exchange submission stay disabled.

Scripted demo reviewers are deterministic checks, not real AI. Synthetic price, funding and OI figures are labelled. The optional model adapter supplies real reviews but cannot override coded controls. Paper protection runs while this local service is running and has fresh data; it is not an exchange-native stop.

## Verify

```powershell
npm run test:api
npm run test:web
npm run typecheck
npm run build
node scripts/python.mjs scripts/check-market.py
```

The last command is an optional public-network smoke check, separate from deterministic tests. It reads Hyperliquid prices and candles without signing or trading. See `docs/VERIFICATION.md` for the tested scope and limitations.

For a fully offline user lifecycle rehearsal, run `node scripts/python.mjs scripts/user-rehearsal.py --output artifacts/rehearsals/new-run` with a new directory. Five synthetic execution/recovery scenarios run without credentials, wallet, funds or exchange access. The output is labelled fixture evidence, never funded acceptance.

With services running, `node scripts/python.mjs scripts/check-health.py` checks local paper readiness; add `--web` to include the frontend proxy. It does not activate execution or establish production readiness. See [OPERATIONS.md](docs/OPERATIONS.md) for exit codes and alert scope.

Known-advisory checks are recorded with input hashes and repeatable commands in [DEPENDENCY-AUDIT.md](docs/DEPENDENCY-AUDIT.md). They require network access and do not replace application or independent security review.

For a production-mode local frontend after building, run `npm run start --workspace @lobster/web` and start the API separately:

```powershell
node scripts/python.mjs -m uvicorn lobster.main:create_app --factory --app-dir apps/api --host 127.0.0.1 --port 8000
```

## Delivery status

The local paper application and separately gated project/user execution code are implemented; default operation remains paper. Entry fees split 0.02% team / 0.03% bot. User-strategy net profit splits 50% author / 50% bot. Current own-agent eligible net profit splits 50% donation reserve / 50% bot, replacing new buybacks. The public Charity pool separates accrued from sent; recipient/payment integration remains pending. Signed-in users submit attributed strategies and inspect private balances. Author payments use a separate opt-in bounded Hyperliquid process or operator verification of an existing transfer. Source/recipient observations are required; the API does not send payouts. See [strategy sharing](docs/STRATEGY-SHARING.md) and [the delivery handoff](docs/HANDOFF.md).

Funded exchange/wallet/chain acceptance, treasury routing, independent review and public deployment remain external work. All completed substages are committed locally on `lobster-desk`; nothing is pushed automatically.

## Autonomous agents update

For self-generated, historically tested BTC strategies and forward **paper** observation, see [agent setup](docs/AGENT-SETUP.md). Run `npm run setup:agents`, fill `ANTHROPIC_API_KEY` in the ignored `.env.agents`, then `npm run agents:check` and `npm run agents`. The preset contains the model/data configuration; actual provider access remains unverified without a key.

Research results, the current 60/40 bot/team fee split and 50/50 strategy-author profit accounting appear in Research and Treasury. Paper profit is never real revenue. The separate own-agent token policy excludes user-strategy profits. One model API key does not activate real financial execution. See [research mechanics](docs/RESEARCH.md), [distribution policy](docs/DISTRIBUTION.md) and [strategy sharing](docs/STRATEGY-SHARING.md).
