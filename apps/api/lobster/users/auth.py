"""Local EOA sign-in. Authentication never grants exchange permissions."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address
from pydantic import Field
from sqlalchemy import BigInteger, JSON, String, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..admission import consume
from ..domain import Contract, utcnow
from .contracts import Address

ORIGIN = "http://127.0.0.1:3000"
CHAIN_ID = 421614
STATEMENT = "Sign in to the local Claw Desk testnet workspace. This grants no trading, transfer or fee approval."
SCOPE = "testnet:preview"
CURVE_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


class ChallengeInput(Contract):
    address: Address


class VerifyInput(Contract):
    challenge_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    signature: str = Field(pattern=r"^0x[0-9a-fA-F]{130}$")


class AuthError(Exception):
    def __init__(self, status=401, message="Wallet proof or session is invalid, expired or already used.", retry=None):
        self.status, self.message, self.retry = status, message, retry


class Base(DeclarativeBase):
    pass


class AuthControl(Base):
    __tablename__ = "user_auth_control"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Challenge(Base):
    __tablename__ = "user_auth_challenges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    expires_us: Mapped[int] = mapped_column(BigInteger, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class UserSession(Base):
    __tablename__ = "user_auth_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Token hash only.
    expires_us: Mapped[int] = mapped_column(BigInteger, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


def micros(now: datetime) -> int:
    delta = now - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def iso(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


def message(address: str, nonce: str, issued: str, expires: str, request_id: str, *, origin=ORIGIN, network="testnet") -> str:
    if network not in {"testnet", "mainnet"}: raise ValueError("Unsupported authentication network.")
    statement = STATEMENT if origin == ORIGIN else STATEMENT.replace("local ", "")
    statement = statement.replace("testnet", network)
    chain_id = CHAIN_ID if network == "testnet" else 42161
    return (f"{origin} wants you to sign in with your Ethereum account:\n{to_checksum_address(address)}\n\n"
        f"{statement}\n\nURI: {origin}\nVersion: 1\nChain ID: {chain_id}\nNonce: {nonce}"
        f"\nIssued At: {issued}\nExpiration Time: {expires}\nRequest ID: {request_id}")


class UserAuth:
    def __init__(self, store, *, origin=ORIGIN, network="testnet"):
        if network not in {"testnet", "mainnet"}: raise ValueError("Unsupported authentication network.")
        self.network, self.scope = network, network + ":preview"
        self.chain_id = CHAIN_ID if network == "testnet" else 42161
        self.store = store
        self.origin = origin
        self.boot = secrets.token_hex(16)  # Restart invalidates every prior proof/session.
        Base.metadata.create_all(store.engine)
        with store.transaction() as session:
            if not session.get(AuthControl, 1):
                session.add(AuthControl(id=1, payload={"last_seen_us": 0, "admission": {"last_seen_us": 0, "peers": {}}}))

    def clock(self, session) -> tuple[datetime, int]:
        now = utcnow()
        current = micros(now)
        row = session.get(AuthControl, 1)
        if not row or type(row.payload.get("last_seen_us")) is not int or current < row.payload["last_seen_us"]:
            raise AuthError(503, "Wallet authentication is unavailable until the local clock and database are healthy.")
        row.payload = row.payload | {"last_seen_us": current}
        return now, current

    def admit(self, peer: str):
        with self.store.transaction() as session:
            now, _ = self.clock(session)
            row = session.get(AuthControl, 1)
            state, retry = consume(row.payload["admission"], peer, now)
            row.payload = row.payload | {"admission": state}
        if retry:
            raise AuthError(429, "Wallet authentication request limit reached. Wait before trying again.", retry)

    def challenge(self, address: str, peer: str) -> dict:
        self.admit(peer)
        with self.store.transaction() as session:
            now, current = self.clock(session)
            session.execute(delete(Challenge).where(Challenge.expires_us <= current))
            session.execute(delete(UserSession).where(UserSession.expires_us <= current))
            if session.scalar(select(func.count()).select_from(Challenge)) >= 256:
                raise AuthError(429, "Wallet challenge capacity reached. Retry after old challenges expire.", 120)
            request_id, nonce = secrets.token_hex(16), secrets.token_hex(16)
            expires = now + timedelta(minutes=2)
            data = {"address": address, "boot": self.boot, "nonce": nonce, "issued_at": iso(now), "expires_at": iso(expires), "used": False}
            session.add(Challenge(id=request_id, expires_us=micros(expires), payload=data))
        return {"challenge_id": request_id, "address": address, "origin": self.origin, "chain_id": self.chain_id,
            "nonce": nonce, "issued_at": data["issued_at"], "expires_at": data["expires_at"],
            "message": message(address, nonce, data["issued_at"], data["expires_at"], request_id, origin=self.origin, network=self.network),
            "scope": self.scope, "order_submission_enabled": False, "fee_collection_enabled": False}

    def verify(self, body: VerifyInput, peer: str) -> dict:
        self.admit(peer)
        # No external call. Recover the exact server-generated message; clients cannot supply one.
        with self.store.transaction() as session:
            _, current = self.clock(session)
            row = session.get(Challenge, body.challenge_id)
            if not row or row.expires_us <= current or row.payload["used"] or row.payload["boot"] != self.boot:
                raise AuthError()
            data = dict(row.payload)
        signature = bytes.fromhex(body.signature[2:])
        r, s, v = int.from_bytes(signature[:32]), int.from_bytes(signature[32:64]), signature[64]
        if not 0 < r < CURVE_N or not 0 < s <= CURVE_N // 2 or v not in (27, 28):
            raise AuthError()
        try:
            signer = Account.recover_message(encode_defunct(text=message(data["address"], data["nonce"],
                data["issued_at"], data["expires_at"], body.challenge_id, origin=self.origin, network=self.network)), signature=signature).lower()
        except Exception:
            raise AuthError() from None
        if signer != data["address"]:
            raise AuthError()
        token = secrets.token_urlsafe(32)
        with self.store.transaction() as session:
            now, current = self.clock(session)
            row = session.get(Challenge, body.challenge_id)
            if not row or row.expires_us <= current or row.payload != data or row.payload["used"]:
                raise AuthError()
            if session.scalar(select(func.count()).select_from(UserSession).where(UserSession.expires_us > current)) >= 256:
                raise AuthError(429, "Local session capacity reached. Retry after existing sessions expire.", 900)
            expires = now + timedelta(minutes=15)
            session_data = {"address": signer, "boot": self.boot, "scope": self.scope, "issued_at": iso(now),
                "expires_at": iso(expires), "revoked": False}
            session.add(UserSession(id=sha256(token.encode()).hexdigest(), expires_us=micros(expires), payload=session_data))
            row.payload = data | {"used": True}
        return self.public(session_data) | {"access_token": token, "token_type": "Bearer"}

    def public(self, data: dict) -> dict:
        return {"address": data["address"], "scope": data["scope"], "expires_at": data["expires_at"],
            "authenticated": True, "authentication_method": "eip191_eoa", "network": self.network,
            "order_submission_enabled": False, "fee_collection_enabled": False}

    def require(self, authorization: str | None) -> dict:
        if not authorization or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization):
            raise AuthError()
        key = sha256(authorization[7:].encode()).hexdigest()
        with self.store.transaction() as session:
            _, current = self.clock(session)
            row = session.get(UserSession, key)
            if (not row or row.expires_us <= current or row.payload["revoked"] or row.payload["boot"] != self.boot
                    or row.payload["scope"] != self.scope):
                raise AuthError()
            return self.public(row.payload)

    def logout(self, authorization: str | None):
        self.require(authorization)
        key = sha256(authorization[7:].encode()).hexdigest()
        with self.store.transaction() as session:
            self.clock(session)
            row = session.get(UserSession, key)
            row.payload = row.payload | {"revoked": True}
