"""Public key vectors and in-memory HTTP fixtures only; no charity payment made."""
import asyncio
from decimal import Decimal as D
import json

from eth_account import Account
from eth_utils import keccak
import httpx
from pydantic import SecretStr
import pytest
import rlp

from lobster.domain import utcnow
from lobster.economics.book import TreasuryBook, TreasuryEntry
from lobster.economics.charity import (CharitySettings, CharityPayments, GivingBlock, EthereumUsdc,
    RECIPIENTS, ETH_RPC, ETH_USDC, public_charity_report)
from lobster.economics.distribution import distribution

# PUBLIC test key. Never fund this vector.
KEY = "0x" + "1"*64
OWNER = Account.from_key(KEY).address
DESTINATION = "0x" + "2"*40


class Fixture:
    def __init__(self):
        self.sent, self.pledges, self.tx, self.record = [], [], None, None
        self.mine, self.timeout, self.pledge_timeout = True, False, False
        self.network, self.ein, self.forged = "ethereum", "060726487", False
        self.chain = "0x1"

    def request(self, request):
        if request.url.host == "public-api.tgbwidget.com": return self.provider(request)
        assert str(request.url) == ETH_RPC
        payload = json.loads(request.content)
        method, params = payload["method"], payload["params"]
        if method == "eth_chainId": value = self.chain
        elif method == "eth_call": value = hex(6) if params[0]["data"] == "0x313ce567" else hex(1000000000)
        elif method == "eth_getTransactionCount": value = "0x0"
        elif method == "eth_gasPrice": value = hex(1000000000)
        elif method == "eth_estimateGas":
            assert params[0]["to"] == ETH_USDC and params[0]["data"].startswith("0xa9059cbb") and params[0]["value"] == "0x0"
            value = hex(50000)
        elif method == "eth_getBalance": value = hex(10**18)
        elif method == "eth_sendRawTransaction":
            raw = bytes.fromhex(params[0][2:])
            assert Account.recover_transaction(raw) == OWNER
            decoded = rlp.decode(raw)
            assert int.from_bytes(decoded[6]) in (37, 38)  # EIP-155 chain 1.
            signature = "0x" + keccak(raw).hex()
            self.tx = {"hash": signature, "from": OWNER, "to": ETH_USDC, "nonce": hex(int.from_bytes(decoded[0])),
                "gasPrice": hex(int.from_bytes(decoded[1])), "gas": hex(int.from_bytes(decoded[2])), "input": "0x"+decoded[5].hex(), "value": "0x0"}
            self.sent.append(signature)
            self.record = {"txId": signature, "organizationId": 123, "currency": "USDC", "amount": "25",
                "method": "Crypto", "payoutAmount": "24.5", "payoutCurrency": "USD"}
            if self.timeout: raise httpx.ReadTimeout("public fixture")
            value = signature
        elif method == "eth_getTransactionReceipt":
            if not self.mine or not self.tx: value = None
            else:
                topic = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
                value = {"transactionHash": self.tx["hash"], "blockNumber": "0x10", "blockHash": "0x"+"a"*64,
                    "status": "0x1", "gasUsed": hex(45000), "logs": [{"address": ETH_USDC,
                    "topics": [topic, "0x"+OWNER[2:].lower().zfill(64), "0x"+DESTINATION[2:].zfill(64)],
                    "data": hex(26000000 if self.forged else 25000000)}]}
        elif method == "eth_getTransactionByHash": value = self.tx
        elif method == "eth_getBlockByNumber": value = {"number": "0x20", "hash": "0x"+"a"*64}
        else: raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})

    def provider(self, request):
        path = request.url.path
        if path == "/v1/login":
            assert json.loads(request.content) == {"login": "public-fixture", "password": "public-fixture"}
            value = {"accessToken": "public-fixture-token"}
        else:
            assert request.headers["authorization"] == "Bearer public-fixture-token"
            org = {"id": 123, "name": "Save the Children", "nonprofitTaxID": self.ein,
                "areCryptoDonationsEnabled": True, "allowsAnon": True}
            if path == "/v1/organizations/list": value = {"organizations": [org]}
            elif path == "/v1/organization/123": value = {"organization": org}
            elif path == "/v2/currencies/list":
                assert json.loads(request.content)["filters"]["organizationId"] == 123
                value = {"data": [{"code": "USDC", "network": self.network, "isErc20": True, "minDonation": "5"}]}
            elif path == "/v1/deposit-address":
                body = json.loads(request.content)
                assert body == {"organizationId": 123, "pledgeAmount": "25", "pledgeCurrency": "USDC", "isAnonymous": True}
                self.pledges.append(body)
                if self.pledge_timeout: raise httpx.ReadTimeout("public fixture pledge")
                value = {"depositAddress": DESTINATION, "pledgeId": "11111111-1111-4111-8111-111111111111"}
            elif path == "/v1/transaction/list": value = {"data": {"transactions": {"data": [self.record] if self.record else []}}}
            else: raise AssertionError(path)
        return httpx.Response(200, json={"data": value})


