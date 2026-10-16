"""Validate the local paper preset without exposing credentials or calling a model."""
from lobster.config import Settings

if __name__ == "__main__":
    try:
        config = Settings()
        if config.agent_provider != "anthropic" or not config.research_enabled or not config.worker_enabled:
            raise ValueError()
        print("Agent configuration valid: Anthropic research + setup reviews; paper execution only.")
        print(f"Model: {config.anthropic_model}; data: {config.market_source}; history: {config.research_history_bars} hours.")
        print(f"Daily call ceilings: research {config.max_research_calls_per_day}, reviews {config.max_review_calls_per_day}. These are not dollar spending caps.")
        print("Model key present. Provider access/billing is unverified until an actual request succeeds. No wallet key is needed.")
    except Exception:
        raise SystemExit("Agent configuration incomplete. Fill ANTHROPIC_API_KEY in .env.agents; keep the prepared provider/model/worker settings. No credential values were printed.") from None
