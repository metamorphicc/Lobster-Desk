# Start autonomous paper agents

The prepared local preset needs one Anthropic API key. It uses public Hyperliquid BTC data without an exchange key, one configured model in separate research/critic/analyst/risk roles, a 60-day hourly research window and simulated USDC. The banker, sizing and permissions remain deterministic code.

```powershell
npm run setup:agents
```

Open `.env.agents` in the repository root and fill **only** `ANTHROPIC_API_KEY`. This ignored file is never committed. The preset already supplies `ANTHROPIC_MODEL=claude-sonnet-5-5`; change the model ID if your provider account requires another structured-output-capable model. No key belongs in chat, a screenshot or `NEXT_PUBLIC_*` variables.

```powershell
npm run agents:check
npm run agents
```

Open `http://127.0.0.1:3000`, then **Research**. Stop a previous local server occupying ports 3000/8000 before starting a second copy. Ctrl+C stops both children. Do not run multiple workers against the same paper database; the existing local lease enforces this.

The preset uses `data/agents-paper.db`, separate from the manual/demo `data/lobster.db` and previous `data/tryout.db`. It does not read or require exchange private keys. Existing process environment values take precedence over the preset; the configuration check shows the effective model/source without printing the key. The legacy default `npm run dev` remains synthetic/scripted with autonomous research off unless explicitly configured.

The first cohort can take several minutes to fetch/validate history, call the researcher, run tests and call the critic. A failed strategy is an expected outcome: agents may stay flat indefinitely. Later cohorts default to once per 24 hours; current signals use the latest closed hourly bar and the existing review pipeline. Historical gates, no signal, risk veto, stale data, price gaps and occupied capital can all prevent a trade.

`agents:check` is local validation only; it makes no provider request and cannot verify billing, permissions or available credits. Real Anthropic requests have not been acceptance-tested without the owner's key. API failures/refusals are recorded as failed cohorts, with no automatic replay. Separate daily call ceilings are 4 for research (maximum 2/cohort) and 100 for setup reviews (maximum 2/pitch); output limits do not guarantee a dollar budget. Configure a provider-side spending limit for a monetary ceiling.

## Included economics

The Treasury tab shows the agreed 0.05% entry builder fee, 40% agent capital / 20% team / 40% charity earmarks, and 50% of eligible net realized trading profit for buyback followed by burning. The receipt book remains independent of simulated trading. No virtual profit is presented as received revenue.

## External steps that an API key cannot complete

- Real exchange trading: funded testnet acceptance, wallet permissions, actual order/protection evidence and a separately reviewed mainnet implementation. Current user writer is locked.
- Collected builder fees: actual user volume, builder eligibility/approval, exchange receipts and reconciliation. Local fee plans do not create revenue.
- Donations: selected recipients, settlement method and actual payments/receipts.
- Buyback/burn: token network and contract, available funds, reserve policy and actual reviewed chain transactions. The accounting policy is implemented; purchase/burn execution is not implemented or activated.
- Public launch: hosting/domain, public authentication, operational controls and independent review.

These remain open deliberately and are not represented as “just enter API keys.” No jurisdiction choice or token deployment is required to run local research/paper trading.

Provider references checked 2026-10-17: [model IDs](https://platform.claude.com/docs/en/models/overview), [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). Schema constraints are described to the model and independently enforced locally; no generated code is executed.
