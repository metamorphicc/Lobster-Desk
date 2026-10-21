"""Separate opt-in treasury process; durable signed bytes are never rebuilt on retry."""
import base64
from decimal import Decimal as D
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.transaction import Transaction

from ..domain import utcnow
from ..execution.contracts import fingerprint
from .book import TreasuryEntry
from .distribution import DistributionPolicy, distribution_rows
from .solana import (GENESIS, USDC, TOKEN, SolanaRpc, JupiterQuotes, ata, pubkey, burn_checked,
    create_ata, serialize_instruction, deserialize_instruction, validate_route)


class SolanaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.treasury", env_prefix="SOLANA_", extra="ignore", hide_input_in_errors=True)
    network: Literal["mainnet"] = "mainnet"
    enabled: bool = False
    owner: str | None = None
    mint: str | None = None
    private_key: SecretStr | None = None
    jupiter_api_key: SecretStr | None = None
    book: Path = Path("data/treasury.sqlite3")
    operating_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    liability_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    tax_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_buyback_usdc: D = Field(default=D("25"), gt=0, le=100, allow_inf_nan=False)
    slippage_bps: int = Field(default=50, ge=1, le=100, strict=True)
    sol_reserve_lamports: int = Field(default=10000000, ge=1000000, strict=True)
    max_transaction_fee_lamports: int = Field(default=20000, ge=5000, le=100000, strict=True)

    @field_validator("owner", "mint", "private_key", "jupiter_api_key", "operating_reserve", "liability_reserve", "tax_reserve", mode="before")
    @classmethod
    def blank_unconfigured(cls, value):
        if value == "": return None
        if isinstance(value, (float, bool)): raise ValueError("Exact configuration values required.")
        return value

    @field_validator("slippage_bps", "sol_reserve_lamports", "max_transaction_fee_lamports", mode="before")
    @classmethod
    def exact_integer(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdigit(): return int(value)
        if type(value) is not int: raise ValueError("Canonical integer configuration required.")
        return value

    @model_validator(mode="after")
    def identities(self):
        for value in (self.owner, self.mint):
            if value is not None: pubkey(value)
        if self.mint == USDC: raise ValueError("The project token must differ from USDC.")
        return self

    def policy(self):
        values = {key: str(getattr(self, key)) if getattr(self, key) is not None else None
            for key in ("operating_reserve", "liability_reserve", "tax_reserve")}
        return DistributionPolicy(**values, token_contract=self.mint)

    def require_armed(self):
        if not self.enabled or any(value is None for value in (self.owner, self.mint, self.private_key, self.jupiter_api_key,
                self.operating_reserve, self.liability_reserve, self.tax_reserve)):
            raise ValueError("Explicit Solana enablement, wallet/mint/keys and all reserves are required.")


class SolanaOperations:
    def __init__(self, book, owner, mint):
        pubkey(owner); pubkey(mint)
        self.book, self.owner, self.mint = book, owner, mint
        identity = {"genesis": GENESIS, "owner": owner, "mint": mint, "usdc": USDC, "token_program": TOKEN}
        with book.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS solana_identity (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS solana_operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS solana_lots (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS solana_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
            previous = db.execute("SELECT payload FROM solana_identity WHERE id=1").fetchone()
            if previous and json.loads(previous[0]) != identity: raise ValueError("Solana book is bound to a different wallet/mint/network.")
            if not previous: db.execute("INSERT INTO solana_identity VALUES (1,?)", (json.dumps(identity),))

    @staticmethod
    def read(db, operation_id):
        row = db.execute("SELECT payload FROM solana_operations WHERE id=?", (operation_id,)).fetchone()
        if not row: raise ValueError("Unknown Solana operation.")
        row = json.loads(row[0])
        if fingerprint(row["plan"]) != row["id"]: raise ValueError("Solana immutable plan integrity failed.")
        return row

    @staticmethod
    def save(db, row, event):
        db.execute("INSERT OR REPLACE INTO solana_operations VALUES (?,?)", (row["id"], json.dumps(row)))
        db.execute("INSERT INTO solana_events (payload) VALUES (?)", (json.dumps({"operation_id": row["id"],
            "event": event, "at": utcnow().isoformat()}),))

    def get(self, operation_id):
        with self.book.transaction() as db: return self.read(db, operation_id)

    def list(self):
        with self.book.transaction() as db:
            return [self.read(db, row[0]) for row in db.execute("SELECT id FROM solana_operations ORDER BY rowid")]

    def lots(self):
        with self.book.transaction() as db: return [json.loads(row[0]) for row in db.execute("SELECT payload FROM solana_lots ORDER BY rowid")]

    def stage(self, plan, policy, cap):
        identity = fingerprint(plan)
        with self.book.transaction() as db:
            if db.execute("SELECT 1 FROM solana_operations WHERE id=?", (identity,)).fetchone(): return self.read(db, identity)
            active = [json.loads(r[0]) for r in db.execute("SELECT payload FROM solana_operations")]
            if any(row["status"] not in {"finalized", "failed", "cancelled"} for row in active):
                raise ValueError("Resolve the previous Solana operation before reserving another.")
            if plan["owner"] != self.owner or plan["mint"] != self.mint or plan["genesis"] != GENESIS:
                raise ValueError("Plan identity differs from the bound treasury.")
            if plan["kind"] == "buyback":
                report = distribution_rows(self.book.read(db), policy)
                budget = report["reserve_bounded_buyback_budget"]
                amount = D(plan["cost_usdc"])
                if report["receipt_chain_head"] != plan["receipt_head"] or budget is None or not 0 < amount <= min(D(budget), cap):
                    raise ValueError("Purchase exceeds fresh reserve-bounded profit entitlement.")
                if report["provenance"] != "owner_supplied_unverified": raise ValueError("Fixture cash cannot authorize a treasury transaction.")
            elif plan["kind"] == "burn":
                lot = db.execute("SELECT payload FROM solana_lots WHERE id=?", (plan["purchase_id"],)).fetchone()
                lot = json.loads(lot[0]) if lot else None
                if not lot or int(plan["quantity"]) != int(lot["quantity"]) - int(lot["burned"]):
                    raise ValueError("Burn must consume exactly the remaining verified purchased lot.")
            else: raise ValueError("Unsupported treasury operation.")
            row = {"id": identity, "plan": plan, "status": "prepared", "created_at": utcnow().isoformat()}
            self.save(db, row, "prepared")
            return row

    def cancel(self, operation_id):
        with self.book.transaction() as db:
            row = self.read(db, operation_id)
            if row["status"] != "prepared": raise ValueError("Only an unsigned unsent operation may be cancelled.")
            row["status"] = "cancelled"; self.save(db, row, "cancelled")
            return row


class SolanaTreasury:
    def __init__(self, book, settings, rpc, quotes=None, *, armed=False):
        if not settings.owner or not settings.mint: raise ValueError("Treasury wallet and project mint are required.")
        self.book, self.settings, self.rpc, self.quotes, self.armed = book, settings, rpc, quotes, armed
        self.operations = SolanaOperations(book, settings.owner, settings.mint)

    async def prepare_buyback(self, amount):
        if self.settings.policy().profit_buyback_share == "0":
            raise ValueError("New buybacks are disabled: own-agent profit now funds the donation reserve.")
        amount = D(amount)
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(D("0.000001")) or amount > self.settings.max_buyback_usdc:
            raise ValueError("Bounded exact USDC purchase amount required.")
        await self.rpc.mainnet()
        mint = await self.rpc.mint(self.settings.mint)
        usdc = await self.rpc.mint(USDC)
        if usdc["decimals"] != 6: raise ValueError("USDC decimals differ.")
        owner = self.settings.owner
        if await self.rpc.token_account(ata(owner, USDC), owner, USDC) < int(amount * 1000000):
            raise ValueError("Insufficient actual Solana USDC; Hyperliquid cash is not bridged automatically.")
        await self.rpc.token_account(ata(owner, self.settings.mint), owner, self.settings.mint, allow_missing=True)
        quote, ix = await self.quotes.purchase(owner, self.settings.mint, int(amount * 1000000), self.settings.slippage_bps)
        with self.book.transaction() as db: report = distribution_rows(self.book.read(db), self.settings.policy())
        plan = {"kind": "buyback", "owner": owner, "mint": self.settings.mint, "genesis": GENESIS,
            "cost_usdc": str(amount), "decimals": mint["decimals"], "quote": quote,
            "swap_instruction": serialize_instruction(ix), "receipt_head": report["receipt_chain_head"],
            "expires_ms": int(utcnow().timestamp()*1000) + 30000}
        return self.operations.stage(plan, self.settings.policy(), self.settings.max_buyback_usdc)

    async def prepare_burn(self, purchase_id):
        await self.rpc.mainnet()
        lot = next((lot for lot in self.operations.lots() if lot["id"] == purchase_id), None)
        if not lot: raise ValueError("A finalized purchase lot is required.")
        mint = await self.rpc.mint(self.settings.mint)
        remaining = int(lot["quantity"]) - int(lot["burned"])
        if mint["decimals"] != lot["decimals"] or remaining <= 0: raise ValueError("Purchased lot/mint changed or is already burned.")
        if await self.rpc.token_account(ata(self.settings.owner, self.settings.mint), self.settings.owner, self.settings.mint) < remaining:
            raise ValueError("Purchased tokens are missing from the bound treasury account.")
        plan = {"kind": "burn", "owner": self.settings.owner, "mint": self.settings.mint, "genesis": GENESIS,
            "purchase_id": purchase_id, "quantity": str(remaining), "decimals": lot["decimals"],
            "expires_ms": int(utcnow().timestamp()*1000) + 30000}
        return self.operations.stage(plan, self.settings.policy(), self.settings.max_buyback_usdc)

    def instructions(self, plan):
        owner, mint = self.settings.owner, self.settings.mint
        if (plan["owner"], plan["mint"], plan["genesis"]) != (owner, mint, GENESIS): raise ValueError("Wrong signing identity.")
        if plan["kind"] == "burn": return [burn_checked(owner, mint, int(plan["quantity"]), plan["decimals"])]
        if plan["kind"] != "buyback": raise ValueError("Unsupported signing operation.")
        quote = plan["quote"]
        ix = deserialize_instruction(plan["swap_instruction"])
        validate_route(ix, owner, mint, int(D(plan["cost_usdc"])*1000000), int(quote["outAmount"]), self.settings.slippage_bps)
        return [set_compute_unit_limit(1000000), set_compute_unit_price(0), create_ata(owner, mint), ix]

    async def dispatch(self, operation_id):
        self.settings.require_armed()
        if not self.armed: raise ValueError("Treasury process is not explicitly armed.")
        row = self.operations.get(operation_id)
        if row["status"] != "prepared": return await self.reconcile(operation_id)
        plan = row["plan"]
        if plan["kind"] == "buyback" and self.settings.policy().profit_buyback_share == "0":
            raise ValueError("Unsigned buybacks are disabled by the donation policy; cancel this plan. Existing signatures remain reconcilable.")
        if int(utcnow().timestamp()*1000) >= plan["expires_ms"]: raise ValueError("Unsigned treasury quote/plan expired; cancel and review a new plan.")
        await self.rpc.mainnet()
        key = Keypair.from_base58_string(self.settings.private_key.get_secret_value())
        if str(key.pubkey()) != self.settings.owner: raise ValueError("Solana treasury key/owner mismatch.")
        block = (await self.rpc.call("getLatestBlockhash", [{"commitment": "finalized"}]))["value"]
        tx = Transaction.new_signed_with_payer(self.instructions(plan), key.pubkey(), [key], Hash.from_string(block["blockhash"]))
        tx.verify()
        encoded = base64.b64encode(bytes(tx)).decode()
        if len(bytes(tx)) > 1232: raise ValueError("Route exceeds supported legacy packet size.")
        fee = (await self.rpc.call("getFeeForMessage", [base64.b64encode(tx.message_data()).decode(), {"commitment": "finalized"}]))["value"]
        balance = (await self.rpc.call("getBalance", [self.settings.owner, {"commitment": "finalized"}]))["value"]
        # Include enough headroom for one classic ATA rent, independently of RPC quote.
        if type(fee) is not int or fee > self.settings.max_transaction_fee_lamports or balance < self.settings.sol_reserve_lamports + fee + 3000000:
            raise ValueError("SOL fee/reserve bound not established.")
        simulation = (await self.rpc.call("simulateTransaction", [encoded, {"encoding": "base64", "sigVerify": True, "commitment": "finalized"}]))["value"]
        if simulation["err"] is not None: raise ValueError("Bounded treasury transaction failed simulation.")
        with self.book.transaction() as db:
            current = self.operations.read(db, operation_id)
            if current["status"] != "prepared": return current
            if int(utcnow().timestamp()*1000) >= plan["expires_ms"]: raise ValueError("Plan expired during preflight.")
            if plan["kind"] == "buyback":
                report = distribution_rows(self.book.read(db), self.settings.policy())
                if report["receipt_chain_head"] != plan["receipt_head"] or report["reserve_bounded_buyback_budget"] is None or D(report["reserve_bounded_buyback_budget"]) < D(plan["cost_usdc"]):
                    raise ValueError("Treasury entitlement changed after review; cancel and restage.")
            current.update(status="sending", transaction=encoded, signature=str(tx.signatures[0]),
                last_valid_block_height=block["lastValidBlockHeight"])
            self.operations.save(db, current, "signed_and_claimed")
        # Signed bytes and the claim are durable BEFORE the first network write.
        try:
            signature = await self.rpc.call("sendTransaction", [encoded, {"encoding": "base64", "skipPreflight": False,
                "preflightCommitment": "finalized", "maxRetries": 0}])
            if signature != current["signature"]: raise ValueError("RPC returned a different transaction identity.")
            status = "submitted"
        except Exception: status = "unknown"
        with self.book.transaction() as db:
            latest = self.operations.read(db, operation_id)
            if latest["status"] == "sending":
                latest["status"] = status; self.operations.save(db, latest, status)
        return await self.reconcile(operation_id)

    async def reconcile(self, operation_id):
        row = self.operations.get(operation_id)
        if row["status"] in {"prepared", "cancelled", "finalized", "failed"}: return row
        await self.rpc.mainnet()
        result = await self.rpc.call("getTransaction", [row["signature"], {"encoding": "base64", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
        if result is None: return row  # Uncertainty retains the reservation; no new signature/blockhash.
        if result["transaction"] != [row["transaction"], "base64"]: raise ValueError("Finalized transaction differs from the signed bytes.")
        tx = Transaction.from_bytes(base64.b64decode(row["transaction"], validate=True)); tx.verify()
        if str(tx.signatures[0]) != row["signature"]: raise ValueError("Finalized signature differs.")
        metadata, plan = result["meta"], row["plan"]
        if metadata["err"] is not None:
            with self.book.transaction() as db:
                current = self.operations.read(db, operation_id)
                if current["status"] != "finalized":
                    current.update(status="failed", finalized_slot=result["slot"], evidence_hash=fingerprint(result))
                    self.operations.save(db, current, "finalized_failure")
            return self.operations.get(operation_id)
        if type(metadata["fee"]) is not int or not 0 <= metadata["fee"] <= self.settings.max_transaction_fee_lamports:
            raise ValueError("Finalized network fee exceeds the reviewed bound.")
        changes = token_changes(metadata, tx, self.settings.owner)
        if plan["kind"] == "buyback":
            cost, output = int(D(plan["cost_usdc"])*1000000), int(plan["quote"]["otherAmountThreshold"])
            if changes.get(USDC) != -cost or changes.get(self.settings.mint, 0) < output or set(changes) - {USDC, self.settings.mint}:
                raise ValueError("Finalized purchase does not match the bounded USDC/token balance changes.")
        else:
            if changes != {self.settings.mint: -int(plan["quantity"])}:
                raise ValueError("Finalized BurnChecked does not match the purchased token lot.")
        evidence_hash = fingerprint(result)
        with self.book.transaction() as db:
            current = self.operations.read(db, operation_id)
            if current["status"] == "finalized": return current
            if plan["kind"] == "buyback":
                self.book.append_in_transaction(db, TreasuryEntry(id=operation_id, receipt_ref="solana-buyback:" + row["signature"],
                    kind="buyback_spend", amount=plan["cost_usdc"], evidence_sha256=evidence_hash,
                    occurred_at=utcnow(), provenance="owner_supplied_unverified"))
                lot = {"id": operation_id, "quantity": str(changes[self.settings.mint]), "burned": "0", "decimals": plan["decimals"],
                    "mint": self.settings.mint, "owner": self.settings.owner, "purchase_signature": row["signature"], "evidence_hash": evidence_hash}
                db.execute("INSERT INTO solana_lots VALUES (?,?)", (operation_id, json.dumps(lot)))
            else:
                lot = json.loads(db.execute("SELECT payload FROM solana_lots WHERE id=?", (plan["purchase_id"],)).fetchone()[0])
                if int(lot["quantity"]) - int(lot["burned"]) != int(plan["quantity"]): raise ValueError("Burn lot already consumed or changed.")
                lot.update(burned=lot["quantity"], burn_signature=row["signature"], burn_evidence_hash=evidence_hash)
                db.execute("UPDATE solana_lots SET payload=? WHERE id=?", (json.dumps(lot), plan["purchase_id"]))
            current.update(status="finalized", finalized_slot=result["slot"], evidence_hash=evidence_hash, finalized_at=utcnow().isoformat())
            self.operations.save(db, current, "finalized_success")
            return current


def token_changes(metadata, tx, owner):
    before, after = {}, {}
    for key, target in (("preTokenBalances", before), ("postTokenBalances", after)):
        for balance in metadata[key]:
            if balance.get("owner") != owner: continue
            mint, index = balance["mint"], balance["accountIndex"]
            if type(index) is not int or not 0 <= index < len(tx.message.account_keys) or str(tx.message.account_keys[index]) != ata(owner, mint):
                raise ValueError("Unexpected treasury token account in finalized evidence.")
            if balance.get("programId", TOKEN) != TOKEN or mint in target: raise ValueError("Unsupported/duplicate token balance evidence.")
            target[mint] = int(balance["uiTokenAmount"]["amount"])
    return {mint: after.get(mint, 0) - before.get(mint, 0) for mint in set(before) | set(after)
        if after.get(mint, 0) != before.get(mint, 0)}


def create_treasury(book, settings, client, *, armed=False):
    return SolanaTreasury(book, settings, SolanaRpc(client), JupiterQuotes(client, settings.jupiter_api_key), armed=armed)


def public_solana_report(book):
    """Read-only evidence summary; never loads .env.treasury or signed payloads."""
    with book.transaction() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='solana_identity'").fetchone():
            return {"configured": False, "network": "solana-mainnet", "operations": [], "lots": [], "signing_from_api": False}
        identity = json.loads(db.execute("SELECT payload FROM solana_identity WHERE id=1").fetchone()[0])
        operations = [SolanaOperations.read(db, r[0]) for r in db.execute("SELECT id FROM solana_operations ORDER BY rowid DESC LIMIT 50")]
        lots = [json.loads(r[0]) for r in db.execute("SELECT payload FROM solana_lots ORDER BY rowid DESC LIMIT 50")]
        return {"configured": True, "network": "solana-mainnet", "mint": identity["mint"], "owner": identity["owner"],
            "operations": [{"id": row["id"], "kind": row["plan"]["kind"], "status": row["status"],
                "signature": row.get("signature"), "finalized_slot": row.get("finalized_slot"),
                "evidence_hash": row.get("evidence_hash"), "cost_usdc": row["plan"].get("cost_usdc"),
                "quantity_atomic": row["plan"].get("quantity")} for row in operations],
            "lots": lots, "signing_from_api": False, "finality_source": "configured fixed-host RPC observations",
            "note": "Observed finalized signed transactions, not an independent consensus audit. Legacy owner-supplied receipt reports remain unverified. Signed bytes and keys are excluded."}
