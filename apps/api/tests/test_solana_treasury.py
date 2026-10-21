"""Public deterministic keys, mocked RPC/Jupiter; no network or actual transfers."""
import asyncio
import base64
from decimal import Decimal as D
import json
import struct

import httpx
from pydantic import SecretStr
import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction

from lobster.domain import utcnow
from lobster.economics.book import TreasuryBook, TreasuryEntry
from lobster.economics.distribution import distribution
from lobster.economics.solana import (TOKEN, USDC, JUPITER, GENESIS, RPC_URL, SolanaRpc, JupiterQuotes,
    ata, burn_checked, meta, pubkey, serialize_instruction, validate_route)
from lobster.economics.solana_treasury import SolanaSettings, SolanaTreasury, SolanaOperations
from solders.instruction import Instruction

# PUBLIC fixtures. These deterministic vectors must never hold real funds.
KEY = Keypair.from_seed(bytes(range(32)))
OWNER = str(KEY.pubkey())
MINT = str(Keypair.from_seed(bytes(range(1, 33))).pubkey())


def route(quantity=10000000, output=10000, slippage=50):
    data = bytes([229, 23, 203, 119, 221, 11, 109, 12]) + struct.pack("<I", 1) + bytes([46, 100, 0, 1]) + struct.pack("<QQHB", quantity, output, slippage, 0)
    addresses = [TOKEN, OWNER, ata(OWNER, USDC), ata(OWNER, MINT), JUPITER, MINT, JUPITER]
    return Instruction(pubkey(JUPITER), data, [meta(a, i == 1, i in (2, 3)) for i, a in enumerate(addresses)])


class Exchange:
    def __init__(self):
        self.sent, self.transactions, self.mine, self.timeout = [], {}, True, False
        self.genesis = GENESIS
        self.usdc, self.tokens = 100000000, 0
        self.bad_instruction = None
        self.bad_balance = False
        self.requests = []

    def request(self, request):
        self.requests.append((str(request.url), request.method))
        if request.url.host == "api.jup.ag": return self.jupiter(request)
        assert str(request.url) == RPC_URL
        args = json.loads(request.content)
        method, params = args["method"], args["params"]
        if method == "getGenesisHash": result = self.genesis
        elif method == "getAccountInfo": result = {"value": self.account(params[0])}
        elif method == "getLatestBlockhash": result = {"value": {"blockhash": str(Hash.default()), "lastValidBlockHeight": 100}}
        elif method == "getFeeForMessage": result = {"value": 5000}
        elif method == "getBalance": result = {"value": 100000000}
        elif method == "simulateTransaction":
            assert params[1]["sigVerify"] is True
            Transaction.from_bytes(base64.b64decode(params[0])).verify()
            result = {"value": {"err": None}}
        elif method == "sendTransaction":
            assert params[1]["maxRetries"] == 0 and params[1]["skipPreflight"] is False
            tx = Transaction.from_bytes(base64.b64decode(params[0])); tx.verify()
            signature = str(tx.signatures[0]); self.sent.append(signature)
            self.transactions[signature] = self.receipt(tx, params[0])
            if self.timeout: raise httpx.ReadTimeout("public fixture timeout")
            result = signature
        elif method == "getTransaction": result = self.transactions.get(params[0]) if self.mine else None
        else: raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    def account(self, address):
        if address in (USDC, MINT):
            return {"owner": TOKEN, "executable": False, "data": {"parsed": {"type": "mint", "info":
                {"isInitialized": True, "decimals": 6, "supply": "10000000000", "mintAuthority": None, "freezeAuthority": None}}}}
        mint, amount = (USDC, self.usdc) if address == ata(OWNER, USDC) else (MINT, self.tokens)
        return {"owner": TOKEN, "data": {"parsed": {"type": "account", "info": {"owner": OWNER, "mint": mint,
            "state": "initialized", "tokenAmount": {"amount": str(amount), "decimals": 6}}}}}

    def jupiter(self, request):
        assert request.headers["x-api-key"] == "public-fixture-not-a-key"
        if request.url.path.endswith("/quote"):
            quantity = int(request.url.params["amount"])
            return httpx.Response(200, json={"inputMint": USDC, "outputMint": MINT, "inAmount": str(quantity),
                "outAmount": "10000", "otherAmountThreshold": "9950", "swapMode": "ExactIn", "slippageBps": 50,
                "priceImpactPct": "0.001", "routePlan": [{"percent": 100, "swapInfo": {"inputMint": USDC, "outputMint": MINT}}]})
        body = json.loads(request.content)
        assert body["useSharedAccounts"] is False and body["wrapAndUnwrapSol"] is False
        ix = self.bad_instruction or route(quantity=int(body["quoteResponse"]["inAmount"]))
        return httpx.Response(200, json={"swapInstruction": serialize_instruction(ix), "setupInstructions": [],
            "computeBudgetInstructions": [], "addressLookupTableAddresses": []})

    def receipt(self, tx, encoded):
        keys = [str(k) for k in tx.message.account_keys]
        def balance(mint, amount):
            return {"accountIndex": keys.index(ata(OWNER, mint)), "owner": OWNER, "mint": mint, "programId": TOKEN,
                "uiTokenAmount": {"amount": str(amount), "decimals": 6}}
        is_burn = len(tx.message.instructions) == 1
        if is_burn:
            quantity = struct.unpack("<BQB", tx.message.instructions[0].data)[1]
            before = [balance(MINT, self.tokens)]
            self.tokens -= quantity
            after = [balance(MINT, self.tokens)]
        else:
            before = [balance(USDC, self.usdc), balance(MINT, self.tokens)]
            self.usdc -= 10000000 if not self.bad_balance else 11000000
            self.tokens += 10050
            after = [balance(USDC, self.usdc), balance(MINT, self.tokens)]
        return {"slot": 1234, "transaction": [encoded, "base64"], "meta": {"err": None, "fee": 5000,
            "preTokenBalances": before, "postTokenBalances": after}}


