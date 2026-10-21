# Local launch appearance preview

Open **http://127.0.0.1:3000/** to view owner-requested invented financial figures directly on The tank. No query parameter or redirect is used. The sidebar has a visible **LOCAL PREVIEW / Illustrative figures** badge (below navigation on mobile). No API keys are required for this visual preview.

The initial example is $1,204.60 equity, +$284.60 trading profit, $142.30 allocated to charity and $80.00 sent. The numbers change every six seconds; the sequence includes gains and losses. Allocated charity stays at half the illustrative net profit. The example starting principal is $1,000; equity includes profit less the illustrative amount sent, and includes the outstanding charity reserve. These are visual fixtures, never production metrics or evidence of a payment.

Only the financial figures in the tank's performance strip and animated room are overridden. BTC prices/candles, actual setup counts, research, journals, wallet views, server responses, execution permissions, accounting and databases remain unchanged. No financial action is submitted. The preview does not create example orders or journal records.

The temporary setting `LOCAL_LAUNCH_PREVIEW_ENABLED` in `apps/web/src/lib/preview-settings.ts` is currently **true** at the owner's request. To remove the invented figures, set it to **false**, then rebuild/restart the web app (`npm run build`, then the normal web start command). No database cleanup or fixture deletion is needed. The preview only accepts loopback hostnames and is disabled in the operator workspace and other tabs. Public website hostnames cannot activate it. URL parameters cannot override a disabled setting. No setting is persisted in local storage or cookies.

Adding a model API key does not disable the preview and does not activate real trading. Disable the source setting before checking connected account observations; follow `AGENT-SETUP.md` and `HANDOFF.md` for the separate integration boundaries.
