# Claw Desk development rules

- Work on local `lobster-desk` (renamed from `codex/mvp-foundation` at the owner's explicit request). Commit every completed roadmap substage. Never push; the owner pushes manually.
- Keep `docs/ROADMAP.md` current and identify partial integrations honestly.
- Never commit secrets, private keys, local databases, or fabricated production metrics.
- Default to paper execution. Public market data does not mean real execution.
- Models can propose or veto; deterministic code owns risk, capital, and execution permissions.
- Do not submit real orders, transfer funds, deploy, or launch a token while implementing local software.
- Preserve proposal-to-fill audit trails, idempotency, Decimal money arithmetic, and fail-closed data checks.
- Test financial invariants and recovery paths. Run the web production build before a completed UI substage.
- The UI and repository documentation use English. User-facing progress in this chat uses Russian.

