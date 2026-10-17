"""Loopback development API. No exchange signing or mainnet order endpoints."""

import asyncio
from contextlib import ExitStack, asynccontextmanager
import hmac
import json
import logging
import re

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

import httpx

from .agents import AnthropicReviewer, DemoReviewer
from .config import Settings
from .domain import Contract, OperatorAction, PitchInput, Snapshot, utcnow
from .market import DemoFeed, HyperliquidFeed
from .pipeline import Pipeline
from .store import Store
from .execution.settings import TestnetSettings
from .execution.workbench import TestnetWorkbench
from .users.contracts import Address, UserTestnetSettings
from .users.service import UserTestnetService
from .users.fees import ConsentInput, FeeQuoteInput, consent_plan, fee_quote
from .users.auth import AuthError, ChallengeInput, VerifyInput, UserAuth
from .users.orders import PreviewInput, UserPlans, illustrate
from .users.capital import UserCapital
from .users.intents import UserIntents, IntentInput, ProfileInput
from .execution.gateway import HyperliquidTestnet
from .execution.contracts import ReviewedSetup
from .http_boundary import LocalBoundary, LOCAL_ORIGINS
from .ops.readiness import readiness
from .ops.worker import worker_lease
from .research.data import HistoryFeed
from .research.providers import AnthropicResearcher, DemoResearcher
from .research.service import Research
from .economics.distribution import DistributionPolicy, distribution
from .economics.book import TreasuryBook
from .economics.solana_treasury import public_solana_report
from pathlib import Path
from .funding import PaperFunding

logger = logging.getLogger(__name__)


