"""Fixed-host observed revenue ingestion; estimates/paper PnL never become cash."""
from datetime import datetime, timezone
from decimal import Decimal as D
import json

from ..domain import utcnow
from ..execution.contracts import fingerprint
from ..execution.gateway import HyperliquidMainnet
from .book import TreasuryEntry


class RevenueImporter:
    def __init__(self, book, client, builder):
        self.book, self.gateway, self.builder = book, HyperliquidMainnet(client, builder), builder.lower()
        with book.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS revenue_sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS revenue_observations (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    async def sync_builder(self, start_ms: int, end_ms: int):
        if not 0 <= start_ms <= end_ms <= int(utcnow().timestamp()*1000) or end_ms - start_ms > 7 * 86400000:
            raise ValueError("Builder ingestion requires an exact non-future window of at most seven days.")
        referral = await self.gateway.info("referral", user=self.builder)
        # Claims merge referrer and builder earnings. Only a dedicated builder
        # with explicitly empty referral states can be attributed automatically.
        referrers = referral.get("referrerState", {}).get("data", {}).get("referralStates")
        if referrers != []: raise ValueError("Mixed/unknown referral income cannot be labelled as builder revenue.")
        builder_rewards = D(referral["builderRewards"])
        claimed = D(referral["claimedRewards"])
        # These fields are observations, not interchangeable lifetime counters.
        # In particular claimedRewards may exceed the currently shown builderRewards.
        if not builder_rewards.is_finite() or not claimed.is_finite() or min(builder_rewards, claimed) < 0:
            raise ValueError("Builder/referral aggregate observations cannot establish attribution.")
        cursor, rows, seen = start_ms, [], {}
        for _ in range(16):
            page = await self.gateway.info("userNonFundingLedgerUpdates", user=self.builder, startTime=cursor, endTime=end_ms)
            if not isinstance(page, list) or len(page) > 5000: raise ValueError("Malformed revenue history.")
            last, added = cursor, 0
            for item in page:
                if type(item.get("time")) is not int or not cursor <= item["time"] <= end_ms: raise ValueError("Invalid revenue timestamp.")
                if item["delta"]["type"] == "rewardsClaim" and not isinstance(item["delta"].get("amount"), str):
                    raise ValueError("Exact claimed reward amount required.")
                last = max(last, item["time"])
                identity = fingerprint({"builder": self.builder, "hash": item["hash"], "time": item["time"], "type": item["delta"]["type"]})
                value = fingerprint(item)
                if identity in seen and seen[identity] != value: raise ValueError("Conflicting upstream receipt.")
                if identity not in seen:
                    rows.append((identity, item)); seen[identity] = value; added += 1
            if len(page) < 500: break
            if last <= cursor or not added: raise ValueError("Revenue history is truncated.")
            cursor = last
        else: raise ValueError("Revenue history page budget exhausted.")
        source_id = "builder:" + self.builder
        with self.book.transaction() as db:
            previous = db.execute("SELECT payload FROM revenue_sources WHERE id=?", (source_id,)).fetchone()
            state = json.loads(previous[0]) if previous else None
            if state and (start_ms > state["cursor_ms"] or end_ms < state["cursor_ms"]): raise ValueError("Revenue cursor gap/rollback.")
            imported = []
            recorded = sum((D(json.loads(row[0])["event"]["delta"]["amount"]) for row in
                db.execute("SELECT payload FROM revenue_observations WHERE json_extract(payload, '$.source')=?", (source_id,))), D(0))
            for identity, item in rows:
                delta = item["delta"]
                if delta["type"] != "rewardsClaim": continue
                raw = delta["amount"]
                if not isinstance(raw, str): raise ValueError("Exact claimed reward amount required.")
                amount = D(raw)
                if not amount.is_finite() or amount <= 0 or amount != amount.quantize(D("0.000001")): raise ValueError("Invalid USDC claim.")
                if delta.get("token", "USDC") != "USDC": raise ValueError("Unsupported reward currency.")
                tx = item["hash"]
                if not isinstance(tx, str) or len(tx) != 66 or not tx.startswith("0x"): raise ValueError("Malformed claim transaction hash.")
                int(tx[2:], 16)
                observation = {"source": source_id, "event": item, "referral_observation_hash": fingerprint(referral)}
                existing = db.execute("SELECT payload FROM revenue_observations WHERE id=?", (identity,)).fetchone()
                if existing:
                    if json.loads(existing[0])["event"] != item: raise ValueError("Recorded reward receipt changed.")
                    continue
                if state and item["time"] <= state["cursor_ms"]: raise ValueError("Late receipt changed an imported interval.")
                recorded += amount
                if recorded > claimed:
                    raise ValueError("Observed claims exceed the exchange's claimed-reward observation.")
                entry = TreasuryEntry(id=identity, receipt_ref="hl-mainnet-builder:" + identity,
                    evidence_sha256=fingerprint(item), kind="builder_receipt", amount=str(amount),
                    occurred_at=datetime.fromtimestamp(item["time"]/1000, timezone.utc), provenance="owner_supplied_unverified")
                self.book.append_in_transaction(db, entry)
                db.execute("INSERT INTO revenue_observations VALUES (?,?)", (identity, json.dumps(observation)))
                imported.append(identity)
            db.execute("INSERT OR REPLACE INTO revenue_sources VALUES (?,?)", (source_id, json.dumps({"cursor_ms": end_ms,
                "observed_at": utcnow().isoformat(), "builder_rewards_observed": str(builder_rewards),
                "claimed_rewards_observed": str(claimed), "referral_observation_hash": fingerprint(referral)})))
            return {"imported_receipts": imported, "cursor_ms": end_ms, "source": source_id,
                "exchange_observed": True, "cryptographic_finality_verified": False, "transfers_attempted": False}


async def sync_project_settlement(book, runner):
    """Reconcile a flat mainnet account to all owned fills and observed funding.

    Whole-account cumulative settlement avoids assigning hourly funding across
    partial fills incorrectly. Principal movements are excluded by UserCapital.
    """
    if runner.settings.network != "mainnet" or runner.ledger.network != "mainnet":
        raise ValueError("Paper/testnet settlements cannot enter the real receipt book.")
    state, reference = await runner.observe()
    snapshot = runner.ledger.snapshot()
    if state["positions"] or state["open_orders"] or any(t["status"] not in {"closed", "rejected", "expired", "cancelled"} for t in snapshot["trades"]):
        raise ValueError("Settle only a flat account with no unresolved owned commands.")
    # Fills include builder fees inside fee; never subtract the component again.
    net = sum((D(f["closedPnl"]) - D(f["fee"]) for f in snapshot["fills"]), D(0)) + D(reference["funding_observed"])
    performance = D(reference["net_equity_change_excluding_cashflows"])
    if abs(net - performance) > D("0.000001"):
        raise ValueError("Owned fills/funding do not reconcile to cash-flow-neutral flat account performance.")
    if any(type(f["time"]) is not int or not reference["baseline_ms"] < f["time"] <= reference["cursor_ms"] for f in snapshot["fills"]):
        raise ValueError("A fill lies outside complete capital history coverage.")
    if performance != performance.quantize(D("0.000001")):
        raise ValueError("Settlement must be exact to USDC precision.")
    source_id = "project:" + runner.settings.account
    evidence = {"account": state, "reference": reference, "fills": snapshot["fills"],
        "trades": snapshot["trades"], "network": "mainnet"}
    with book.transaction() as db:
        db.execute("CREATE TABLE IF NOT EXISTS revenue_sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        old = db.execute("SELECT payload FROM revenue_sources WHERE id=?", (source_id,)).fetchone()
        old = json.loads(old[0]) if old else None
        if old and (old["baseline_ms"] != reference["baseline_ms"] or reference["cursor_ms"] < old["cursor_ms"]):
            raise ValueError("Project baseline/cursor changed; reconcile the original history.")
        previous = D(old["net_settled"]) if old else D(0)
        if old and reference["cursor_ms"] == old["cursor_ms"] and performance != previous:
            raise ValueError("Conflicting settlement at one observation timestamp.")
        change = performance - previous
        identity = fingerprint({"source": source_id, "baseline": reference["baseline_ms"], "cursor": reference["cursor_ms"]})
        if change:
            book.append_in_transaction(db, TreasuryEntry(id=identity, receipt_ref="hl-mainnet-settlement:" + identity,
                evidence_sha256=fingerprint(evidence), kind="trading_profit" if change > 0 else "trading_loss",
                amount=str(abs(change)), occurred_at=datetime.fromtimestamp(reference["cursor_ms"]/1000, timezone.utc),
                provenance="owner_supplied_unverified"))
        db.execute("INSERT OR REPLACE INTO revenue_sources VALUES (?,?)", (source_id, json.dumps({"baseline_ms": reference["baseline_ms"],
            "cursor_ms": reference["cursor_ms"], "net_settled": str(performance), "evidence_hash": fingerprint(evidence)})))
        return {"source": source_id, "net_settled": str(performance), "new_settlement": str(change),
            "exchange_observed": True, "cryptographic_finality_verified": False, "transfers_attempted": False}
