# Runner observations and external alerts

`npm run ops` performs a local read-only API/journal observation and records an alert transition. It does **not** send notifications by default. `npm run ops -- --watch` repeats every 15 seconds. The API origin is fixed to loopback; public-single-host internal probes additionally use the configured private proxy token. `OPS_APPLICATION_PATH` must identify the same application database as the API; a hashed instance binding detects accidental monitoring of another workspace. Missing/stale/malformed API observations produce a static critical alert rather than a healthy result.

The monitor reads every canonical financial journal in `execution_catalog`, private financial permission handoffs and Solana operation state and strategy-author settlement/payment records. It detects uncertain commands/transactions, missing journals, exposure needing review and absent/stale runner heartbeat while financial work is active. Runner heartbeats report attempt/success separately. A telemetry write failure cannot authorize or block an order: it leaves stale telemetry for the independent monitor to detect. The monitor itself has no exchange submission method or financial key map.

## Notification delivery

Set the private `.env.ops` fields `OPS_ALERTS_ENABLED`, `OPS_ALERT_WEBHOOK`, `OPS_ALERT_FORMAT` and, for generic HTTPS receivers, a separate `OPS_ALERT_WEBHOOK_SECRET` of at least 32 characters. Supported formats are generic JSON and official Slack incoming webhooks. URLs contain credentials and must remain private. No channel, endpoint or real notification has been configured by the developer.

Only the owner may activate delivery:

```powershell
npm run ops -- --watch --notify --arm
```

The persistent outbox records state transitions, suppresses unchanged observations, emits recovery transitions and supersedes unattempted stale history. Each event has a stable ID. The generic receiver must deduplicate `Idempotency-Key` / `X-Lobster-Event-ID` and verify:

```text
HMAC-SHA256(shared_secret, X-Lobster-Timestamp + "." + exact_request_body)
```

Compare the lowercase hex result with `X-Lobster-Signature` using a constant-time comparison; reject stale timestamps and duplicate IDs. TLS verification is always enabled and redirects are refused. Slack uses its official `text` payload and secret webhook URL; it does not provide the generic receiver's deduplication guarantee.

Delivery claims persist before HTTP. Timeout/rejection retries keep the event ID, use bounded exponential backoff (one to fifteen minutes) and stop after five attempts. A process death after claim recovers the same event after its deadline. This is **bounded at-least-once delivery**, so a receiver without deduplication can see duplicates after an ambiguous response. Exhausted attempts remain `failed` locally for owner inspection; the monitor does not pretend a webhook outage can report itself through that same failed webhook. An independent external uptime monitor is still required to detect loss of the entire host/monitor.

Outbound payloads use a strict allowlist of static codes/scopes, severity and count. Raw exception text, paths, account addresses, signatures, model input/output, donor data and arbitrary API strings cannot be forwarded. The operations state database is included in recovery inventory; no webhook URL/HMAC key is stored in the outbox.

## Verification

Eleven focused tests cover restart/concurrent deduplication, explicit arming, authenticated/redacted payloads, recovery/superseded history, timeout/backoff/exhaustion, actual broker uncertainty/heartbeat age, scope/stale-API refusal and invalid destinations. Webhook requests use HTTP mocks. A live local demo observation returned an empty alert set with `notification_attempted=false` on 2026-10-17. No external message was sent.

The owner must choose and configure the real notification endpoint, verify delivery/recovery there and arrange host-level monitoring. The code does not create a recurring Codex automation, send a message to another account or contact a provider during implementation. Reference: [official Slack incoming webhook format and secret handling](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/).
