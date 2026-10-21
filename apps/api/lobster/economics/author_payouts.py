"""Opt-in bounded Hyperliquid author payouts; unknown sends are never replayed."""
from decimal import Decimal as D
from datetime import datetime
import json
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_typed_data
from hyperliquid.utils.signing import USD_SEND_SIGN_TYPES, user_signed_payload
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain import utcnow
from ..execution.contracts import fingerprint, MAINNET_URL
from ..execution.gateway import HyperliquidMainnet
from ..ops.catalog import JournalLocation
from ..users.contracts import Address, UserMainnetSettings
from ..users.fees import require_fresh
from ..users.service import UserTestnetService
from ..users.strategy_http import record_payout, PayoutReceipt
from .distribution import DistributionPolicy, distribution_rows, usdc
from .sharing import author_balances

TERMINAL = {"recorded", "rejected", "cancelled"}


class AuthorPayoutSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.author-payouts", env_prefix="AUTHOR_PAYOUT_", extra="ignore", hide_input_in_errors=True)
    enabled: bool = False
    account: Address | None = None
    private_key: SecretStr | None = None
    book: Path = Path("data/treasury.sqlite3")
    batch_usdc: D = Field(default=D("25"), gt=0, le=100, decimal_places=6, allow_inf_nan=False)
    operating_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    liability_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    tax_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)

    def require_armed(self):
        if not self.enabled or any(getattr(self, key) is None for key in ("account", "private_key", "operating_reserve", "liability_reserve", "tax_reserve")):
            raise ValueError("Author payouts require explicit enablement, project source key and reserves.")
        if Account.from_key(self.private_key.get_secret_value()).address.lower() != self.account:
            raise ValueError("Only the dedicated project account key can sign its USDC transfers; an API trading key cannot be substituted.")


