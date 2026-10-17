"""Bounded Solana instructions and fixed mainnet RPC. No import-time networking."""
import base64
from decimal import Decimal as D
import struct

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM = "11111111111111111111111111111111"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
RPC_URL = "https://api.mainnet-beta.solana.com"


def pubkey(value):
    if not isinstance(value, str) or str(Pubkey.from_string(value)) != value: raise ValueError("Canonical Solana public key required.")
    return Pubkey.from_string(value)


def ata(owner, mint):
    return str(Pubkey.find_program_address([bytes(pubkey(owner)), bytes(pubkey(TOKEN)), bytes(pubkey(mint))], pubkey(ASSOCIATED))[0])


def meta(address, signer=False, writable=False): return AccountMeta(pubkey(address), signer, writable)


def create_ata(owner, mint):
    return Instruction(pubkey(ASSOCIATED), b"\x01", [meta(owner, True, True), meta(ata(owner, mint), writable=True),
        meta(owner), meta(mint), meta(SYSTEM), meta(TOKEN)])


def burn_checked(owner, mint, quantity, decimals):
    if type(quantity) is not int or not 0 < quantity < 2**64 or type(decimals) is not int or not 0 <= decimals <= 18:
        raise ValueError("Bounded exact atomic burn required.")
    return Instruction(pubkey(TOKEN), struct.pack("<BQB", 15, quantity, decimals),
        [meta(ata(owner, mint), writable=True), meta(mint, writable=True), meta(owner, True)])


def transfer_checked(owner, destination, quantity):
    if type(quantity) is not int or not 0 < quantity < 2**64: raise ValueError("Exact USDC transfer required.")
    return Instruction(pubkey(TOKEN), struct.pack("<BQB", 12, quantity, 6),
        [meta(ata(owner, USDC), writable=True), meta(USDC), meta(destination, writable=True), meta(owner, True)])


def serialize_instruction(ix):
    return {"programId": str(ix.program_id), "data": base64.b64encode(ix.data).decode(),
        "accounts": [{"pubkey": str(a.pubkey), "isSigner": a.is_signer, "isWritable": a.is_writable} for a in ix.accounts]}


def deserialize_instruction(value):
    return Instruction(pubkey(value["programId"]), base64.b64decode(value["data"], validate=True),
        [meta(a["pubkey"], a["isSigner"], a["isWritable"]) for a in value["accounts"]])


class SolanaRpc:
    def __init__(self, client): self.client = client

    async def call(self, method, params=None):
        if method not in {"getGenesisHash", "getAccountInfo", "getBalance", "getLatestBlockhash", "getTransaction",
                "simulateTransaction", "getFeeForMessage", "getSignatureStatuses", "sendTransaction"}:
            raise ValueError("Unsupported Solana RPC method.")
        response = await self.client.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []},
            timeout=15, follow_redirects=False)
        response.raise_for_status()
        result = response.json(parse_float=D)
        if result.get("error") or "result" not in result: raise ValueError("Solana RPC refused the bounded request.")
        return result["result"]

    async def mainnet(self):
        if await self.call("getGenesisHash") != GENESIS: raise ValueError("Solana mainnet genesis mismatch.")

    async def account(self, address):
        pubkey(address)
        return (await self.call("getAccountInfo", [address, {"encoding": "jsonParsed", "commitment": "finalized"}]))["value"]

    async def mint(self, address):
        value = await self.account(address)
        if not value or value["owner"] != TOKEN or value.get("executable") or value["data"]["parsed"]["type"] != "mint":
            raise ValueError("Only the classic SPL Token program is supported; extensions/native SOL are refused.")
        info = value["data"]["parsed"]["info"]
        if info["isInitialized"] is not True or type(info["decimals"]) is not int or not 0 <= info["decimals"] <= 18:
            raise ValueError("Uninitialized/unsupported mint.")
        return info

    async def token_account(self, address, owner, mint, *, allow_missing=False):
        value = await self.account(address)
        if value is None and allow_missing: return 0
        if not value or value["owner"] != TOKEN or value["data"]["parsed"]["type"] != "account":
            raise ValueError("A classic SPL token account is required.")
        info = value["data"]["parsed"]["info"]
        if info["owner"] != owner or info["mint"] != mint or info["state"] != "initialized" or info.get("delegate") or info.get("closeAuthority"):
            raise ValueError("Token account identity/state/delegation differs from treasury policy.")
        return int(info["tokenAmount"]["amount"])