class Runtime:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.market: Snapshot | None = None
        self.market_error: str | None = None
        self.worker_error: str | None = None
        self.tasks: dict[str, asyncio.Task] = {}
        self.last_market_tick = None
        self.last_decision_tick = None
        self.last_research_tick = None
        self.research_error = None
        self.research = Research(store, settings)
        self.funding = PaperFunding(store)
        if settings.paper_funding_enabled: self.funding.enable()

    async def funding_loop(self, client):
        while True:
            try:
                pending = await asyncio.to_thread(self.funding.pending)
                if pending:
                    earliest = min(p["funding_cursor"] for p in pending)
                    count = max(240, (int(utcnow().timestamp()) // 3600 * 3600 - earliest) // 3600 + 1)
                    if count > 4000: raise ValueError("Paper funding recovery exceeds available history.")
                    dataset = await HistoryFeed(client, self.settings.market_source, count).fetch()
                    await asyncio.to_thread(self.funding.apply, dataset)
            except Exception:
                await asyncio.to_thread(self.funding.fail)
            await asyncio.sleep(15)

    async def research_loop(self, history, researcher):
        dataset, next_fetch = None, 0
        while True:
            try:
                now = utcnow().timestamp()
                if self.market is not None and now >= next_fetch:
                    dataset = None
                    next_fetch = now + 300  # Bound retry traffic on data failures.
                    dataset = await history.fetch()
                    next_fetch = (int(now) // 3600 + 1) * 3600 + 30
                if dataset is not None and self.market is not None:
                    await self.research.run(dataset, researcher)
                    await asyncio.to_thread(self.research.emit, dataset, self.market)
                    self.research_error = None
            except Exception as error:
                logger.warning("Research tick unavailable (%s)", type(error).__name__)
                self.research_error = "Research data or audit checks are unavailable. New research signals wait; paper position protection is independent."
            finally:
                self.last_research_tick = utcnow()
            await asyncio.sleep(15)

    async def market_loop(self, feed):
        while True:
            try:
                self.market = await feed.fetch()
                self.market_error = None
                # Protection runs independently from model latency.
                self.store.mark(self.market)
                for ep in self.store.working_episodes():
                    if ep["status"] == "approved":
                        self.store.try_fill(ep["id"], self.market)
                self.store.mark(self.market)
            except Exception as error:
                logger.warning("Market/protection tick failed (%s)", type(error).__name__)
                self.market_error = "Market update or protection failed. New entries wait for a healthy fresh snapshot."
                # Invalidates entry authority even if the previous snapshot is still young.
                self.market = None
            finally:
                self.last_market_tick = utcnow()
            await asyncio.sleep(self.settings.market_poll_seconds)

    async def decision_loop(self, reviewer):
        pipeline = Pipeline(self.store, reviewer, self.settings.max_review_calls_per_day)
        while True:
            try:
                await pipeline.step(self.market)
                self.worker_error = None
            except Exception as error:
                logger.warning("Decision worker failed (%s)", type(error).__name__)
                self.worker_error = "Decision worker could not advance. Existing position protection remains independent."
            finally:
                self.last_decision_tick = utcnow()
            await asyncio.sleep(max(self.settings.review_interval_seconds, 0.05))

    def snapshot(self):
        stale = self.market is None or not -2 <= (utcnow() - self.market.timestamp).total_seconds() <= self.store.policy.max_data_age_seconds
        return self.store.state(self.market) | {
            "market": self.market.model_dump(mode="json") if self.market else None,
            "policy": self.store.policy.model_dump(mode="json"),
            "service": {"execution_mode": "paper", "market_source": self.settings.market_source,
                "agent_provider": self.settings.agent_provider,
                "model": self.settings.anthropic_model if self.settings.agent_provider == "anthropic" else "scripted-review-v1",
                "data_stale": stale, "market_error": self.market_error, "worker_error": self.worker_error,
                "operator_enabled": bool(self.settings.operator_token), "user_trading_enabled": False,
                "fee_collection_enabled": False, "worker_enabled": self.settings.worker_enabled,
                "research_enabled": self.settings.research_enabled, "research_error": self.research_error}}


class StageTestnetInput(Contract):
    episode_id: str = Field(min_length=1, max_length=64)


def create_app(settings: Settings | None = None, testnet_settings: TestnetSettings | None = None,
               user_settings: UserTestnetSettings | None = None) -> FastAPI:
    config = settings or Settings()
    testnet_config = testnet_settings or TestnetSettings()
    user_config = user_settings or UserTestnetSettings()

    def require_operator(authorization: str | None):
        if not config.operator_token:
            raise HTTPException(503, "Operator controls are disabled. Configure OPERATOR_TOKEN locally.")
        expected = "Bearer " + config.operator_token.get_secret_value()
        if not authorization or not hmac.compare_digest(authorization.encode("utf-8"), expected.encode("utf-8")):
            raise HTTPException(401, "Invalid operator credentials.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as resources:
            if config.worker_enabled:
                resources.enter_context(worker_lease(config.database_url))
            runtime = Runtime(config, Store(config.database_url, config.initial_capital))
            resources.callback(runtime.store.engine.dispose)
            runtime.store.bind_market_source(config.market_source)
            if config.worker_enabled and config.research_enabled:
                runtime.research.recover()
            app.state.runtime = runtime
            app.state.user_auth = UserAuth(runtime.store)
            app.state.user_plans = UserPlans(runtime.store)
            app.state.user_capital = UserCapital(runtime.store)
            app.state.user_intents = UserIntents(runtime.store)
            async with httpx.AsyncClient(timeout=10) as client:
                app.state.testnet = TestnetWorkbench(testnet_config, client, config.database_url)
                if app.state.testnet.ledger:
                    resources.callback(app.state.testnet.ledger.engine.dispose)
                app.state.users = UserTestnetService(user_config, client)
                feed = DemoFeed() if config.market_source == "demo" else HyperliquidFeed(client, testnet=config.market_source == "hyperliquid-testnet")
                reviewer = DemoReviewer() if config.agent_provider == "demo" else AnthropicReviewer(client, config)
                tasks = []
                if config.worker_enabled:
                    runtime.tasks = {"market": asyncio.create_task(runtime.market_loop(feed)),
                                     "decision": asyncio.create_task(runtime.decision_loop(reviewer))}
                    if config.research_enabled:
                        researcher = DemoResearcher() if config.agent_provider == "demo" else AnthropicResearcher(client, config)
                        runtime.tasks["research"] = asyncio.create_task(runtime.research_loop(
                            HistoryFeed(client, config.market_source, config.research_history_bars), researcher))
                    if config.paper_funding_enabled:
                        runtime.tasks["funding"] = asyncio.create_task(runtime.funding_loop(client))
                    tasks = list(runtime.tasks.values())
                try:
                    yield
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Lobster Desk", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(LOCAL_ORIGINS),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key", "Authorization"])
    app.add_middleware(LocalBoundary)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"], www_redirect=False)

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        return JSONResponse({"detail": error.message}, status_code=error.status,
            headers={"Retry-After": str(error.retry)} if error.retry else {})

    def auth_call(request: Request, operation, *args):
        try:
            return operation(*args)
        except AuthError:
            raise
        except Exception as error:
            logger.warning("Wallet authentication unavailable (%s)", type(error).__name__)
            raise AuthError(503, "Wallet authentication is unavailable. Check the local database.") from None

    @app.post("/api/v1/users/testnet/auth/challenge")
    def auth_challenge(body: ChallengeInput, request: Request):
        return auth_call(request, request.app.state.user_auth.challenge, body.address, request.client.host if request.client else "local")

    @app.post("/api/v1/users/testnet/auth/verify")
    def auth_verify(body: VerifyInput, request: Request):
        return auth_call(request, request.app.state.user_auth.verify, body, request.client.host if request.client else "local")

    @app.get("/api/v1/users/testnet/auth/session")
    def auth_session(request: Request, authorization: str | None = Header(default=None)):
        return auth_call(request, request.app.state.user_auth.require, authorization)

    @app.get("/api/v1/users/testnet/capital")
    def user_capital_get(request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        return {"reference": request.app.state.user_capital.get(identity["address"]), "entry_permission": False}

    @app.post("/api/v1/users/testnet/capital/refresh")
    async def user_capital_refresh(request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        auth_call(request, request.app.state.user_auth.admit, "capital:" + (request.client.host if request.client else "local"))
        address, ledger = identity["address"], request.app.state.user_capital
        previous = ledger.get(address)
        account = await fresh_user_account(request, address)
        end = account.get("exchange_time_ms")
        if type(end) is not int:
            raise HTTPException(502, "The exchange account lacks an exact accounting timestamp.")
        if previous and end < previous["cursor_ms"]:
            return {"reference": ledger.get(address), "entry_permission": False}
        start = max(previous["baseline_ms"], previous["cursor_ms"] - 5000) if previous else end
        try:
            receipts = await request.app.state.users.capital_history(address, start, end) if previous else []
            auth_call(request, request.app.state.user_auth.require, authorization)
            result = ledger.observe(address, account, start, receipts, complete=True)
        except ValueError:
            ledger.halt(address, "Unsupported, incomplete or conflicting accounting history requires owner review.")
            raise HTTPException(409, "Capital history could not be reconciled conservatively. No entry permission was granted.") from None
        except HTTPException:
            raise
        except AuthError:
            raise
        except Exception:
            raise HTTPException(502, "Capital observation is unavailable. No entry permission was granted.") from None
        return {"reference": result, "entry_permission": False}

    @app.post("/api/v1/users/testnet/auth/logout")
    def auth_logout(request: Request, authorization: str | None = Header(default=None)):
        auth_call(request, request.app.state.user_auth.logout, authorization)
        return {"authenticated": False, "revoked": True}

    @app.get("/api/health")
    def health(request: Request):
        runtime = request.app.state.runtime
        return {"status": "degraded" if runtime.market_error or runtime.worker_error else "ok", "execution_mode": "paper", "probe": "liveness"}

    @app.get("/api/ready")
    def ready(request: Request):
        report = readiness(request.app.state.runtime, request.app.state.testnet)
        return JSONResponse(report, status_code=200 if report["service_ready"] else 503)

    @app.get("/api/v1/ops/status")
    def operations(request: Request):
        return readiness(request.app.state.runtime, request.app.state.testnet)

    @app.get("/api/v1/state")
    def state(request: Request):
        return request.app.state.runtime.snapshot()

    @app.get("/api/v1/research")
    def research_summary(request: Request):
        runtime = request.app.state.runtime
        try:
            return runtime.research.summary() | {"error": runtime.research_error,
                "last_tick_at": runtime.last_research_tick.isoformat() if runtime.last_research_tick else None}
        except Exception:
            raise HTTPException(503, "Research audit is unavailable. No research entry authority was granted.") from None

    @app.get("/api/v1/research/{campaign_id}")
    def research_details(campaign_id: str, request: Request):
        if not re.fullmatch(r"[a-f0-9]{64}", campaign_id): raise HTTPException(422, "Invalid research identifier.")
        try:
            result = request.app.state.runtime.research.get(campaign_id)
        except Exception:
            raise HTTPException(503, "Research audit could not be validated.") from None
        if not result: raise HTTPException(404, "Research cohort not found.")
        return result

    @app.get("/api/v1/economics")
    def economics(request: Request):
        try:
            book = TreasuryBook(Path(config.treasury_path))
            return distribution(book, DistributionPolicy()) | {"solana": public_solana_report(book)}
        except Exception:
            raise HTTPException(503, "Treasury receipt arithmetic is unavailable. No transfers were authorized.") from None

    @app.post("/api/v1/pitches", status_code=201)
    def submit(pitch: PitchInput, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", idempotency_key):
            raise HTTPException(422, "Use an 8-64 character alphanumeric Idempotency-Key.")
        runtime = request.app.state.runtime
        client = request.client.host if request.client else "local"
        try:
            retry = runtime.store.consume_pitch_request(client)
        except Exception as error:
            logger.warning("Pitch admission unavailable (%s)", type(error).__name__)
            raise HTTPException(503, "Pitch admission is unavailable. Check the local database before retrying.") from None
        if retry:
            raise HTTPException(429, "Pitch request limit reached. Wait before trying again.", headers={"Retry-After": str(retry)})
        try:
            return runtime.store.submit(pitch, idempotency_key)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/episodes/{episode_id}")
    def episode(episode_id: str, request: Request):
        result = request.app.state.runtime.store.get_episode(episode_id)
        if not result:
            raise HTTPException(404, "Episode not found.")
        return result

    @app.get("/api/v1/events")
    async def events(request: Request, after: int = Query(default=0, ge=0),
                     last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
        cursor = max(after, int(last_event_id)) if last_event_id and last_event_id.isdigit() else after
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                items = request.app.state.runtime.store.events(cursor)
                for item in items:
                    cursor = item["id"]
                    yield f"id: {cursor}\nevent: decision\ndata: {json.dumps(item)}\n\n"
                if not items:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/v1/journal")
    def journal(request: Request, after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=1000)):
        return {"events": request.app.state.runtime.store.events(after, limit)}

    @app.get("/api/v1/testnet/status")
    def testnet_status(request: Request):
        return request.app.state.testnet.status()

    @app.get("/api/v1/users/testnet/config")
    def user_testnet_config(request: Request):
        return request.app.state.users.config()

    @app.get("/api/v1/users/testnet/accounts/{address}")
    async def user_testnet_account(address: Address, request: Request):
        try:
            return await request.app.state.users.inspect(address)
        except Exception:
            raise HTTPException(502, "Testnet account data is unavailable or malformed. No exchange write was attempted.") from None

    async def fresh_user_account(request: Request, address: str):
        try:
            return await request.app.state.users.inspect(address)
        except Exception:
            raise HTTPException(502, "A fresh testnet account observation is unavailable. No permission or order was submitted.") from None

    @app.post("/api/v1/users/testnet/fee-quote")
    async def user_fee_quote(body: FeeQuoteInput, request: Request):
        account = await fresh_user_account(request, body.address)
        try:
            return fee_quote(body, account)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/users/testnet/consent-preview")
    async def user_consent_preview(body: ConsentInput, request: Request):
        if not user_config.builder_address:
            raise HTTPException(409, "Configure a public testnet builder address first.")
        account = await fresh_user_account(request, body.address)
        try:
            return consent_plan(body, user_config, account)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/users/testnet/order-preview", status_code=201)
    async def user_order_preview(body: PreviewInput, request: Request,
            idempotency_key: str = Header(alias="Idempotency-Key"), authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", idempotency_key):
            raise HTTPException(422, "Use an 8-64 character alphanumeric Idempotency-Key.")
        plans = request.app.state.user_plans
        try:
            existing = plans.by_request(identity["address"], idempotency_key, body.episode_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if existing:
            return existing
        peer = request.client.host if request.client else "local"
        auth_call(request, request.app.state.user_auth.admit, "order-preview:" + peer)
        episode = request.app.state.runtime.store.get_episode(body.episode_id)
        if not episode:
            raise HTTPException(404, "Reviewed setup not found.")
        try:
            ReviewedSetup.from_episode(episode, request.app.state.runtime.store.policy)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        account = await fresh_user_account(request, identity["address"])
        try:
            rules, market = await HyperliquidTestnet(request.app.state.users.client, identity["address"]).market()
        except Exception:
            raise HTTPException(502, "A fresh testnet BTC observation is unavailable. No order was submitted.") from None
        try:
            plan = illustrate(episode, identity["address"], account, market, rules, request.app.state.runtime.store.policy,
                request.app.state.user_capital.get(identity["address"]))
            auth_call(request, request.app.state.user_auth.require, authorization)
            return plans.save(identity["address"], idempotency_key, plan)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/users/testnet/order-previews/{plan_id}")
    def user_order_preview_get(plan_id: str, request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        result = request.app.state.user_plans.get(identity["address"], plan_id)
        if not result:
            raise HTTPException(404, "User preview not found.")
        return result

    @app.post("/api/v1/operator/user-testnet-profile")
    def user_profile(body: ProfileInput, request: Request, authorization: str | None = Header(default=None)):
        require_operator(authorization)
        if body.builder != user_config.builder_address or body.fee_tenths_bps != user_config.builder_fee_tenths_bps:
            raise HTTPException(409, "The profile must match the configured testnet builder and fee.")
        try:
            return request.app.state.user_intents.configure(body)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/users/testnet/permission-plans")
    def user_permission_plans(request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        auth_call(request, request.app.state.user_auth.admit, "intent:" + (request.client.host if request.client else "local"))
        try:
            return request.app.state.user_intents.approval_plans(identity["address"])
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/users/testnet/execution-context")
    def user_execution_context(request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        return auth_call(request, request.app.state.user_intents.context, identity["address"])

    @app.post("/api/v1/users/testnet/intents", status_code=201)
    def user_intent(body: IntentInput, request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        auth_call(request, request.app.state.user_auth.admit, "intent:" + (request.client.host if request.client else "local"))
        plan = request.app.state.user_plans.get(identity["address"], body.plan_id)
        if not plan:
            raise HTTPException(404, "User preview not found.")
        try:
            return request.app.state.user_intents.view(request.app.state.user_intents.prepare(identity["address"], plan))
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.get("/api/v1/users/testnet/intents/{intent_id}")
    def user_intent_get(intent_id: str, request: Request, authorization: str | None = Header(default=None)):
        identity = auth_call(request, request.app.state.user_auth.require, authorization)
        result = request.app.state.user_intents.get(identity["address"], intent_id)
        if not result:
            raise HTTPException(404, "User intent not found.")
        return request.app.state.user_intents.view(result)

    @app.get("/api/v1/testnet/inspect")
    async def testnet_inspect(request: Request):
        return await request.app.state.testnet.inspect()

    @app.get("/api/v1/testnet/preflight/{episode_id}")
    async def testnet_preflight(episode_id: str, request: Request):
        ep = request.app.state.runtime.store.get_episode(episode_id)
        if not ep:
            raise HTTPException(404, "Episode not found.")
        report, _ = await request.app.state.testnet.preflight(ep)
        return report

    @app.post("/api/v1/testnet/stage", status_code=201)
    async def testnet_stage(body: StageTestnetInput, request: Request, authorization: str | None = Header(default=None)):
        require_operator(authorization)
        ep = request.app.state.runtime.store.get_episode(body.episode_id)
        if not ep:
            raise HTTPException(404, "Episode not found.")
        try:
            return await request.app.state.testnet.stage(ep)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/testnet/cancel")
    def testnet_cancel(body: StageTestnetInput, request: Request, authorization: str | None = Header(default=None)):
        require_operator(authorization)
        ledger = request.app.state.testnet.ledger
        if not ledger:
            raise HTTPException(409, "Configure both public testnet addresses first.")
        try:
            return ledger.cancel_staged(body.episode_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/operator")
    def operate(action: OperatorAction, request: Request, authorization: str | None = Header(default=None)):
        require_operator(authorization)
        runtime = request.app.state.runtime
        try:
            runtime.store.operate(action.action, runtime.market)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return {"ok": True}

    return app

