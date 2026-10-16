from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from lobster.config import Settings
from lobster.domain import utcnow
from lobster.execution.settings import TestnetSettings
from lobster.main import create_app
from lobster.store import Store
from lobster.users import auth
from lobster.users.auth import AuthError, Challenge, CURVE_N, UserAuth, UserSession, VerifyInput

# Public cryptographic test vectors. NEVER fund these accounts.
KEY = "0x" + "0" * 63 + "1"
OTHER_KEY = "0x" + "0" * 63 + "2"
ADDRESS = Account.from_key(KEY).address.lower()


@pytest.fixture
def clock(monkeypatch):
    value = [utcnow()]
    monkeypatch.setattr(auth, "utcnow", lambda: value[0])
    return value


@pytest.fixture
def service(tmp_path, clock):
    store = Store(f"sqlite:///{tmp_path / 'auth.db'}")
    yield UserAuth(store)
    store.engine.dispose()


def proof(challenge, key=KEY, message=None):
    signature = Account.sign_message(encode_defunct(text=message or challenge["message"]), key).signature
    return VerifyInput(challenge_id=challenge["challenge_id"], signature="0x" + signature.hex())


def login(service, peer="test"):
    return service.verify(proof(service.challenge(ADDRESS, peer)), peer)


def test_exact_scoped_message_and_hashed_session_never_grant_exchange_authority(service):
    challenge = service.challenge(ADDRESS, "test")
    assert challenge["message"].startswith(auth.ORIGIN + " wants you to sign in with your Ethereum account:\n")
    assert Account.from_key(KEY).address in challenge["message"]
    assert "URI: http://127.0.0.1:3000\nVersion: 1\nChain ID: 421614\nNonce: " in challenge["message"]
    signed = proof(challenge)
    result = service.verify(signed, "test")
    token = result.pop("access_token")
    assert service.require("Bearer " + token) == {key: value for key, value in result.items() if key != "token_type"}
    assert result["scope"] == "testnet:preview"
    assert result["authenticated"] and not result["order_submission_enabled"] and not result["fee_collection_enabled"]
    with Session(service.store.engine) as session:
        stored = json.dumps([row.payload | {"id": row.id} for row in session.scalars(select(UserSession))])
        assert token not in stored and signed.signature not in stored and KEY not in stored
    public = json.dumps(service.store.state(None))
    assert token not in public and signed.signature not in public and "user_auth" not in public


@pytest.mark.parametrize("changed", ["127.0.0.1:3000", "Chain ID: 421614", "Nonce:", "no trading"])
def test_modified_domain_chain_nonce_or_statement_cannot_authenticate(service, changed):
    challenge = service.challenge(ADDRESS, "test")
    with pytest.raises(AuthError):
        service.verify(proof(challenge, message=challenge["message"].replace(changed, "changed")), "test")
    # A failed proof does not consume the legitimate owner's challenge.
    assert service.verify(proof(challenge), "test")["address"] == ADDRESS


def test_wrong_wallet_and_noncanonical_signature_are_refused(service):
    challenge = service.challenge(ADDRESS, "test")
    with pytest.raises(AuthError):
        service.verify(proof(challenge, OTHER_KEY), "test")
    signature = bytes.fromhex(proof(challenge).signature[2:])
    high_s = CURVE_N - int.from_bytes(signature[32:64])
    changed = signature[:32] + high_s.to_bytes(32) + bytes([55 - signature[64]])
    with pytest.raises(AuthError):
        service.verify(VerifyInput(challenge_id=challenge["challenge_id"], signature="0x" + changed.hex()), "test")


def test_one_time_proof_is_atomic_across_independent_store_connections(service):
    second = UserAuth(Store(str(service.store.engine.url)))
    second.boot = service.boot  # Simulate requests served by the same boot through independent connections.
    signed = proof(service.challenge(ADDRESS, "create"))
    def verify(index):
        try:
            return (service if index % 2 else second).verify(signed, f"peer-{index}")
        except AuthError as error:
            assert error.status == 401
            return None
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(verify, range(12)))
    assert sum(result is not None for result in results) == 1
    second.store.engine.dispose()