class AuthorPayouts:
    def __init__(self, store, book, settings, client, *, armed=False):
        if not armed: raise ValueError("Author payout writer must be explicitly armed.")
        settings.require_armed()
        if settings.book.resolve() != book.path: raise ValueError("Payout treasury book mismatch.")
        self.store, self.book, self.settings, self.client = store, book, settings, client
        self.gateway = HyperliquidMainnet(client, settings.account)
        self.service = UserTestnetService(UserMainnetSettings(_env_file=None), client, network="mainnet")
        with Session(store.engine) as db:
            matches = [row.payload for row in db.scalars(select(JournalLocation)) if row.payload["role"] == "project"
                and row.payload["account"] == settings.account and row.payload["network"] == "mainnet"]
        if len(matches) != 1: raise ValueError("Exactly one registered mainnet project source is required.")
        self.journal = matches[0]
        if fingerprint({k: self.journal[k] for k in ("network", "account", "signer", "path", "role")}) != self.journal["id"]:
            raise ValueError("Registered payout source binding changed.")
        binding = {"network": "mainnet", "account": settings.account, "journal_id": self.journal["id"]}
        with book.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS author_payout_control (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS author_payout_jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            old = db.execute("SELECT payload FROM author_payout_control WHERE id=1").fetchone()
            if old and json.loads(old[0])["binding"] != binding: raise ValueError("Payout source is immutable; reconcile before migration.")
            if not old: db.execute("INSERT INTO author_payout_control VALUES (1,?)", (json.dumps({"binding": binding, "last_nonce": 0}),))

    def jobs(self):
        with self.book.transaction() as db: return [json.loads(r[0]) for r in db.execute("SELECT payload FROM author_payout_jobs ORDER BY rowid")]

    @staticmethod
    def save(db, job): db.execute("INSERT OR REPLACE INTO author_payout_jobs VALUES (?,?)", (job["id"], json.dumps(job)))

    def limits(self, rows, owner):
        report = distribution_rows(rows, DistributionPolicy())
        balance = author_balances(rows).get(owner)
        due = D(balance["outstanding"]) if balance else D(0)
        reserves = self.settings.operating_reserve+self.settings.liability_reserve+self.settings.tax_reserve
        # Protect every other author and the team while allowing this author's
        # own earmark to be paid. Never spend deposits as a new entitlement.
        free = max(D(0), D(report["recorded_cash"])-D(report["outstanding_earmarks"]["team"])
            -(D(report["outstanding_earmarks"]["strategy_authors"])-due)-D(report["outstanding_earmarks"]["donations"])-reserves)
        return min(due, free, self.settings.batch_usdc)

    async def flat(self):
        if await self.gateway.info("userAbstraction", user=self.settings.account) != "disabled":
            raise ValueError("Payouts support explicitly observed standard accounts only.")
        state = await self.service.inspect(self.settings.account)
        require_fresh(state, self.settings.account, network="mainnet")
        stamp = state.get("exchange_time_ms")
        if type(stamp) is not int or not -2000 <= int(utcnow().timestamp()*1000)-stamp <= 15000 or state["positions"] or state["open_orders"]:
            raise ValueError("Fresh flat project observations are required before a payout.")
        with self.book.transaction() as db:
            if any(row["entry"]["kind"] in {"author_payout", "team_payout"}
                    and int(datetime.fromisoformat(row["entry"]["occurred_at"]).timestamp()*1000) > stamp for row in self.book.read(db)):
                raise ValueError("Project observations predate a recorded payout.")
        return state

    async def prepare(self):
        state = await self.flat()
        with self.book.transaction() as db:
            if any(json.loads(r[0])["status"] not in TERMINAL for r in db.execute("SELECT payload FROM author_payout_jobs")):
                raise ValueError("Resolve the previous payout before preparing another.")
            rows = self.book.read(db)
            reserves = self.settings.operating_reserve+self.settings.liability_reserve+self.settings.tax_reserve
            candidates = [(owner, usdc(min(self.limits(rows, owner), max(D(0), D(state["withdrawable"])-reserves))))
                for owner in sorted(author_balances(rows)) if owner != self.settings.account]
            choice = next(((owner, amount) for owner, amount in candidates if amount >= D("0.01")), None)
            if not choice: return None
            owner, amount = choice
            now = int(utcnow().timestamp()*1000)
            control = json.loads(db.execute("SELECT payload FROM author_payout_control WHERE id=1").fetchone()[0])
            nonce = max(now, control["last_nonce"]+1)
            if nonce > now+1000: raise ValueError("Payout nonce is ahead of the clock.")
            action = {"type": "usdSend", "hyperliquidChain": "Mainnet", "signatureChainId": "0xa4b1",
                "destination": owner, "amount": format(amount, "f"), "time": nonce}
            plan = {"account": self.settings.account, "journal_id": self.journal["id"], "action": action,
                "nonce": nonce, "expires_ms": now+30000}
            job = {"id": fingerprint(plan), "plan": plan, "status": "prepared", "envelope": None}
            self.save(db, job)
            control["last_nonce"] = nonce
            db.execute("UPDATE author_payout_control SET payload=? WHERE id=1", (json.dumps(control),))
            return job

    async def dispatch(self, job_id):
        self.settings.require_armed()
        job = next((j for j in self.jobs() if j["id"] == job_id), None)
        if not job: raise ValueError("Unknown author payout job.")
        if job["status"] != "prepared": return await self.reconcile(job_id)
        state = await self.flat()
        with self.book.transaction() as db:
            job = json.loads(db.execute("SELECT payload FROM author_payout_jobs WHERE id=?", (job_id,)).fetchone()[0])
            if job["status"] != "prepared": return job
            plan, now = job["plan"], int(utcnow().timestamp()*1000)
            if fingerprint(plan) != job_id: raise ValueError("Payout immutable plan integrity failed.")
            if not plan["nonce"]-1000 <= now < plan["expires_ms"]:
                job["status"] = "cancelled"; self.save(db, job); return job
            action = plan["action"]
            expected = {"type": "usdSend", "hyperliquidChain": "Mainnet", "signatureChainId": "0xa4b1",
                "destination": action["destination"], "amount": action["amount"], "time": plan["nonce"]}
            if (action != expected or plan["account"] != self.settings.account or plan["journal_id"] != self.journal["id"]
                    or action["destination"] == self.settings.account or not D("0.01") <= D(action["amount"]) <= self.limits(self.book.read(db), action["destination"])):
                raise ValueError("Payout exceeds the exact current verified-author entitlement.")
            reserves = self.settings.operating_reserve+self.settings.liability_reserve+self.settings.tax_reserve
            if D(action["amount"]) > D(state["withdrawable"])-reserves: raise ValueError("Insufficient unreserved project funds.")
            typed = user_signed_payload("HyperliquidTransaction:UsdSend", USD_SEND_SIGN_TYPES, action)
            wallet = Account.from_key(self.settings.private_key.get_secret_value())
            signed = wallet.sign_message(encode_typed_data(full_message=typed))
            envelope = {"action": action, "nonce": plan["nonce"], "signature": {"r": hex(signed.r), "s": hex(signed.s), "v": signed.v}}
            # Durable claim and exact signed body precede HTTP. A timeout or
            # crash cannot produce a second transfer/nonce for this job.
            job.update(status="sending", envelope=envelope); self.save(db, job)
        try:
            response = await self.client.post(MAINNET_URL+"/exchange", json=envelope, timeout=10, follow_redirects=False)
            response.raise_for_status()
            result = response.json()
            status = "acknowledged" if result.get("status") == "ok" and result.get("response", {}).get("type") == "default" else "rejected" if result.get("status") == "err" else "unknown"
        except Exception: status = "unknown"
        with self.book.transaction() as db:
            job["status"] = status; self.save(db, job)
        return await self.reconcile(job_id)

    async def reconcile(self, job_id):
        job = next(j for j in self.jobs() if j["id"] == job_id)
        if fingerprint(job["plan"]) != job_id: raise ValueError("Payout immutable plan integrity failed.")
        # Matching balance/history cannot prove which uncertain signed transfer
        # caused it. Preserve uncertainty; do not replay or auto-clear it.
        if job["status"] != "acknowledged": return job
        plan, end = job["plan"], int(utcnow().timestamp()*1000)
        if end-plan["nonce"] > 7*86400000 or end < plan["nonce"]: raise ValueError("Payout history needs manual reconciliation.")
        rows = await self.service.capital_history(self.settings.account, plan["nonce"], end)
        candidates = [r for r in rows if r["kind"] == "internalTransfer" and D(r["cashflow"]) == -D(plan["action"]["amount"])]
        if len(candidates) != 1: return job
        receipt = candidates[0]
        body = PayoutReceipt(journal_id=self.journal["id"], owner=plan["action"]["destination"], transfer_hash=receipt["hash"],
            timestamp_ms=receipt["time"], amount=plan["action"]["amount"])
        await record_payout(self.store, self.book, self.service, body, operation_id=job_id)
        with self.book.transaction() as db:
            job.update(status="recorded", transfer_hash=receipt["hash"]); self.save(db, job)
        return job
