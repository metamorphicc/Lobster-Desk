# Lobster Desk

A public trading tank: pitch a BTC setup, watch three crustacean agents challenge it, and follow the decision through a verifiable paper trade.

**Local development. No mainnet order execution, deposits, token, or fee collection is enabled.** Market data and execution modes are independent: live Hyperliquid data can drive simulated trades.

## Structure

- `apps/api`: FastAPI, deterministic risk/capital controls, paper broker, market feeds, agent adapters, persistent audit journal.
- `apps/web`: Next.js trading tank and pitch interface.
- `docs/ROADMAP.md`: stages, substages, acceptance criteria, and completion status.
- `docs/ARCHITECTURE.md`: financial authority, data flow, and safety boundaries.

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

No environment file or credentials are needed for the scripted demo. SQLite creates `data/lobster.db` on first launch; it survives restarts and is ignored by Git. The initial $1,000 is simulated capital, not a deposit. `INITIAL_CAPITAL` only applies when creating a new database.

To configure the optional modes, copy `.env.example` to `.env` at the repository root:

- `MARKET_SOURCE=hyperliquid` uses read-only public BTC data. Execution stays paper.
- `AGENT_PROVIDER=anthropic` requires your own `ANTHROPIC_API_KEY` and an explicit `ANTHROPIC_MODEL` supporting structured outputs. Model calls incur provider charges. No paid calls were made during development.
- `MAX_REVIEW_CALLS_PER_DAY=100` caps review attempts across restarts, using a UTC day. A normal pitch uses at most two calls. Interrupted calls are not automatically retried.
- `OPERATOR_TOKEN` enables pause/resume/close controls; use at least 24 characters. It is never exposed in the public state response.
- Use a separate `DATABASE_URL` when switching between demo and live-market experiments. Switching feeds with an open position or pending reviewed setup is blocked.

## Try the flow

1. Open **Pitch a setup**, choose long or short, and use sample levels or supply your own.
2. Send the pitch. Watch analyst, risk and capital stages in the shared tank and decision feed.
3. Approved setups wait for their entry trigger. Gaps beyond the allowed deviation expire instead of chasing price.
4. Inspect **Trade journal** for levels, reasons, reviewer metadata, approval binding and closed-trade PnL.
5. Inspect **Treasury** for simulated capital, modeled fees and a clearly hypothetical builder-fee calculator.
6. **Export journal** downloads the complete append-only application event history as JSON.

Scripted demo reviewers are deterministic checks, not real AI. Synthetic price, funding and OI figures are labelled. The optional model adapter supplies real reviews but cannot override coded controls. Paper protection runs while this local service is running and has fresh data; it is not an exchange-native stop.

## Verify

```powershell
npm run test:api
npm run typecheck
npm run build
node scripts/python.mjs scripts/check-market.py
```

The last command is an optional public-network smoke check, separate from deterministic tests. It reads Hyperliquid prices and candles without signing or trading. See `docs/VERIFICATION.md` for the tested scope and limitations.

For a production-mode local frontend after building, run `npm run start --workspace @lobster/web` and start the API separately:

```powershell
node scripts/python.mjs -m uvicorn lobster.main:create_app --factory --app-dir apps/api --host 127.0.0.1 --port 8000
```

## Delivery status

Stages 0–4 implement the local paper MVP. Exchange testnet execution, user wallet trading, actual builder-fee collection and token operations remain separate roadmap stages. This release has no mainnet order endpoint and should not be deployed as a public financial service.

Every completed substage is a separate local commit on `codex/mvp-foundation`. The `origin` remote points to `https://github.com/metamorphicc/Lobster-Desk.git`; nothing is pushed automatically.

