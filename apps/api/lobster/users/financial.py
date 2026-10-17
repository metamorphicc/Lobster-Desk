"""Explicit testnet financial consent, distinct from sign-in and offline rehearsal."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import secrets
from typing import Literal
from pathlib import Path
import json
import sqlite3
from contextlib import closing

from hyperliquid.utils.signing import user_signed_payload
from pydantic import Field
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint, TESTNET_URL, MAINNET_URL
from .intents import Profile, recover, typed_intent


class FinancialRequest(Contract):
    kind: Literal["agent", "builder", "revoke_builder", "trade"]
    plan_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class FinancialProof(Contract):
    signature: str = Field(pattern=r"^0x[0-9a-fA-F]{130}$")


class Base(DeclarativeBase): pass


class FinancialJob(Base):
    __tablename__ = "user_financial_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    request_key: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class UserFinancial:
    def __init__(self, store, intents, plans):
        self.store, self.intents, self.plans = store, intents, plans
        self.network = intents.network
        if plans.network != self.network: raise ValueError("Financial plan/profile networks differ.")
        Base.metadata.create_all(store.engine)

    @staticmethod
    def check_binding(job):
        keys = ("id", "owner", "kind", "plan_id", "nonce", "expires_ms", "profile_hash", "network", "scope",
            "typed_data", "action", "plan_hash", "episode_id")
        if fingerprint({k: job[k] for k in keys if k in job}) != job["binding_hash"]:
            raise ValueError("Financial job immutable binding integrity failed.")

    def validate_plan(self, owner, plan, profile):
        immutable = {k: v for k, v in (plan or {}).items() if k not in {"plan_hash", "expired", "observation"}}
        if (not plan or plan["address"] != owner or plan["network"] != self.network or profile["network"] != self.network or fingerprint(immutable) != plan["plan_hash"]
                or plan["fees"]["builder_address"] != profile["builder"] or plan["fees"]["builder_fee_tenths_bps"] != profile["fee_tenths_bps"]):
            raise ValueError("Financial consent requires an exact matching private user plan/profile.")

    def prepare(self, owner, body, request_key):
        now = int(utcnow().timestamp()*1000)
        with self.store.transaction() as session:
            previous = session.scalar(select(FinancialJob).where(FinancialJob.owner == self.intents.key(owner), FinancialJob.request_key == request_key))
            if previous:
                if previous.payload["kind"] != body.kind or previous.payload.get("plan_id") != body.plan_id: raise ValueError("Request identity conflict.")
                return previous.payload
            row = session.get(Profile, self.intents.key(owner))
            if not row: raise ValueError("Operator must register a dedicated public API-wallet profile first.")
            profile = row.payload
            nonce = max(now, profile["last_nonce"] + 1)
            if nonce > now + 1000: raise ValueError("Financial consent nonce is ahead of the local clock.")
            expires = now + 30000
            job = {"id": secrets.token_hex(16), "owner": owner, "kind": body.kind, "plan_id": body.plan_id,
                "nonce": nonce, "expires_ms": expires, "profile_hash": fingerprint({k: v for k, v in profile.items() if k != "last_nonce"}),
                "status": "unsigned", "network": self.network, "scope": self.network+"-financial-consent-v1", "proof": None}
            if body.kind == "trade":
                # Read through the current SQL session, avoiding a nested write lock.
                from .orders import UserPlan
                saved = session.get(UserPlan, body.plan_id) if body.plan_id else None
                plan = saved.payload if saved and saved.address == self.plans.key(owner) else None
                self.validate_plan(owner, plan, profile)
                deadline = int(datetime.fromisoformat(plan["expires_at"]).timestamp()*1000)
                if deadline <= now: raise ValueError("Refresh the private order preview before financial consent.")
                expires = min(expires, deadline)
                typed = typed_intent(owner, profile, plan, nonce, expires, network=self.network)
                typed["domain"]["name"] = "Lobster Desk Execution Consent"
                job.update(plan_hash=plan["plan_hash"], episode_id=plan["episode_id"], expires_ms=expires, typed_data=typed)
            else:
                if body.plan_id is not None: raise ValueError("Permission plans cannot bind an unrelated trade ID.")
                agent = body.kind == "agent"
                action = {"type": "approveAgent" if agent else "approveBuilderFee", "hyperliquidChain": "Testnet" if self.network == "testnet" else "Mainnet",
                    "signatureChainId": "0x66eee" if self.network == "testnet" else "0xa4b1", "nonce": nonce}
                if agent: action.update(agentAddress=profile["agent"], agentName="Lobster Desk " + self.network)
                else:
                    from decimal import Decimal
                    action.update(builder=profile["builder"], maxFeeRate=(str(Decimal(profile["fee_tenths_bps"])/1000) + "%") if body.kind == "builder" else "0%")
                fields = [{"name": "hyperliquidChain", "type": "string"}] + ([{"name": "agentAddress", "type": "address"}, {"name": "agentName", "type": "string"}] if agent
                    else [{"name": "maxFeeRate", "type": "string"}, {"name": "builder", "type": "address"}]) + [{"name": "nonce", "type": "uint64"}]
                job.update(action=action, typed_data=user_signed_payload("HyperliquidTransaction:" + ("ApproveAgent" if agent else "ApproveBuilderFee"), fields, action))
            row.payload = profile | {"last_nonce": nonce}
            job["binding_hash"] = fingerprint({k: v for k, v in job.items() if k not in {"status", "proof"}})
            session.add(FinancialJob(id=job["id"], owner=self.intents.key(owner), request_key=request_key, payload=job))
            return job

    def get(self, owner, job_id):
        with self.store.transaction() as session:
            row = session.get(FinancialJob, job_id)
            return row.payload if row and row.owner == self.intents.key(owner) else None

    def jobs(self, owner):
        with self.store.transaction() as session:
            return [r.payload for r in session.scalars(select(FinancialJob).where(FinancialJob.owner == self.intents.key(owner)).order_by(FinancialJob.payload["nonce"].as_integer()))]

    def context(self, owner, root, enabled):
        profile = self.intents.profile(owner)
        snapshot = None
        if profile:
            path = Path(root).resolve() / owner / (profile["agent"] + ".sqlite3")
            if path.exists():
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
                    control = json.loads(db.execute("SELECT payload FROM testnet_control WHERE id=1").fetchone()[0])
                    if (control["network"], control["account"], control["signer"]) != (self.network, owner, profile["agent"]):
                        raise ValueError("Private execution journal identity mismatch.")
                    snapshot = {"network": self.network, "control": control,
                        "trades": [json.loads(r[0]) for r in db.execute("SELECT payload FROM testnet_trades ORDER BY rowid DESC LIMIT 20")],
                        "events": [json.loads(r[0]) for r in db.execute("SELECT payload FROM testnet_events ORDER BY id DESC LIMIT 30")]}
        return {"schema": "lobster-user-financial-context-v1", "owner": owner, "network": self.network, "enabled": enabled,
            "profile": {k: v for k, v in profile.items() if k != "last_nonce"} if profile else None,
            "jobs": [self.view(job) for job in self.jobs(owner)[-30:]], "execution": snapshot,
            "submission_from_api": False, "note": "Financial " + self.network.upper() + " signing is separate from read-only previews. The owner-run process holds only dedicated API keys."}

    @staticmethod
    def view(job):
        now = int(utcnow().timestamp()*1000)
        return {k: v for k, v in job.items() if k != "proof"} | {"proof": None, "expired": now >= job["expires_ms"] or now < job["nonce"] - 1000,
            "wallet_signing_enabled": True, "submission_from_api": False,
            "note": "Explicit " + job["network"].upper() + " financial consent. Sign-in and offline local intent proofs cannot authorize this job. A separate armed runner submits queued permissions/orders. SDK permissions persist until revoked; the local queue deadline is not on-chain expiry."}

    @staticmethod
    def valid_profile(job, profile):
        if not profile or fingerprint({k: v for k, v in profile.items() if k != "last_nonce"}) != job["profile_hash"]:
            raise ValueError("The financial profile changed.")

    def verify(self, owner, job_id, signature):
        now = int(utcnow().timestamp()*1000)
        with self.store.transaction() as session:
            row, profile = session.get(FinancialJob, job_id), session.get(Profile, self.intents.key(owner))
            if not row or row.owner != self.intents.key(owner): raise ValueError("Unknown owner-bound financial job.")
            job = row.payload
            self.check_binding(job)
            if job["status"] != "unsigned":
                if job.get("proof_hash") == sha256(signature.encode()).hexdigest(): return job
                raise ValueError("Financial job already consumed.")
            if not job["nonce"] - 1000 <= now < job["expires_ms"]: raise ValueError("Financial queue consent expired or clock changed.")
            self.valid_profile(job, profile.payload if profile else None)
            if recover(job["typed_data"], signature) != owner: raise ValueError("The exact financial payload requires the owner wallet signature.")
            row.payload = job | {"status": "signed", "proof": signature, "proof_hash": sha256(signature.encode()).hexdigest()}
            return row.payload

    def claim_trade(self, owner, job_id, plan):
        with self.store.transaction() as session:
            row, profile = session.get(FinancialJob, job_id), session.get(Profile, self.intents.key(owner))
            if not row or row.owner != self.intents.key(owner) or row.payload["kind"] != "trade" or row.payload["status"] != "signed":
                raise ValueError("Unconsumed signed financial trade consent required.")
            job = row.payload
            self.check_binding(job)
            self.valid_profile(job, profile.payload if profile else None)
            self.validate_plan(owner, plan, profile.payload)
            expected = typed_intent(owner, profile.payload, plan, job["nonce"], job["expires_ms"], network=self.network)
            expected["domain"]["name"] = "Lobster Desk Execution Consent"
            now = int(utcnow().timestamp()*1000)
            if (not job["nonce"] - 1000 <= now < job["expires_ms"] or job["typed_data"] != expected
                    or plan["id"] != job["plan_id"] or recover(expected, job["proof"]) != owner):
                raise ValueError("Financial trade consent binding/expiry failed.")
            row.payload = job | {"status": "claimed", "claimed_at": utcnow().isoformat()}
            return row.payload

    async def submit_permission(self, owner, job_id, gateway, *, armed=False):
        if not armed or getattr(gateway, "network", "testnet") != self.network or gateway.account_address != owner:
            raise ValueError("Explicit matching-network permission runner required.")
        with self.store.transaction() as session:
            row, profile = session.get(FinancialJob, job_id), session.get(Profile, self.intents.key(owner))
            if not row or row.owner != self.intents.key(owner) or row.payload["kind"] == "trade": raise ValueError("Owner-bound permission job required.")
            job = row.payload
            self.check_binding(job)
            self.valid_profile(job, profile.payload if profile else None)
            if job["status"] != "signed": return job
            now = int(utcnow().timestamp()*1000)
            if not job["nonce"] - 1000 <= now < job["expires_ms"] or recover(job["typed_data"], job["proof"]) != owner:
                raise ValueError("Permission proof expired or changed.")
            # The SDK action has a strict schema, is immutable in this job, and was
            # signed by the main wallet. No private owner key is held by the runner.
            proof = bytes.fromhex(job["proof"][2:])
            envelope = {"action": job["action"], "nonce": job["nonce"], "signature": {
                "r": hex(int.from_bytes(proof[:32])), "s": hex(int.from_bytes(proof[32:64])), "v": proof[64]}}
            row.payload = job | {"status": "sending"}
        try:
            response = await gateway.client.post((TESTNET_URL if self.network == "testnet" else MAINNET_URL) + "/exchange", json=envelope, timeout=10, follow_redirects=False)
            response.raise_for_status()
            result = response.json()
            status = "acknowledged" if result.get("status") == "ok" else "rejected"
        except Exception: status = "unknown"
        with self.store.transaction() as session:
            row = session.get(FinancialJob, job_id)
            if row.payload["status"] == "sending": row.payload = row.payload | {"status": status}
        return await self.reconcile_permission(owner, job_id, gateway)

    async def reconcile_permission(self, owner, job_id, gateway):
        if getattr(gateway, "network", "testnet") != self.network or gateway.account_address != owner:
            raise ValueError("Permission observation network/account mismatch.")
        job = self.get(owner, job_id)
        if not job or job["kind"] == "trade" or job["status"] in {"unsigned", "signed", "rejected", "observed"}: return job
        profile = self.intents.profile(owner)
        if job["kind"] == "agent": matches = await gateway.agent_approved(profile["agent"])
        else:
            value = await gateway.info("maxBuilderFee", user=owner, builder=profile["builder"])
            if type(value) is not int or value < 0: raise ValueError("Unknown permission observation.")
            matches = value == 0 if job["kind"] == "revoke_builder" else value >= profile["fee_tenths_bps"]
        if matches:
            with self.store.transaction() as session:
                row = session.get(FinancialJob, job_id)
                # Matching current permissions cannot resolve an uncertain signed
                # command that might still arrive later. Preserve its uncertainty.
                row.payload = row.payload | {"status": "observed" if row.payload["status"] == "acknowledged" else row.payload["status"],
                    "permission_currently_matches": True, "observed_at": utcnow().isoformat(),
                    "observation_note": "Current permission matches; this does not prove which prior signed command caused it."}
        return self.get(owner, job_id)


class FinancialIntentAdapter:
    """Translate internal lifecycle names to the existing bounded broker hooks.

    Only FinancialJob rows with the explicit execution domain enter this adapter;
    local-rehearsal proofs never become execution authority.
    """
    def __init__(self, financial): self.financial = financial
    def profile(self, owner): return self.financial.intents.profile(owner)
    def get(self, owner, job_id):
        job = self.financial.get(owner, job_id)
        if not job or job["kind"] != "trade": return None
        return deepcopy(job) | {"address": owner, "status": {"signed": "verified_local", "claimed": "claimed_offline"}.get(job["status"], job["status"])}
    def claim_offline(self, owner, job_id, plan): return self.financial.claim_trade(owner, job_id, plan)
