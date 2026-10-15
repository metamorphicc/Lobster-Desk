"""One durable transition at a time. The worker can resume after a restart."""

from datetime import datetime
import logging

from .agents import Reviewer
from .domain import PitchInput, Snapshot, utcnow
from .store import Store

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "analyzing", "risk_check", "capital_check"}


class Pipeline:
    def __init__(self, store: Store, reviewer: Reviewer):
        self.store = store
        self.reviewer = reviewer

    async def step(self, market: Snapshot | None):
        state = self.store.state(market)
        pending = sorted((ep for ep in state["episodes"] if ep["status"] in ACTIVE), key=lambda ep: ep["created_at"])
        if not pending:
            return
        ep = pending[0]
        status = ep["status"]
        if utcnow() >= datetime.fromisoformat(ep["expires_at"]):
            self.store.advance(ep["id"], status, "expired", "system", "Proposal expired before review completed.")
            return
        if not market or not -2 <= (utcnow() - market.timestamp).total_seconds() <= self.store.policy.max_data_age_seconds:
            return  # No model spending or approvals without current market data.
        if status == "queued":
            self.store.advance(ep["id"], status, "analyzing", "analyst", "Reading the setup against the market snapshot.",
                               {"snapshot": market.model_dump(mode="json")})
            return
        try:
            if status in {"analyzing", "risk_check"}:
                role = "analyst" if status == "analyzing" else "risk"
                attempts = ep.get("review_attempts", {})
                if attempts.get(role, 0):
                    self.store.advance(ep["id"], status, "rejected", "system",
                        "A previous model call was interrupted. No automatic paid retry was made.")
                    return
                self.store.advance(ep["id"], status, status, role, f"Starting the {role} review.",
                    {"review_attempts": attempts | {role: 1}})
                outcomes = [{"status": e["status"], "reason": e["reason"]} for e in state["episodes"]
                            if e["status"] in {"closed", "rejected"}][:5]
                review, metadata = await self.reviewer.review(role, PitchInput.model_validate(ep["pitch"]),
                    Snapshot.model_validate(ep["snapshot"]), outcomes)
                reviews = ep["reviews"] | {role: review.model_dump(mode="json") | {"metadata": metadata}}
                next_status = ("risk_check" if role == "analyst" else "capital_check") if review.verdict == "approve" else "rejected"
                self.store.advance(ep["id"], status, next_status, role, review.summary, {"reviews": reviews})
            elif status == "capital_check":
                self.store.approve(ep["id"], market)
        except Exception as error:
            # Do not expose response bodies/headers (could contain credentials) to the public journal.
            logger.warning("Review failed for %s (%s)", ep["id"], type(error).__name__)
            self.store.advance(ep["id"], status, "rejected", "system",
                "Review could not be validated. No trade was authorized; submit a new pitch to retry.")