class JupiterQuotes:
    def __init__(self, client, api_key): self.client, self.api_key = client, api_key

    async def request(self, path, *, params=None, body=None):
        headers = {"x-api-key": self.api_key.get_secret_value()}
        if body is None:
            response = await self.client.get("https://api.jup.ag/swap/v1/" + path, params=params, headers=headers, timeout=15, follow_redirects=False)
        else:
            response = await self.client.post("https://api.jup.ag/swap/v1/" + path, json=body, headers=headers, timeout=15, follow_redirects=False)
        response.raise_for_status()
        return response.json()

    async def purchase(self, owner, mint, quantity, slippage):
        quote = await self.request("quote", params={"inputMint": USDC, "outputMint": mint, "amount": str(quantity),
            "slippageBps": slippage, "swapMode": "ExactIn", "onlyDirectRoutes": "true", "asLegacyTransaction": "true",
            "dexes": "Raydium,Raydium CLMM,Raydium CPMM,Whirlpool"})
        if (quote["inputMint"] != USDC or quote["outputMint"] != mint or quote["inAmount"] != str(quantity)
                or quote["swapMode"] != "ExactIn" or quote["slippageBps"] != slippage or quote.get("platformFee")
                or not 0 <= D(quote["priceImpactPct"]) <= D("0.01")):
            raise ValueError("Quote exceeds the exact purchase policy.")
        minimum = int(quote["outAmount"]) * (10000 - slippage) // 10000
        if minimum <= 0 or int(quote["otherAmountThreshold"]) != minimum:
            raise ValueError("Quote minimum output differs from fixed slippage.")
        plan = quote["routePlan"]
        if len(plan) != 1 or plan[0]["percent"] != 100 or plan[0]["swapInfo"]["inputMint"] != USDC or plan[0]["swapInfo"]["outputMint"] != mint:
            raise ValueError("Only direct, single-pool exact-input routes are supported.")
        value = await self.request("swap-instructions", body={"userPublicKey": owner, "quoteResponse": quote,
            "useSharedAccounts": False, "wrapAndUnwrapSol": False, "asLegacyTransaction": True,
            "destinationTokenAccount": ata(owner, mint), "dynamicSlippage": False, "dynamicComputeUnitLimit": False,
            "computeUnitPriceMicroLamports": 0})
        # Construct all non-swap instructions ourselves; never sign provider setup,
        # transfers, cleanup, token-ledger, tips or an opaque transaction blob.
        if value.get("tokenLedgerInstruction") or value.get("cleanupInstruction") or value.get("otherInstructions"):
            raise ValueError("Unexpected provider instruction outside the purchase route.")
        ix = deserialize_instruction(value["swapInstruction"])
        validate_route(ix, owner, mint, quantity, int(quote["outAmount"]), slippage)
        return quote, ix


def validate_route(ix, owner, mint, quantity, quoted_output, slippage):
    data, accounts = ix.data, ix.accounts
    # Jupiter's published classic route IDL. Refuse unknown variants/versions.
    # One route-plan step: enum + optional direction + percent/input/output.
    if str(ix.program_id) != JUPITER or data[:8] != bytes([229, 23, 203, 119, 221, 11, 109, 12]) or data[8:12] != struct.pack("<I", 1):
        raise ValueError("Unsupported Jupiter instruction/route version.")
    variant = data[12] if len(data) > 12 else -1
    step_size = 5 if variant == 17 else 4
    if variant not in {7, 17, 26, 40, 46} or len(data) != 12 + step_size + 19:
        raise ValueError("Unsupported bounded DEX route.")
    if variant == 17 and data[13] not in (0, 1): raise ValueError("Invalid Whirlpool direction.")
    if data[12 + step_size - 3:12 + step_size] != bytes([100, 0, 1]): raise ValueError("Route changes the single-pool input/output path.")
    if struct.unpack("<QQHB", data[-19:]) != (quantity, quoted_output, slippage, 0):
        raise ValueError("Swap instruction amount/slippage differs from the reviewed quote.")
    expected = [TOKEN, owner, ata(owner, USDC), ata(owner, mint)]
    if (len(accounts) < 7 or [str(a.pubkey) for a in accounts[:4]] != expected
            or str(accounts[4].pubkey) not in {JUPITER, ata(owner, mint)}
            or str(accounts[5].pubkey) != mint or str(accounts[6].pubkey) != JUPITER):
        raise ValueError("Swap accounts do not match treasury input/output authority.")
    if [str(a.pubkey) for a in accounts if a.is_signer] != [owner]: raise ValueError("Unexpected swap signing authority.")
