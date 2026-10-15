# Architecture and authority

## Scope

Local-first monorepo: Next.js web application, FastAPI service, a single market/decision worker, SQLAlchemy persistence. SQLite is the zero-configuration local database; PostgreSQL is supported through `DATABASE_URL` and intended for hosted operation. Deploy only one worker until durable leader election is added.

## Decision flow

`pitch -> snapshot -> analyst -> risk reviewer -> deterministic risk -> capital reservation -> final validation -> paper fill -> protection -> close -> report`

Pitches describe a setup, not executable code. They cannot select tools, change prompts, change policy, change market, or access keys. A proposal's hash binds its direction, levels, size policy and market snapshot to its approval. Approvals expire and are rechecked at execution.

The analyst proposes or rejects. The risk reviewer can only veto. The banker reports the deterministic capital result. The paper executor is software; it is not an LLM. No model holds signing credentials.

## Modes

- `MARKET_SOURCE=demo`: labelled synthetic prices, reproducible local fixtures.
- `MARKET_SOURCE=hyperliquid`: read-only public mainnet market data. Failure marks data unavailable/stale; it never switches to demo.
- `MARKET_SOURCE=hyperliquid-testnet`: public testnet prices drive the paper review pipeline; eligible bound reviews can be separately staged for testnet submission.
- `AGENT_PROVIDER=demo`: labelled deterministic scripted reviewers; not represented as real AI.
- `AGENT_PROVIDER=anthropic`: optional hosted model adapter, credentials supplied only through environment variables, strict validated outputs and bounded calls.
- The tank remains `paper`. The HTTP Testnet workbench can inspect public account state and save/cancel unsent local intents. It has no order submission endpoint and loads no signing key.
- A separately enabled owner CLI uses the official SDK, fixed testnet host and dedicated API wallet. Its own ledger owns nonces, command claims, fills and confirmed protection. See `TESTNET.md`; funded exchange behavior remains unverified.

## Accounting

Paper entry/exit taker fees and adverse slippage are modeled. Funding is excluded and disclosed. Open PnL is separate from realized net PnL. Entry fees are expensed immediately; close profit includes exit fees without charging entry fees twice. Trade-level net PnL includes both fees. Initial capital is a synthetic deposit, not earnings.

Builder revenue is zero until an actual user trading integration exists. A fee calculator is an illustration, never a revenue counter. Project trades cannot create external fee revenue by charging themselves.

## Durability and concurrency

Account updates, reservations, fills and journal events share a database transaction. SQLite uses an immediate write transaction; PostgreSQL locks the account row. Unique client request IDs prevent duplicate pitch submission. A unique proposal-to-position association prevents repeated fills after a timeout or restart. Events are append-only at the application layer and exportable; they are not described as an immutable blockchain record.

## Boundaries

The local API binds to loopback and is not a public multi-tenant service. Operator mutations require a configured token. Public hosting requires identity, durable abuse controls, TLS, secrets management and operational review. The paper broker must never be relabelled as an exchange execution adapter.

