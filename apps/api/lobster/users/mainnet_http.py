"""Explicit mainnet user consent routes. No HTTP handler dispatches money."""
import re

from fastapi import Header, HTTPException, Request

from ..execution.contracts import ReviewedSetup
from ..execution.gateway import HyperliquidMainnet
from .auth import AuthError, ChallengeInput, VerifyInput
from .contracts import Address
from .financial import FinancialRequest, FinancialProof
from .intents import ProfileInput
from .orders import PreviewInput, illustrate


def install(app, config, require_operator):
    def auth(request, method, *args):
        try: return method(*args)
        except AuthError as error:
            raise HTTPException(error.status, error.message, headers={"Retry-After": str(error.retry)} if error.retry else None) from None

    def identity(request, authorization, *, write=False):
        service = request.app.state.mainnet_auth
        owner = auth(request, service.require, authorization)["address"]
        if write:
            if not config.financial_enabled: raise HTTPException(503, "Mainnet financial consent is disabled.")
            auth(request, service.admit, "mainnet-financial:" + owner)
        return owner

    async def account(request, owner):
        try: return await request.app.state.mainnet_users.inspect(owner)
        except Exception: raise HTTPException(502, "Fresh mainnet account data is unavailable. No order was submitted.") from None

    def request_key(value):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", value): raise HTTPException(422, "Bounded request identity required.")

    @app.get("/api/v1/users/mainnet/config")
    def settings(request: Request): return request.app.state.mainnet_users.config()

    @app.get("/api/v1/users/mainnet/accounts/{address}")
    async def public_account(address: Address, request: Request): return await account(request, address)

    @app.post("/api/v1/users/mainnet/auth/challenge")
    def challenge(body: ChallengeInput, request: Request):
        return auth(request, request.app.state.mainnet_auth.challenge, body.address, request.client.host if request.client else "local")

    @app.post("/api/v1/users/mainnet/auth/verify")
    def verify(body: VerifyInput, request: Request):
        return auth(request, request.app.state.mainnet_auth.verify, body, request.client.host if request.client else "local")

    @app.get("/api/v1/users/mainnet/auth/session")
    def session(request: Request, authorization: str | None = Header(default=None)):
        return auth(request, request.app.state.mainnet_auth.require, authorization)

    @app.post("/api/v1/users/mainnet/auth/logout")
    def logout(request: Request, authorization: str | None = Header(default=None)):
        auth(request, request.app.state.mainnet_auth.logout, authorization)
        return {"authenticated": False, "revoked": True}

    @app.get("/api/v1/users/mainnet/capital")
    def capital(request: Request, authorization: str | None = Header(default=None)):
        return {"reference": request.app.state.mainnet_capital.get(identity(request, authorization)), "entry_permission": False}

    @app.post("/api/v1/users/mainnet/capital/refresh")
    async def refresh(request: Request, authorization: str | None = Header(default=None)):
        owner = identity(request, authorization)
        auth(request, request.app.state.mainnet_auth.admit, "mainnet-capital:" + (request.client.host if request.client else "local"))
        ledger = request.app.state.mainnet_capital
        previous = ledger.get(owner)
        state = await account(request, owner)
        end = state.get("exchange_time_ms")
        if type(end) is not int: raise HTTPException(502, "An exact accounting timestamp is required.")
        if previous and end < previous["cursor_ms"]: return {"reference": ledger.get(owner), "entry_permission": False}
        start = max(previous["baseline_ms"], previous["cursor_ms"] - 5000) if previous else end
        try:
            receipts = await request.app.state.mainnet_users.capital_history(owner, start, end) if previous else []
            identity(request, authorization)
            reference = ledger.observe(owner, state, start, receipts, complete=True)
        except ValueError:
            ledger.halt(owner, "Incomplete or conflicting mainnet accounting history requires review.")
            raise HTTPException(409, "Capital history could not be reconciled. No entry permission was granted.") from None
        except HTTPException: raise
        except Exception: raise HTTPException(502, "Capital history is unavailable. No entry permission was granted.") from None
        return {"reference": reference, "entry_permission": False}

    @app.post("/api/v1/operator/user-mainnet-profile")
    def profile(body: ProfileInput, request: Request, authorization: str | None = Header(default=None)):
        require_operator(authorization)
        if body.network != "mainnet" or body.builder != config.builder_address or body.fee_tenths_bps != config.builder_fee_tenths_bps:
            raise HTTPException(409, "The mainnet profile must match the configured network, builder and fee.")
        try: return request.app.state.mainnet_intents.configure(body)
        except ValueError as error: raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/users/mainnet/order-preview", status_code=201)
    async def preview(body: PreviewInput, request: Request, idempotency_key: str = Header(alias="Idempotency-Key"),
                      authorization: str | None = Header(default=None)):
        owner = identity(request, authorization)
        request_key(idempotency_key)
        plans, runtime = request.app.state.mainnet_plans, request.app.state.runtime
        try: previous = plans.by_request(owner, idempotency_key, body.episode_id)
        except ValueError as error: raise HTTPException(409, str(error)) from None
        if previous: return previous
        auth(request, request.app.state.mainnet_auth.admit, "mainnet-preview:" + (request.client.host if request.client else "local"))
        episode = runtime.store.get_episode(body.episode_id)
        if not episode: raise HTTPException(404, "Reviewed mainnet setup not found.")
        try: ReviewedSetup.from_episode(episode, runtime.store.policy, network="mainnet")
        except ValueError as error: raise HTTPException(409, str(error)) from None
        state = await account(request, owner)
        try: rules, market = await HyperliquidMainnet(request.app.state.mainnet_users.client, owner).market()
        except Exception: raise HTTPException(502, "A fresh mainnet BTC market is unavailable.") from None
        try:
            plan = illustrate(episode, owner, state, market, rules, runtime.store.policy,
                request.app.state.mainnet_capital.get(owner), network="mainnet")
            identity(request, authorization)
            return plans.save(owner, idempotency_key, plan)
        except ValueError as error: raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/users/mainnet/order-previews/{plan_id}")
    def saved(plan_id: str, request: Request, authorization: str | None = Header(default=None)):
        result = request.app.state.mainnet_plans.get(identity(request, authorization), plan_id)
        if not result: raise HTTPException(404, "Owner-bound mainnet preview not found.")
        return result

    @app.get("/api/v1/users/mainnet/financial")
    def context(request: Request, authorization: str | None = Header(default=None)):
        owner = identity(request, authorization)
        try: return request.app.state.mainnet_financial.context(owner, config.execution_root, config.financial_enabled)
        except Exception: raise HTTPException(503, "Private mainnet execution context is unavailable.") from None

    @app.post("/api/v1/users/mainnet/financial/jobs", status_code=201)
    def prepare(body: FinancialRequest, request: Request, authorization: str | None = Header(default=None),
                idempotency_key: str = Header(alias="Idempotency-Key")):
        owner = identity(request, authorization, write=True)
        request_key(idempotency_key)
        financial = request.app.state.mainnet_financial
        try: return financial.view(financial.prepare(owner, body, idempotency_key))
        except ValueError as error: raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/users/mainnet/financial/jobs/{job_id}/proof")
    def proof(job_id: str, body: FinancialProof, request: Request, authorization: str | None = Header(default=None)):
        owner = identity(request, authorization, write=True)
        financial = request.app.state.mainnet_financial
        try: return financial.view(financial.verify(owner, job_id, body.signature))
        except ValueError as error: raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/users/mainnet/financial/jobs/{job_id}")
    def job(job_id: str, request: Request, authorization: str | None = Header(default=None)):
        financial = request.app.state.mainnet_financial
        result = financial.get(identity(request, authorization), job_id)
        if not result: raise HTTPException(404, "Owner-bound mainnet financial job not found.")
        return financial.view(result)
