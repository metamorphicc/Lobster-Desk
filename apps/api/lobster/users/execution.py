"""User-owned testnet orchestration rehearsal with an unconditionally locked writer.

The owner postponed funded acceptance. This module deliberately has no unlock flag.
"""
from decimal import Decimal as D
from pathlib import Path

from ..domain import Capital, utcnow
from ..execution.broker import TestnetBroker
from ..execution.contracts import ReviewedSetup, fingerprint
from ..execution.ledger import ExecutionLedger
from ..execution.signer import TestnetSigner
from .fees import require_fresh
from .service import amount


class LockedUserGateway:
    def __init__(self, reader): self.reader = reader
    def __getattr__(self, name): return getattr(self.reader, name)
    async def send(self, envelope):
        raise ValueError("User exchange transport is locked pending funded acceptance and review.")


class PlanSigner(TestnetSigner):
    def __init__(self, key, owner, rules, plan, profile, deadline_ms):
        super().__init__(key, owner, rules, D("50"), builder=profile["builder"], builder_fee_tenths_bps=profile["fee_tenths_bps"])
        self.plan, self.deadline_ms = plan, deadline_ms

    def order(self, order, nonce, now_ms, deadline_ms=None):
        if order.kind == "entry":
            entry = self.plan["entry"]
            limit = D(entry["limit_price"])
            if (order.quantity > D(entry["quantity"]) or order.side != entry["side"]
                    or (order.price > limit if order.side == "buy" else order.price < limit)):
                raise ValueError("Refreshed entry exceeds the user's exact quantity/limit consent.")
            deadline_ms = min(self.deadline_ms, deadline_ms) if deadline_ms is not None else self.deadline_ms
        # Fee approval revocation must not make protective/reduce-only orders
        # depend on a new fee authorization. Entry alone carries the builder fee.
        return super().order(order, nonce, now_ms, deadline_ms, include_builder=order.kind == "entry")

    def leverage(self, value, nonce, now_ms):
        if now_ms >= self.deadline_ms or value != self.plan["entry"]["leverage"]:
            raise ValueError("User leverage consent expired or changed.")
        return super().leverage(value, nonce, now_ms)


class UserLedger(ExecutionLedger):
    def bind(self, capital, owner): self.capital, self.owner = capital, owner

    def stage(self, setup, order, rules):
        return super().stage(setup, order, rules, audit_binding=self.audit_binding)

    def observe_capital(self, account, policy):
        if account.address.lower() != self.owner or not -2 <= (utcnow() - account.observed_at).total_seconds() <= 15:
            raise ValueError("Fresh matching user capital is required.")
        reference = self.capital.get(self.owner)
        if not reference: raise ValueError("Establish user observation references before staging.")
        halted = self.snapshot()["control"]["halt_reason"]
        flows = D(reference["cashflows"])
        # UserCapital already enforces the stricter deposit-neutral loss basis.
        # Adjust reference levels into physical equity units for the broker's risk code.
        return Capital(equity=account.equity, available_cash=account.withdrawable,
            day_start_equity=max(D("0"), D(reference["day_reference"]) + flows),
            high_water_equity=max(D("0"), D(reference["high_water"]) + flows),
            occupied=bool(account.btc_size or account.other_positions or account.open_order_count),
            paused=bool(halted or reference["halt_reason"] or reference["stale"]))