def test_expired_proofs_sessions_logout_and_restart_are_fail_closed(service, clock):
    challenge = service.challenge(ADDRESS, "challenge")
    clock[0] += timedelta(minutes=2)
    with pytest.raises(AuthError):
        service.verify(proof(challenge), "verify")
    result = login(service, "login")
    bearer = "Bearer " + result["access_token"]
    service.logout(bearer)
    with pytest.raises(AuthError):
        service.require(bearer)
    token = login(service, "second")["access_token"]
    pending = service.challenge(ADDRESS, "third")
    restarted = UserAuth(service.store)
    with pytest.raises(AuthError):
        restarted.require("Bearer " + token)
    with pytest.raises(AuthError):
        restarted.verify(proof(pending), "fourth")
    clock[0] += timedelta(minutes=15)
    with pytest.raises(AuthError):
        service.require("Bearer " + token)


def test_clock_rollback_blocks_challenges_and_existing_session(service, clock):
    token = login(service)["access_token"]
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(AuthError) as error:
        service.require("Bearer " + token)
    assert error.value.status == 503
    with pytest.raises(AuthError):
        service.challenge(ADDRESS, "new")


def test_auth_request_limit_survives_restart_and_prunes_expired_proofs(service, clock):
    for _ in range(10):
        service.challenge(ADDRESS, "peer")
    restarted = UserAuth(service.store)
    with pytest.raises(AuthError) as error:
        restarted.challenge(ADDRESS, "peer")
    assert error.value.status == 429 and error.value.retry == 60
    clock[0] += timedelta(minutes=2)
    restarted.challenge(ADDRESS, "peer")
    with Session(service.store.engine) as session:
        assert len(list(session.scalars(select(Challenge)))) == 1


@pytest.mark.parametrize("bearer", [None, "Bearer not-a-token", "Bearer " + "é" * 43, "Bearer " + "a" * 43])
def test_unknown_or_malformed_bearer_is_refused(service, bearer):
    with pytest.raises(AuthError):
        service.require(bearer)


def test_http_authentication_exposes_no_signing_or_order_route(tmp_path, clock, monkeypatch):
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}", worker_enabled=False),
        TestnetSettings(_env_file=None))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        def no_network(*args):
            pytest.fail("Wallet authentication attempted exchange access")
        monkeypatch.setattr(app.state.users, "inspect", no_network)
        prefix = "/api/v1/users/testnet/auth/"
        assert client.get(prefix + "session").status_code == 401
        challenge = client.post(prefix + "challenge", json={"address": ADDRESS}).json()
        signed = proof(challenge)
        result = client.post(prefix + "verify", json=signed.model_dump()).json()
        headers = {"Authorization": "Bearer " + result["access_token"]}
        response = client.get(prefix + "session", headers=headers)
        assert response.status_code == 200 and response.json()["address"] == ADDRESS
        assert response.headers["Cache-Control"] == "no-store"
        assert client.post(prefix + "verify", json=signed.model_dump()).status_code == 401
        assert client.post("/api/v1/users/testnet/orders", json={}, headers=headers).status_code == 404
        assert client.post(prefix + "logout", headers=headers).status_code == 200
        assert client.get(prefix + "session", headers=headers).status_code == 401
        # Server constructs message/domain/scope; client overrides are invalid.
        assert client.post(prefix + "challenge", json={"address": ADDRESS, "origin": "https://evil.invalid"}).status_code == 422
        monkeypatch.setattr(app.state.user_auth, "require", lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic-secret-marker")))
        failed = client.get(prefix + "session", headers=headers)
        assert failed.status_code == 503 and "synthetic-secret-marker" not in failed.text