def book(tmp_path):
    result = TreasuryBook(tmp_path / "treasury.db")
    result.append(TreasuryEntry(id="public-fixture-profit", receipt_ref="public-fixture-settled-profit", evidence_sha256="a"*64,
        kind="trading_profit", amount="100", occurred_at=utcnow(), provenance="owner_supplied_unverified"))
    return result


class HistoricalSolanaSettings(SolanaSettings):
    """Offline old-policy recovery fixtures; production policy refuses new buys."""
    def policy(self):
        from lobster.economics.distribution import DistributionPolicy
        return DistributionPolicy.model_construct(**(super().policy().model_dump() | {
            "profit_buyback_share": "0.5", "profit_donation_share": "0"}))


def test_current_policy_refuses_new_buybacks_before_any_rpc_or_quote(tmp_path):
    exchange, ledger = Exchange(), book(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange.request)) as client:
            config = SolanaSettings(**settings().model_dump())
            worker = SolanaTreasury(ledger, config, SolanaRpc(client), armed=True)
            with pytest.raises(ValueError, match="donation reserve"):
                await worker.prepare_buyback("10")
            assert exchange.requests == [] and exchange.sent == []
    asyncio.run(run())


def settings(**changes):
    return HistoricalSolanaSettings(_env_file=None, enabled=True, owner=OWNER, mint=MINT, private_key=SecretStr(str(KEY)),
        jupiter_api_key=SecretStr("public-fixture-not-a-key"), operating_reserve="0", liability_reserve="0", tax_reserve="0", **changes)


async def treasury(client, ledger, **changes):
    config = settings(**changes)
    return SolanaTreasury(ledger, config, SolanaRpc(client), JupiterQuotes(client, config.jupiter_api_key), armed=True)


def test_purchase_then_actual_spl_burn_accounts_exact_received_tokens_and_restart(tmp_path):
    exchange, ledger = Exchange(), book(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange.request)) as client:
            first = await treasury(client, ledger)
            row = await first.prepare_buyback("10")
            assert exchange.sent == []
            bought = await first.dispatch(row["id"])
            assert bought["status"] == "finalized"
            assert first.operations.lots()[0]["quantity"] == "10050"
            assert D(distribution(ledger, settings().policy())["reserve_bounded_buyback_budget"]) == 40
            restarted = await treasury(client, TreasuryBook(ledger.path))
            assert (await restarted.dispatch(row["id"]))["status"] == "finalized" and len(exchange.sent) == 1
            burn = await restarted.prepare_burn(row["id"])
            assert (await restarted.dispatch(burn["id"]))["status"] == "finalized"
            assert restarted.operations.lots()[0]["burned"] == "10050" and exchange.tokens == 0
            with pytest.raises(ValueError, match="already burned"): await restarted.prepare_burn(row["id"])
            assert len(exchange.sent) == 2
    asyncio.run(run())


def test_timeout_reserves_budget_reconciles_existing_signature_and_never_resends(tmp_path):
    exchange, ledger = Exchange(), book(tmp_path)
    exchange.timeout, exchange.mine = True, False
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange.request)) as client:
            first = await treasury(client, ledger)
            plan = await first.prepare_buyback("10")
            assert (await first.dispatch(plan["id"]))["status"] == "unknown"
            restarted = await treasury(client, TreasuryBook(ledger.path))
            assert (await restarted.dispatch(plan["id"]))["status"] == "unknown"
            with pytest.raises(ValueError, match="previous"): await restarted.prepare_buyback("10")
            exchange.mine = True
            assert (await restarted.reconcile(plan["id"]))["status"] == "finalized"
            assert (await restarted.reconcile(plan["id"]))["status"] == "finalized"
            assert len(exchange.sent) == 1 and len(restarted.operations.lots()) == 1
            assert distribution(ledger)["record_count"] == 2
    asyncio.run(run())