class UserExecution:
    """No HTTP registration, financial RPC or live writer. One canonical DB per owner/agent."""
    def __init__(self, *, store, intents, plans, capital, service, owner, intent_id, gateway, key, root: Path, rules):
        profile = intents.profile(owner)
        intent = intents.get(owner, intent_id)
        if not profile or not intent or intent["status"] not in {"verified_local", "claimed_offline"}:
            raise ValueError("An owner-bound verified offline intent/profile is required.")
        plan = plans.get(owner, intent["plan_id"])
        immutable = {k: v for k, v in (plan or {}).items() if k not in {"plan_hash", "expired", "observation"}}
        if not plan or fingerprint(immutable) != intent["plan_hash"] or plan["address"] != owner:
            raise ValueError("The saved private user plan changed.")
        episode = store.get_episode(plan["episode_id"])
        setup = ReviewedSetup.from_episode(episode, store.policy)
        if setup.approval_hash != plan["approval_hash"] or setup.policy_version != plan["policy_version"]:
            raise ValueError("The current review does not match the user plan.")
        if gateway.account_address.lower() != owner or service.settings.builder_address != profile["builder"] or service.settings.builder_fee_tenths_bps != profile["fee_tenths_bps"]:
            raise ValueError("User gateway/builder identity differs from the consent profile.")
        signer = PlanSigner(key, owner, rules, plan, profile, intent["expires_ms"])
        if plan["entry"]["asset_id"] != rules.asset_id:
            raise ValueError("The preview's BTC market identity changed.")
        if signer.address.lower() != profile["agent"]:
            raise ValueError("The local API key does not match this user's unique public profile.")
        self.owner, self.profile, self.intent, self.plan = owner, profile, intent, plan
        self.intents, self.capital, self.service, self.store = intents, capital, service, store
        self.setup = setup.model_copy(update={"approved_quantity": min(setup.approved_quantity, D(plan["entry"]["quantity"]))})
        path = root.resolve() / owner / (profile["agent"] + ".sqlite3")
        if path.resolve() == Path(store.engine.url.database).resolve():
            raise ValueError("The user execution journal must be separate from the application database.")
        self.ledger = UserLedger("sqlite:///" + path.as_posix(), owner, profile["agent"])
        self.ledger.bind(capital, owner)
        self.ledger.audit_binding = {"user_intent_id": intent_id, "user_plan_id": plan["id"],
            "user_plan_hash": plan["plan_hash"], "user_profile_hash": intent["profile_hash"], "user_proof_hash": intent["proof_hash"]}
        # Tighter cost assumptions than project defaults, never cheaper than preview.
        rate = D(plan["fees"]["reported_taker_rate"]) + D(plan["fees"]["builder_fee_rate"])
        policy = store.policy.model_copy(update={"fee_rate": max(store.policy.fee_rate, rate)})
        self.broker = TestnetBroker(self.ledger, LockedUserGateway(gateway), signer, armed=False,
            policy=policy, entry_guard=self.entry_guard)

    async def entry_guard(self, account):
        now = int(utcnow().timestamp() * 1000)
        current = self.intents.get(self.owner, self.intent["id"])
        if not current or current["status"] != "claimed_offline":
            raise ValueError("The exact user proof must be claimed before any entry checkpoint.")
        staged = next((trade for trade in self.ledger.snapshot()["trades"] if trade["id"] == self.setup.episode_id), None)
        if staged and staged.get("audit_binding") != self.ledger.audit_binding:
            raise ValueError("The staged execution belongs to a different user consent.")
        if now < self.intent["nonce"] - 1000 or now >= self.intent["expires_ms"]:
            raise ValueError("The user's exact trade consent expired or its clock is invalid.")
        gateway = self.broker.gateway
        if await gateway.info("userAbstraction", user=self.owner) != "disabled":
            raise ValueError("Only explicitly observed standard account scope is supported; default/unified/portfolio scope is refused.")
        if await gateway.info("userAbstraction", user=self.profile["builder"]) != "disabled":
            raise ValueError("The builder must have explicitly observed standard account scope.")
        builder = await gateway.info("clearinghouseState", user=self.profile["builder"])
        stamp = builder.get("time")
        if type(stamp) is not int or not -2000 <= now - stamp <= 15000 or D(amount(builder["marginSummary"]["accountValue"])) < 100:
            raise ValueError("Fresh eligible builder capital is not established.")
        if not await gateway.agent_approved(self.profile["agent"]):
            raise ValueError("The user's dedicated API wallet is no longer approved.")
        state = await self.service.inspect(self.owner)
        require_fresh(state, self.owner)
        if (state["builder_address"] != self.profile["builder"] or state["builder_fee_tenths_bps"] != self.profile["fee_tenths_bps"]
                or state["builder_approval_status"] != "approved"
                or D(amount(state["reported_taker_rate"])) > D(self.plan["fees"]["reported_taker_rate"])):
            raise ValueError("Current builder approval, fee identity or observed costs exceed user consent.")
        if state["positions"] or state["open_orders"] or D(amount(state["equity"])) != account.equity or D(amount(state["withdrawable"])) != account.withdrawable:
            raise ValueError("Fresh flat user observations disagree; entry waits for consistent account state.")
        reference = self.capital.get(self.owner)
        if not reference: raise ValueError("User cash-flow references are not established.")
        end = state.get("exchange_time_ms")
        if type(end) is not int or end < reference["cursor_ms"]:
            raise ValueError("The user accounting cursor is missing or regressed.")
        start = max(reference["baseline_ms"], reference["cursor_ms"] - 5000)
        try:
            receipts = await self.service.capital_history(self.owner, start, end)
            reference = self.capital.observe(self.owner, state, start, receipts, complete=True)
        except ValueError:
            self.capital.halt(self.owner, "Entry accounting coverage could not be established; owner review required.")
            raise
        if reference["stale"] or reference["halt_reason"]:
            raise ValueError("A user accounting halt blocks entry.")

    async def stage_offline(self):
        self.intents.claim_offline(self.owner, self.intent["id"], self.plan)
        # Claim and trade staging are separate databases. Crash/failure after claim
        # requires inspection, never a second entry claim or new nonce ledger.
        return await self.broker.stage(self.setup)

    def status(self):
        return {"intent_id": self.intent["id"], "plan_id": self.plan["id"], "address": self.owner,
            "ledger": self.ledger.snapshot(), "exchange_submission_enabled": False,
            "note": "Local user orchestration rehearsal; exchange writer is unconditionally locked."}
