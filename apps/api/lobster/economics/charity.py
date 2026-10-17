"""The Giving Block directory/pledges and bounded Ethereum USDC charity payments."""
from decimal import Decimal as D
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

from eth_account import Account
from eth_utils import keccak, to_checksum_address
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain import utcnow
from ..execution.contracts import fingerprint
from .book import TreasuryEntry
from .distribution import distribution_rows

TGB = "https://public-api.tgbwidget.com"
ETH_RPC = "https://ethereum-rpc.publicnode.com"
ETH_USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
RECIPIENTS = {
    "children": {"name": "Save the Children", "ein": "060726487", "source": "https://www.savethechildren.org/us/ways-to-help/ways-to-give/donor-advised-funds"},
    "animals": {"name": "Best Friends Animal Society", "ein": "237147797", "source": "https://bestfriends.org/contact-us"},
}


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value) or int(value, 16) == 0:
        raise ValueError("Nonzero Ethereum address required.")
    return to_checksum_address(value)


def canonical(value):
    if isinstance(value, D): return str(value)
    if isinstance(value, dict): return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list): return [canonical(v) for v in value]
    return value


class CharitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.charity", env_prefix="CHARITY_", extra="ignore", hide_input_in_errors=True)
    enabled: bool = False
    owner: str | None = None
    private_key: SecretStr | None = None
    tgb_login: SecretStr | None = None
    tgb_password: SecretStr | None = None
    book: Path = Path("data/treasury.sqlite3")
    batch_usdc: D = Field(default=D("25"), ge=1, le=250, allow_inf_nan=False)
    operating_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    liability_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    tax_reserve: D | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_gas_price_wei: int = Field(default=20000000000, ge=1, le=100000000000)
    eth_reserve_wei: int = Field(default=1000000000000000, ge=0)

    @field_validator("owner", "private_key", "tgb_login", "tgb_password", "operating_reserve", "liability_reserve", "tax_reserve", mode="before")
    @classmethod
    def blank(cls, value):
        if value == "": return None
        if isinstance(value, (float, bool)): raise ValueError("Exact configuration required.")
        return value

    @field_validator("owner")
    @classmethod
    def owner_address(cls, value): return address(value) if value else None

    def require_armed(self):
        if not self.enabled or any(x is None for x in (self.owner, self.private_key, self.tgb_login, self.tgb_password,
                self.operating_reserve, self.liability_reserve, self.tax_reserve)):
            raise ValueError("Charity dispatch needs explicit enablement, dedicated wallet/provider credentials and reserves.")

    def policy(self):
        from .distribution import DistributionPolicy
        return DistributionPolicy(**{k: str(getattr(self, k)) if getattr(self, k) is not None else None
            for k in ("operating_reserve", "liability_reserve", "tax_reserve")})


