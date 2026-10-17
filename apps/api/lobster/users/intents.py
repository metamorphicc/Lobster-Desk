"""Owner-bound local trade consent. This signature is NOT an exchange signature."""

from datetime import datetime
from decimal import Decimal as D
from hashlib import sha256
import secrets
from typing import Literal

from eth_account import Account
from eth_account.messages import encode_typed_data
from hyperliquid.utils.signing import user_signed_payload
from pydantic import Field, model_validator
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..domain import Contract, utcnow
from ..execution.contracts import fingerprint
from .auth import CURVE_N
from .contracts import Address


class ProfileInput(Contract):
    address: Address
    agent: Address
    builder: Address
    fee_tenths_bps: int = Field(default=50, ge=0, le=100, strict=True)
    network: Literal["testnet", "mainnet"] = "testnet"

    @model_validator(mode="after")
    def separate(self):
        if len({self.address, self.agent, self.builder}) != 3:
            raise ValueError("Use separate user, dedicated API wallet and builder addresses.")
        return self


class IntentInput(Contract):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "user_execution_profiles"
    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent: Mapped[str] = mapped_column(String(42), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Intent(Base):
    __tablename__ = "user_trade_intents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


def typed_intent(owner, profile, plan, nonce, expires, *, network="testnet"):
    if network not in {"testnet", "mainnet"}: raise ValueError("Unsupported consent network.")
    primary = "TestnetTradeIntent" if network == "testnet" else "MainnetTradeIntent"
    return {"domain": {"name": "Lobster Desk Local Intent", "version": "1", "chainId": 421614 if network == "testnet" else 42161,
        "verifyingContract": "0x" + "0" * 40}, "primaryType": primary,
        "types": {"EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
            primary: [{"name": "owner", "type": "address"}, {"name": "planHash", "type": "bytes32"},
                {"name": "agent", "type": "address"}, {"name": "builder", "type": "address"},
                {"name": "builderFeeTenthsBps", "type": "uint256"}, {"name": "nonce", "type": "uint64"},
                {"name": "validUntil", "type": "uint64"}]},
        "message": {"owner": owner, "planHash": "0x" + plan["plan_hash"], "agent": profile["agent"],
            "builder": profile["builder"], "builderFeeTenthsBps": profile["fee_tenths_bps"], "nonce": nonce, "validUntil": expires}}


def recover(typed, signature):
    try:
        raw = bytes.fromhex(signature.removeprefix("0x"))
        if len(raw) != 65 or raw[64] not in (27, 28) or not 0 < int.from_bytes(raw[32:64]) <= CURVE_N // 2:
            raise ValueError()
        return Account.recover_message(encode_typed_data(full_message=typed), signature=raw).lower()
    except Exception:
        raise ValueError("Invalid local intent signature.") from None


class UserIntents:
    def __init__(self, store, *, network="testnet"):
        if network not in {"testnet", "mainnet"}: raise ValueError("Unsupported profile network.")
        self.network = network
        self.store = store
        Base.metadata.create_all(store.engine)

    def key(self, owner): return owner if self.network == "testnet" else "mainnet:" + owner

    def configure(self, body: ProfileInput):
        if body.network != self.network: raise ValueError("Profile belongs to another network.")
        with self.store.transaction() as session:
            existing = session.get(Profile, self.key(body.address))
            if existing:
                if {key: existing.payload[key] for key in type(body).model_fields} != body.model_dump():
                    raise ValueError("Execution profiles are immutable. Cancel/reconcile old intents and migrate explicitly before replacing a profile.")
                return existing.payload
            for other in session.scalars(select(Profile)):
                registered = other.payload
                if (body.agent in {registered["address"], registered["agent"], registered["builder"]}
                        or body.address in {registered["agent"], registered["builder"]}
                        or body.builder in {registered["address"], registered["agent"]}):
                    raise ValueError("Each user requires a different API wallet, separated from every registered user and builder.")
            data = body.model_dump() | {"last_nonce": 0}
            session.add(Profile(address=self.key(body.address), agent=body.agent, payload=data))
            return data

    def profile(self, owner):
        with self.store.transaction() as session:
            row = session.get(Profile, self.key(owner))
            return row.payload if row else None

    def prepare(self, owner, plan):
        if self.network != "testnet": raise ValueError("Legacy local rehearsal is testnet-only.")
        immutable = {key: value for key, value in plan.items() if key not in {"plan_hash", "expired", "observation"}}
        if plan.get("network") != "testnet" or fingerprint(immutable) != plan.get("plan_hash"):
            raise ValueError("The immutable testnet preview binding is invalid.")
        now = int(utcnow().timestamp() * 1000)
        if plan["address"] != owner or now >= int(datetime.fromisoformat(plan["expires_at"]).timestamp() * 1000):
            raise ValueError("A fresh private preview for this owner is required.")
        with self.store.transaction() as session:
            profile = session.get(Profile, owner)
            if not profile:
                raise ValueError("The owner must configure a separate public API-wallet profile first.")
            config = profile.payload
            if plan["fees"]["builder_address"] != config["builder"] or plan["fees"]["builder_fee_tenths_bps"] != config["fee_tenths_bps"]:
                raise ValueError("The user preview and execution profile disagree about the builder fee.")
            nonce = max(now, config["last_nonce"] + 1)
            if nonce > now + 1000:
                raise ValueError("Local intent nonce is ahead of the signing clock.")
            expires = min(now + 30000, int(datetime.fromisoformat(plan["expires_at"]).timestamp() * 1000))
            intent = {"id": secrets.token_hex(16), "address": owner, "plan_id": plan["id"], "plan_hash": plan["plan_hash"],
                "episode_id": plan["episode_id"], "nonce": nonce, "expires_ms": expires, "profile_hash": fingerprint({key: value for key, value in config.items() if key != "last_nonce"}),
                "typed_data": typed_intent(owner, config, plan, nonce, expires), "status": "unsigned", "proof": None,
                "wallet_signing_enabled": False, "exchange_submission_enabled": False,
                "scope": "local-testnet-trade-intent", "note": "Not an exchange authorization. Actual delegation, builder approval and funded execution acceptance remain separate."}
            profile.payload = config | {"last_nonce": nonce}
            session.add(Intent(id=intent["id"], address=owner, payload=intent))
            return intent

    def get(self, owner, intent_id):
        if self.network != "testnet": raise ValueError("Legacy local rehearsal is testnet-only.")
        with self.store.transaction() as session:
            row = session.get(Intent, intent_id)
            return row.payload if row and row.address == owner else None

    @staticmethod
    def view(data):
        now = int(utcnow().timestamp()*1000)
        return data | {"proof": None, "expired": now >= data["expires_ms"] or now < data["nonce"] - 1000}

    def context(self, owner):
        if self.network != "testnet": raise ValueError("Legacy local rehearsal is testnet-only.")
        with self.store.transaction() as session:
            row = session.get(Profile, owner)
            recent = list(session.scalars(select(Intent).where(Intent.address == owner)
                .order_by(Intent.payload["nonce"].as_integer().desc()).limit(10)))
            profile = {key: value for key, value in row.payload.items() if key != "last_nonce"} if row else None
            views = [self.view(item.payload) for item in recent]
            return {"schema": "lobster-user-execution-context-v1", "address": owner, "network": "testnet", "profile": profile,
                "intents": [{key: item[key] for key in ("id", "plan_id", "plan_hash", "status", "expires_ms", "expired")} for item in views],
                "wallet_signing_enabled": False, "exchange_submission_enabled": False, "signatures_accepted": False,
                "note": "Private local consent journal. No trading permissions or signatures are accepted. API-wallet profiles require separate operator configuration."}

    def verify_local(self, owner, intent_id, signature):
        if self.network != "testnet": raise ValueError("Legacy local rehearsal is testnet-only.")
        """Core/offline verification only; no public financial-signature endpoint is enabled."""
        with self.store.transaction() as session:
            row = session.get(Intent, intent_id)
            if not row or row.address != owner or row.payload["status"] != "unsigned" or int(utcnow().timestamp()*1000) >= row.payload["expires_ms"]:
                raise ValueError("Local intent is expired, already consumed or belongs to another owner.")
            if recover(row.payload["typed_data"], signature) != owner:
                raise ValueError("The local intent must be signed by its user main wallet.")
            row.payload = row.payload | {"status": "verified_local", "proof": signature,
                "proof_hash": sha256(signature.encode()).hexdigest()}
            return row.payload

    def claim_offline(self, owner, intent_id, plan):
        if self.network != "testnet": raise ValueError("Legacy local rehearsal is testnet-only.")
        """One-time audit handoff for offline rehearsals. Never grants transport authority.

        A crash after this claim requires review; another claim cannot replay entry.
        """
        with self.store.transaction() as session:
            row, profile = session.get(Intent, intent_id), session.get(Profile, owner)
            if not row or row.address != owner or not profile or row.payload["status"] != "verified_local":
                raise ValueError("An unconsumed owner-bound local proof is required.")
            data = row.payload
            if int(utcnow().timestamp()*1000) >= data["expires_ms"]:
                raise ValueError("The local intent expired before handoff.")
            immutable = {key: value for key, value in plan.items() if key not in {"plan_hash", "expired", "observation"}}
            binding = fingerprint({key: value for key, value in profile.payload.items() if key != "last_nonce"})
            expected = typed_intent(owner, profile.payload, plan, data["nonce"], data["expires_ms"])
            if (plan["address"] != owner or plan["id"] != data["plan_id"] or plan["plan_hash"] != data["plan_hash"]
                    or fingerprint(immutable) != data["plan_hash"] or binding != data["profile_hash"]
                    or data["typed_data"] != expected or recover(expected, data["proof"]) != owner):
                raise ValueError("Intent, profile, preview or signature binding changed.")
            row.payload = data | {"status": "claimed_offline", "claimed_at": utcnow().isoformat()}
            return row.payload

    def approval_plans(self, owner):
        if self.network != "testnet": raise ValueError("Legacy local rehearsal is testnet-only.")
        """Unsigned SDK-compatible permissions, sharing a serialized main-wallet nonce sequence."""
        now = int(utcnow().timestamp()*1000)
        with self.store.transaction() as session:
            row = session.get(Profile, owner)
            if not row: raise ValueError("No user execution profile is configured.")
            profile = row.payload
            first = max(now, profile["last_nonce"] + 1)
            if first > now + 1000: raise ValueError("Permission nonce is ahead of the local clock.")
            row.payload = profile | {"last_nonce": first + 1}
            agent_action = {"type": "approveAgent", "hyperliquidChain": "Testnet", "signatureChainId": "0x66eee",
                "agentAddress": profile["agent"], "agentName": "Lobster Desk testnet", "nonce": first}
            builder_action = {"type": "approveBuilderFee", "hyperliquidChain": "Testnet", "signatureChainId": "0x66eee",
                "maxFeeRate": str(D(profile["fee_tenths_bps"]) / 1000) + "%", "builder": profile["builder"], "nonce": first + 1}
            return {"address": owner, "network": "testnet", "wallet_signing_enabled": False, "submitted": False,
                "agent": {"action": agent_action, "typed_data": user_signed_payload("HyperliquidTransaction:ApproveAgent", [
                    {"name": "hyperliquidChain", "type": "string"}, {"name": "agentAddress", "type": "address"},
                    {"name": "agentName", "type": "string"}, {"name": "nonce", "type": "uint64"}], agent_action)},
                "builder": {"action": builder_action, "typed_data": user_signed_payload("HyperliquidTransaction:ApproveBuilderFee", [
                    {"name": "hyperliquidChain", "type": "string"}, {"name": "maxFeeRate", "type": "string"},
                    {"name": "builder", "type": "address"}, {"name": "nonce", "type": "uint64"}], builder_action)}}
