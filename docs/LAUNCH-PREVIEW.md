# Local launch appearance preview

Open **http://127.0.0.1:3000/?preview=launch** to view owner-requested invented financial figures on The tank. A local preview badge identifies them. No API keys are required for this visual preview.

The initial example is $1,204.60 equity, +$284.60 trading profit, $142.30 allocated to charity and $80.00 sent. The numbers change every six seconds; the sequence includes gains and losses. Allocated charity stays at half the illustrative net profit. The example starting principal is $1,000; equity includes profit less the illustrative amount sent, and includes the outstanding charity reserve. These are visual fixtures, never production metrics or evidence of a payment.

Only the financial figures in the tank's performance strip and animated room are overridden. BTC prices/candles, actual setup counts, research, journals, wallet views, server responses, execution permissions, accounting and databases remain unchanged. No financial action is submitted. The preview does not create example orders or journal records.

To remove all invented figures, open **http://127.0.0.1:3000/** without `?preview=launch`. No rebuild, database cleanup or code deletion is needed. The preview is off by default, only accepts loopback hostnames, and is disabled in the operator workspace and other tabs. A public website hostname cannot activate it. No setting is persisted in local storage or cookies.

Adding a model API key does not disable a URL preview and does not activate real trading. Remove the query parameter before checking connected account observations; follow `AGENT-SETUP.md` and `HANDOFF.md` for the separate integration boundaries.