def settings(**changes):
    return CharitySettings(_env_file=None, enabled=True, owner=OWNER, private_key=SecretStr(KEY),
        tgb_login=SecretStr("public-fixture"), tgb_password=SecretStr("public-fixture"),
        operating_reserve="0", liability_reserve="0", tax_reserve="0", **changes)


def book(tmp_path):
    ledger = TreasuryBook(tmp_path / "treasury.db")
    ledger.append(TreasuryEntry(id="public-fixture-fees", receipt_ref="public-fixture-builder-fees", evidence_sha256="a"*64,
        kind="builder_receipt", amount="100", occurred_at=utcnow(), provenance="owner_supplied_unverified"))
    return ledger


def payments(ledger, client, *, armed=True):
    config = settings()
    return CharityPayments(ledger, config, GivingBlock(client, config.tgb_login, config.tgb_password), EthereumUsdc(client), armed=armed)


def test_directory_pledge_bounded_payment_finality_provider_receipt_and_restart(tmp_path):
    fixture, ledger = Fixture(), book(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.request)) as client:
            service = payments(ledger, client)
            row = await service.prepare("children", "25")
            assert fixture.sent == [] and len(fixture.pledges) == 1
            assert row["recipient"]["ein"] == RECIPIENTS["children"]["ein"]
            paid = await service.dispatch(row["id"])
            assert paid["status"] == "finalized" and paid["provider_status"] == "record_observed"
            assert paid["provider_net_amount"] == "24.5"
            restarted = payments(TreasuryBook(ledger.path), client)
            assert (await restarted.reconcile(row["id"]))["status"] == "finalized"
            assert (await restarted.dispatch(row["id"]))["status"] == "finalized"
            assert len(fixture.sent) == 1
            report = distribution(ledger)
            assert D(report["recorded_charity_paid"]) == 25 and D(report["outstanding_earmarks"]["charity"]) == 15
            public = json.dumps(public_charity_report(ledger))
            assert "raw_transaction" not in public and KEY not in public and "public-fixture-token" not in public
    asyncio.run(run())


def test_unknown_payment_is_never_signed_or_submitted_twice(tmp_path):
    fixture, ledger = Fixture(), book(tmp_path)
    fixture.timeout, fixture.mine = True, False
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.request)) as client:
            service = payments(ledger, client)
            row = await service.prepare("children", "25")
            assert (await service.dispatch(row["id"]))["status"] == "unknown"
            service = payments(TreasuryBook(ledger.path), client)
            assert (await service.dispatch(row["id"]))["status"] == "unknown"
            with pytest.raises(ValueError, match="previous"): await service.prepare("children", "25")
            fixture.mine = True
            assert (await service.reconcile(row["id"]))["status"] == "finalized"
            assert len(fixture.sent) == 1 and distribution(ledger)["record_count"] == 2
    asyncio.run(run())


@pytest.mark.parametrize("change", ["foreign_ein", "wrong_network", "missing_credentials", "earmark", "unarmed", "chain", "forged_log"])
def test_unknown_recipient_network_authority_or_money_cannot_mark_paid(tmp_path, change):
    fixture, ledger = Fixture(), book(tmp_path)
    if change == "foreign_ein": fixture.ein = "999999999"
    if change == "wrong_network": fixture.network = "solana"
    if change == "chain": fixture.chain = "0xaa36a7"
    if change == "forged_log": fixture.forged = True
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.request)) as client:
            service = payments(ledger, client, armed=change != "unarmed")
            if change == "missing_credentials": service.provider.login = None
            if change in {"foreign_ein", "wrong_network", "missing_credentials"}:
                with pytest.raises(ValueError): await service.prepare("children", "25")
                assert fixture.pledges == []
            elif change == "earmark":
                with pytest.raises(ValueError, match="earmark"): await service.prepare("children", "41")
            else:
                row = await service.prepare("children", "25")
                with pytest.raises(ValueError): await service.dispatch(row["id"])
            assert D(distribution(ledger)["recorded_charity_paid"]) == 0
            if change != "forged_log": assert fixture.sent == []
    asyncio.run(run())


def test_ambiguous_pledge_creation_cannot_be_automatically_recreated_or_paid(tmp_path):
    fixture, ledger = Fixture(), book(tmp_path)
    fixture.pledge_timeout = True
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.request)) as client:
            service = payments(ledger, client)
            with pytest.raises(ValueError, match="uncertain"): await service.prepare("children", "25")
            row = service.list()[0]
            assert row["status"] == "pledge_unknown"
            assert (await service.dispatch(row["id"]))["status"] == "pledge_unknown"
            with pytest.raises(ValueError, match="previous"): await service.prepare("children", "25")
            assert len(fixture.pledges) == 1 and fixture.sent == []
            assert service.cancel_unsent(row["id"])["status"] == "cancelled"
    asyncio.run(run())