@pytest.mark.parametrize("change", ["network", "amount", "account", "authority", "variant", "slippage"])
def test_foreign_or_widened_provider_instruction_cannot_be_signed(tmp_path, change):
    exchange, ledger = Exchange(), book(tmp_path)
    ix = route()
    if change == "network": exchange.genesis = "devnet"
    if change == "amount": ix = route(quantity=11000000)
    if change == "account": ix = Instruction(ix.program_id, ix.data, [meta(MINT)] + ix.accounts[1:])
    if change == "authority": ix = Instruction(ix.program_id, ix.data, ix.accounts + [meta(MINT, True)])
    if change == "variant": ix = Instruction(ix.program_id, ix.data[:12] + b"\xff" + ix.data[13:], ix.accounts)
    if change == "slippage": ix = route(slippage=100)
    exchange.bad_instruction = ix
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange.request)) as client:
            first = await treasury(client, ledger)
            with pytest.raises(ValueError): await first.prepare_buyback("10")
            assert exchange.sent == [] and first.operations.list() == []
    asyncio.run(run())


def test_changed_profit_entitlement_or_unarmed_process_refuses_before_submission(tmp_path):
    exchange, ledger = Exchange(), book(tmp_path)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange.request)) as client:
            first = await treasury(client, ledger)
            row = await first.prepare_buyback("10")
            first.armed = False
            with pytest.raises(ValueError, match="armed"): await first.dispatch(row["id"])
            first.armed = True
            ledger.append(TreasuryEntry(id="later-realized-loss", receipt_ref="public-fixture-later-loss", evidence_sha256="b"*64,
                kind="trading_loss", amount="90", occurred_at=utcnow(), provenance="owner_supplied_unverified"))
            with pytest.raises(ValueError, match="entitlement changed"): await first.dispatch(row["id"])
            assert exchange.sent == []
    asyncio.run(run())


def test_finalized_balance_mismatch_blocks_book_and_keeps_operation_reserved(tmp_path):
    exchange, ledger = Exchange(), book(tmp_path)
    exchange.bad_balance = True
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(exchange.request)) as client:
            first = await treasury(client, ledger)
            row = await first.prepare_buyback("10")
            with pytest.raises(ValueError, match="balance changes"): await first.dispatch(row["id"])
            assert first.operations.get(row["id"])["status"] == "submitted"
            assert first.operations.lots() == [] and distribution(ledger)["record_count"] == 1
    asyncio.run(run())


def test_treasury_identity_unknown_reserves_and_exact_amount_fail_closed(tmp_path):
    ledger = book(tmp_path)
    SolanaOperations(ledger, OWNER, MINT)
    with pytest.raises(ValueError, match="different"): SolanaOperations(ledger, MINT, OWNER)
    ix = burn_checked(OWNER, MINT, 123456, 6)
    assert str(ix.program_id) == TOKEN and ix.data == struct.pack("<BQB", 15, 123456, 6)
    assert str(ix.accounts[1].pubkey) == MINT and ix.accounts[1].is_writable
    with pytest.raises(ValueError): burn_checked(OWNER, MINT, -1, 6)
    assert distribution(ledger)["reserve_bounded_buyback_budget"] is None


def test_burn_checked_runs_in_real_spl_program_and_reduces_mint_supply():
    from solders.account import Account
    from solders.litesvm import LiteSVM
    from solders.transaction_metadata import TransactionMetadata
    vm = LiteSVM()
    vm.airdrop(KEY.pubkey(), 100000000)
    mint = bytearray(82)
    struct.pack_into("<QBB", mint, 36, 1000000, 6, 1)
    token = bytearray(165)
    token[:32], token[32:64] = bytes(pubkey(MINT)), bytes(KEY.pubkey())
    struct.pack_into("<Q", token, 64, 10000)
    token[108] = 1
    vm.set_account(pubkey(MINT), Account(10000000, bytes(mint), pubkey(TOKEN)))
    vm.set_account(pubkey(ata(OWNER, MINT)), Account(10000000, bytes(token), pubkey(TOKEN)))
    tx = Transaction.new_signed_with_payer([burn_checked(OWNER, MINT, 10000, 6)], KEY.pubkey(), [KEY], vm.latest_blockhash())
    result = vm.send_transaction(tx)
    assert isinstance(result, TransactionMetadata), str(result)
    assert struct.unpack_from("<Q", vm.get_account(pubkey(MINT)).data, 36)[0] == 990000
    assert struct.unpack_from("<Q", vm.get_account(pubkey(ata(OWNER, MINT))).data, 64)[0] == 0


def test_blank_example_and_env_integer_configuration_are_usable(monkeypatch):
    monkeypatch.setenv("SOLANA_SLIPPAGE_BPS", "50")
    monkeypatch.setenv("SOLANA_OWNER", "")
    monkeypatch.setenv("SOLANA_OPERATING_RESERVE", "")
    config = SolanaSettings(_env_file=None)
    assert config.owner is None and config.operating_reserve is None and config.slippage_bps == 50
    with pytest.raises(ValueError): config.require_armed()