class GivingBlock:
    def __init__(self, client, login, password):
        self.client, self.login, self.password = client, login, password
        self.access = None

    async def request(self, path, body=None):
        if path not in {"/v1/organizations/list", "/v2/currencies/list", "/v1/deposit-address", "/v1/transaction/list"} and not re.fullmatch(r"/v1/organization/[1-9][0-9]*", path):
            raise ValueError("Unsupported charity provider endpoint.")
        if self.access is None:
            if not self.login or not self.password: raise ValueError("The Giving Block partner API credentials are missing.")
            response = await self.client.post(TGB + "/v1/login", json={"login": self.login.get_secret_value(), "password": self.password.get_secret_value()}, timeout=15, follow_redirects=False)
            response.raise_for_status()
            self.access = response.json()["data"]["accessToken"]
        headers = {"Authorization": "Bearer " + self.access}
        if body is None:
            response = await self.client.get(TGB + path, headers=headers, timeout=15, follow_redirects=False)
        else:
            response = await self.client.post(TGB + path, headers=headers, json=body, timeout=15, follow_redirects=False)
        # No automatic mutation retry, including after an ambiguous timeout.
        if response.status_code == 401: self.access = None
        response.raise_for_status()
        return response.json(parse_float=D)["data"]

    async def recipient(self, key):
        expected = RECIPIENTS[key]
        rows = (await self.request("/v1/organizations/list"))["organizations"]
        matches = [row for row in rows if re.sub(r"\D", "", str(row.get("nonprofitTaxID", ""))) == expected["ein"]]
        if len(matches) != 1 or type(matches[0]["id"]) is not int: raise ValueError("Recipient EIN is missing or ambiguous in the live provider directory.")
        row = (await self.request("/v1/organization/" + str(matches[0]["id"])))["organization"]
        if (row["id"] != matches[0]["id"] or re.sub(r"\D", "", str(row.get("nonprofitTaxID", ""))) != expected["ein"]
                or row.get("areCryptoDonationsEnabled") is not True or row.get("allowsAnon") is not True):
            raise ValueError("Recipient identity/crypto/anonymous donation permission changed.")
        currencies = (await self.request("/v2/currencies/list", {"filters": {"organizationId": row["id"], "code": "USDC"},
            "pagination": {"page": 1, "itemsPerPage": 100}}))["data"]
        supported = [c for c in currencies if c["code"] == "USDC" and c["network"] == "ethereum" and c["isErc20"] is True]
        if len(supported) != 1: raise ValueError("Provider does not explicitly support USDC on Ethereum for this organization.")
        minimum = D(str(supported[0]["minDonation"]))
        if not minimum.is_finite() or minimum < 0: raise ValueError("Unknown provider minimum.")
        return {"key": key, "id": row["id"], "name": row["name"], "ein": expected["ein"], "min_donation": str(minimum),
            "directory_hash": fingerprint(canonical(row)), "currency_hash": fingerprint(canonical(supported[0]))}

    async def pledge(self, recipient, amount):
        result = await self.request("/v1/deposit-address", {"organizationId": recipient["id"], "pledgeAmount": str(amount),
            "pledgeCurrency": "USDC", "isAnonymous": True})
        destination = address(result["depositAddress"])
        if result.get("depositTag"): raise ValueError("Unexpected deposit tag for Ethereum USDC.")
        pledge = str(UUID(result["pledgeId"]))
        return {"pledge_id": pledge, "destination": destination, "provider_response_hash": fingerprint(canonical(result))}

    async def find_payment(self, signature, since):
        # Poll authenticated records. Unauthenticated/AES-only webhooks never
        # mark a donation completed. Their encryption is not an authenticity proof.
        for page in range(1, 11):
            data = await self.request("/v1/transaction/list", {"filters": {"date": {"from": since, "to": int(utcnow().timestamp()*1000)}},
                "pagination": {"page": page, "itemsPerPage": 100}})
            rows = data["data"]["transactions"]["data"]
            matches = [row for row in rows if str(row.get("txId", "")).lower() == signature.lower()]
            if len(matches) > 1: raise ValueError("Ambiguous provider transaction records.")
            if matches: return canonical(matches[0])
            if len(rows) < 100: return None
        raise ValueError("Provider payment lookup exceeds the bounded history window.")


class EthereumUsdc:
    def __init__(self, client): self.client = client

    async def call(self, method, params):
        if method not in {"eth_chainId", "eth_call", "eth_getTransactionCount", "eth_gasPrice", "eth_estimateGas", "eth_getBalance",
                "eth_sendRawTransaction", "eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_getBlockByNumber"}:
            raise ValueError("Unsupported Ethereum treasury method.")
        response = await self.client.post(ETH_RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15, follow_redirects=False)
        response.raise_for_status(); result = response.json()
        if result.get("error") or "result" not in result: raise ValueError("Ethereum RPC refused the request.")
        return result["result"]

    async def mainnet(self):
        if await self.call("eth_chainId", []) != "0x1": raise ValueError("Ethereum mainnet chain ID mismatch.")
        if int(await self.call("eth_call", [{"to": ETH_USDC, "data": "0x313ce567"}, "finalized"]), 16) != 6:
            raise ValueError("USDC contract decimals differ.")

    async def transaction(self, owner, destination, amount, settings):
        await self.mainnet()
        quantity = int(amount * 1000000)
        data = "0xa9059cbb" + destination[2:].lower().zfill(64) + f"{quantity:064x}"
        balance = int(await self.call("eth_call", [{"to": ETH_USDC, "data": "0x70a08231" + owner[2:].lower().zfill(64)}, "finalized"]), 16)
        if balance < quantity: raise ValueError("The dedicated Ethereum wallet lacks actual USDC; no automatic bridge is implied.")
        nonce = await self.call("eth_getTransactionCount", [owner, "pending"])
        if nonce != await self.call("eth_getTransactionCount", [owner, "latest"]): raise ValueError("An external pending wallet transaction needs reconciliation.")
        gas_price = int(await self.call("eth_gasPrice", []), 16)
        gas = int(await self.call("eth_estimateGas", [{"from": owner, "to": ETH_USDC, "data": data, "value": "0x0"}]), 16)
        gas = (gas * 120 + 99) // 100
        if not 0 < gas <= 120000 or not 0 < gas_price <= settings.max_gas_price_wei: raise ValueError("Ethereum gas exceeds the explicit ceiling.")
        native = int(await self.call("eth_getBalance", [owner, "finalized"]), 16)
        if native < gas * gas_price + settings.eth_reserve_wei: raise ValueError("Ethereum fee reserve is insufficient.")
        return {"chainId": 1, "nonce": int(nonce, 16), "gas": gas, "gasPrice": gas_price, "to": ETH_USDC, "value": 0, "data": data}


