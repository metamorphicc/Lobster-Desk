"""Generate synthetic client contracts from the actual Python/SDK implementation."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from lobster.execution.contracts import fingerprint
from lobster.store import Store
from lobster.users.financial import UserFinancial, FinancialRequest
import lobster.users.financial as module
from lobster.users.intents import ProfileInput, UserIntents
from lobster.users.orders import UserPlans

now = datetime(2026, 10, 17, tzinfo=timezone.utc)
module.utcnow = lambda: now
profile = json.loads(Path("apps/web/tests/fixtures/user-consent.json").read_text())["context"]["profile"]
owner = profile["address"]
with TemporaryDirectory(prefix="lobster-financial-fixture-") as temp:
    store = Store("sqlite:///" + (Path(temp)/"fixture.db").as_posix())
    try:
        intents, plans = UserIntents(store), UserPlans(store)
        intents.configure(ProfileInput(**{k: v for k, v in profile.items() if k != "network"}))
        plan = {"id": "1"*32, "address": owner, "network": "testnet", "episode_id": "public-fixture-episode",
            "expires_at": (now+timedelta(seconds=30)).isoformat(), "fees": {"builder_address": profile["builder"], "builder_fee_tenths_bps": profile["fee_tenths_bps"]},
            "executable": False, "submitted": False, "signed": False, "nonce_reserved": False, "order_submission_enabled": False, "fee_collection_enabled": False}
        plan["plan_hash"] = fingerprint(plan)
        plans.save(owner, "public-client-fixture", plan)
        service = UserFinancial(store, intents, plans)
        jobs = {kind: service.view(service.prepare(owner, FinancialRequest(kind=kind, plan_id=plan["id"] if kind=="trade" else None), "public-fixture-"+kind))
            for kind in ("agent", "builder", "revoke_builder", "trade")}
        result = {"fixture": "Synthetic unfunded Python/SDK contracts. No signatures or financial HTTP.", "profile": profile, "plan": plan,
            "jobs": jobs, "context": service.context(owner, Path(temp)/"absent-execution", True)}
        Path("apps/web/tests/fixtures/user-financial.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    finally: store.engine.dispose()