class CharityPayments:
    def __init__(self, book, settings, provider, rpc, *, armed=False):
        if not settings.owner: raise ValueError("Dedicated charity wallet required.")
        self.book, self.settings, self.provider, self.rpc, self.armed = book, settings, provider, rpc, armed
        with book.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS charity_identity (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS charity_payments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS charity_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
            identity = {"owner": settings.owner, "chain": 1, "token": ETH_USDC, "provider": TGB}
            old = db.execute("SELECT payload FROM charity_identity WHERE id=1").fetchone()
            if old and json.loads(old[0]) != identity: raise ValueError("Charity book belongs to a different wallet/network/provider.")
            if not old: db.execute("INSERT INTO charity_identity VALUES (1,?)", (json.dumps(identity),))

    @staticmethod
    def read(db, payment_id):
        row = db.execute("SELECT payload FROM charity_payments WHERE id=?", (payment_id,)).fetchone()
        if not row: raise ValueError("Unknown charity payment.")
        return json.loads(row[0])

    @staticmethod
    def save(db, row, event):
        db.execute("INSERT OR REPLACE INTO charity_payments VALUES (?,?)", (row["id"], json.dumps(row)))
        db.execute("INSERT INTO charity_events (payload) VALUES (?)", (json.dumps({"payment_id": row["id"], "event": event, "at": utcnow().isoformat()}),))

    def get(self, payment_id):
        with self.book.transaction() as db: return self.read(db, payment_id)

    def list(self):
        with self.book.transaction() as db: return [json.loads(row[0]) for row in db.execute("SELECT payload FROM charity_payments ORDER BY rowid")]

    def cancel_unsent(self, payment_id):
        with self.book.transaction() as db:
            row = self.read(db, payment_id)
            if row["status"] not in {"prepared", "creating_pledge", "pledge_unknown"} or row.get("signature"):
                raise ValueError("Only an unsigned unsent payment may be abandoned.")
            row["status"] = "cancelled"; self.save(db, row, "unsigned_payment_abandoned")
            return row

    def budget(self, db, amount):
        report = distribution_rows(self.book.read(db), self.settings.policy())
        if report["provenance"] != "owner_supplied_unverified" or report["blockers"]: raise ValueError("Reconciled receipts/reserves required.")
        due = D(report["outstanding_earmarks"]["charity"])
        reserves = sum((D(str(getattr(self.settings, k))) for k in ("operating_reserve", "liability_reserve", "tax_reserve")), D(0))
        free = D(report["recorded_cash"]) - reserves - D(report["outstanding_earmarks"]["team"])
        # Pending Solana buys have not debited the book yet.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='solana_operations'").fetchone():
            for row in db.execute("SELECT payload FROM solana_operations"):
                operation = json.loads(row[0])
                if operation["status"] not in {"finalized", "failed", "cancelled"} and operation["plan"]["kind"] == "buyback":
                    free -= D(operation["plan"]["cost_usdc"])
        if not 0 < amount <= min(due, free, self.settings.batch_usdc): raise ValueError("Payment exceeds unspent charity earmark/cash/batch cap.")
        return report

    async def prepare(self, recipient_key, amount):
        if recipient_key not in RECIPIENTS: raise ValueError("Recipient is outside the curated directory.")
        amount = D(amount)
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(D("0.000001")): raise ValueError("Exact positive USDC donation required.")
        recipient = await self.provider.recipient(recipient_key)
        if amount < D(recipient["min_donation"]): raise ValueError("Amount is below the live provider minimum; accumulate before paying.")
        with self.book.transaction() as db:
            if any(json.loads(r[0])["status"] not in {"finalized", "failed", "cancelled"} for r in db.execute("SELECT payload FROM charity_payments")):
                raise ValueError("Resolve the previous charity payment/pledge before creating another.")
            report = self.budget(db, amount)
            row = {"id": uuid4().hex, "status": "creating_pledge", "recipient": recipient, "amount": str(amount),
                "created_ms": int(utcnow().timestamp()*1000), "receipt_head": report["receipt_chain_head"], "owner": self.settings.owner}
            self.save(db, row, "pledge_claimed")
        try:
            pledge = await self.provider.pledge(recipient, amount)
            if pledge["destination"].lower() in {self.settings.owner.lower(), ETH_USDC.lower()}: raise ValueError("Invalid charity deposit destination.")
        except Exception:
            with self.book.transaction() as db:
                row = self.read(db, row["id"]); row["status"] = "pledge_unknown"; self.save(db, row, "pledge_unknown")
            raise ValueError("Provider pledge creation is uncertain. Inspect provider history; no automatic recreation or payment.") from None
        with self.book.transaction() as db:
            row = self.read(db, row["id"])
            if row["status"] != "creating_pledge": raise ValueError("The unsigned pledge was abandoned during provider creation.")
            row.update(pledge, status="prepared")
            row["binding_hash"] = fingerprint({k: row[k] for k in ("id", "recipient", "amount", "created_ms", "owner", "pledge_id", "destination")})
            self.save(db, row, "prepared")
            return row

    async def dispatch(self, payment_id):
        self.settings.require_armed()
        if not self.armed: raise ValueError("Charity process is not armed.")
        row = self.get(payment_id)
        if row["status"] != "prepared": return await self.reconcile(payment_id)
        expected = fingerprint({k: row[k] for k in ("id", "recipient", "amount", "created_ms", "owner", "pledge_id", "destination")})
        if row["binding_hash"] != expected: raise ValueError("Charity payment binding integrity failed.")
        current_recipient = await self.provider.recipient(row["recipient"]["key"])
        if current_recipient["id"] != row["recipient"]["id"] or current_recipient["ein"] != row["recipient"]["ein"]:
            raise ValueError("Provider recipient identity changed after pledge creation.")
        if D(row["amount"]) < D(current_recipient["min_donation"]): raise ValueError("Provider minimum changed.")
        key = Account.from_key(self.settings.private_key.get_secret_value())
        if key.address != self.settings.owner: raise ValueError("Dedicated charity wallet key differs.")
        tx = await self.rpc.transaction(self.settings.owner, row["destination"], D(row["amount"]), self.settings)
        signed = key.sign_transaction(tx)
        raw, signature = "0x" + signed.raw_transaction.hex(), "0x" + signed.hash.hex()
        if Account.recover_transaction(raw) != key.address: raise ValueError("Charity signature verification failed.")
        with self.book.transaction() as db:
            current = self.read(db, payment_id)
            if current["status"] != "prepared": return current
            self.budget(db, D(row["amount"]))
            # Exact pledge identity and current earmark are revalidated before claim.
            current.update(status="sending", transaction=tx, raw_transaction=raw, signature=signature)
            self.save(db, current, "signed_and_claimed")
        try:
            observed = await self.rpc.call("eth_sendRawTransaction", [raw])
            if observed.lower() != signature.lower(): raise ValueError("Unexpected charity transaction identity.")
            status = "submitted"
        except Exception: status = "unknown"
        with self.book.transaction() as db:
            current = self.read(db, payment_id)
            if current["status"] == "sending": current["status"] = status; self.save(db, current, status)
        return await self.reconcile(payment_id)

    async def reconcile(self, payment_id):
        row = self.get(payment_id)
        if row["status"] in {"prepared", "creating_pledge", "pledge_unknown", "cancelled", "failed"}: return row
        if row["status"] != "finalized":
            await self.rpc.mainnet()
            receipt = await self.rpc.call("eth_getTransactionReceipt", [row["signature"]])
            finalized = await self.rpc.call("eth_getBlockByNumber", ["finalized", False])
            if not receipt or not finalized or int(receipt["blockNumber"], 16) > int(finalized["number"], 16): return row
            block = await self.rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
            if not block or block["hash"].lower() != receipt["blockHash"].lower(): raise ValueError("Charity receipt is not in the observed finalized chain.")
            if receipt["transactionHash"].lower() != row["signature"].lower(): raise ValueError("Charity receipt transaction mismatch.")
            if int(receipt["status"], 16) != 1:
                with self.book.transaction() as db:
                    current = self.read(db, payment_id); current["status"] = "failed"; self.save(db, current, "finalized_failure")
                return self.get(payment_id)
            observed = await self.rpc.call("eth_getTransactionByHash", [row["signature"]])
            if (not observed or observed["from"].lower() != self.settings.owner.lower() or observed["to"].lower() != ETH_USDC.lower()
                    or observed["input"].lower() != row["transaction"]["data"].lower() or int(observed["value"], 16) != 0
                    or int(observed["nonce"], 16) != row["transaction"]["nonce"]
                    or int(observed["gas"], 16) != row["transaction"]["gas"]
                    or int(observed["gasPrice"], 16) != row["transaction"]["gasPrice"]
                    or int(receipt["gasUsed"], 16) > row["transaction"]["gas"]):
                raise ValueError("Finalized charity transaction differs from exact signed transfer.")
            topic = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
            source = "0x" + self.settings.owner[2:].lower().zfill(64)
            destination = "0x" + row["destination"][2:].lower().zfill(64)
            transfers = [log for log in receipt["logs"] if log["address"].lower() == ETH_USDC.lower()
                and [t.lower() for t in log["topics"]] == [topic, source, destination]]
            if len(transfers) != 1 or int(transfers[0]["data"], 16) != int(D(row["amount"])*1000000):
                raise ValueError("Finalized USDC transfer log does not match the charity pledge.")
            evidence = fingerprint({"receipt": receipt, "transaction": observed, "finalized_block_hash": finalized["hash"]})
            with self.book.transaction() as db:
                current = self.read(db, payment_id)
                if current["status"] != "finalized":
                    self.book.append_in_transaction(db, TreasuryEntry(id=payment_id, receipt_ref="ethereum-charity:" + row["signature"],
                        evidence_sha256=evidence, kind="charity_payout", amount=row["amount"], occurred_at=utcnow(), provenance="owner_supplied_unverified"))
                    current.update(status="finalized", chain_evidence_hash=evidence, finalized_at=utcnow().isoformat(),
                        provider_status="awaiting_provider_record")
                    self.save(db, current, "finalized_usdc_transfer")
            row = self.get(payment_id)
        if row.get("provider_status") != "record_observed":
            record = await self.provider.find_payment(row["signature"], row["created_ms"])
            if record:
                if (record["organizationId"] != row["recipient"]["id"] or record["currency"] != "USDC"
                        or D(str(record["amount"])) != D(row["amount"]) or record.get("method") != "Crypto"):
                    raise ValueError("Authenticated provider record differs from finalized pledge payment.")
                with self.book.transaction() as db:
                    current = self.read(db, payment_id)
                    current.update(provider_status="record_observed", provider_evidence_hash=fingerprint(record),
                        provider_net_amount=record.get("payoutAmount"), provider_net_currency=record.get("payoutCurrency"))
                    self.save(db, current, "provider_record_observed")
        return self.get(payment_id)


def public_charity_report(book):
    with book.transaction() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='charity_payments'").fetchone()
        rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM charity_payments ORDER BY rowid DESC LIMIT 50")] if exists else []
        keys = ("id", "status", "amount", "signature", "provider_status", "provider_net_amount", "provider_net_currency", "chain_evidence_hash", "provider_evidence_hash")
        return {"provider": "The Giving Block", "network": "ethereum", "currency": "USDC (ERC-20)",
            "recipients": RECIPIENTS, "payments": [{**{key: row.get(key) for key in keys}, "recipient": row["recipient"]["key"]} for row in rows],
            "configured": bool(exists), "signing_from_api": False,
            "note": "Gross USDC transfers to provider-assigned addresses are separate from provider acknowledgment and net nonprofit proceeds. No signed bytes or provider credentials are public."}
