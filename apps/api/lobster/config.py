from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = "sqlite:///data/lobster.db"
    initial_capital: Decimal = Field(default=Decimal("1000"), gt=0, allow_inf_nan=False)
    market_source: Literal["demo", "hyperliquid", "hyperliquid-testnet"] = "demo"
    agent_provider: Literal["demo", "anthropic"] = "demo"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None
    operator_token: SecretStr | None = None
    worker_enabled: bool = True
    market_poll_seconds: float = Field(default=5, ge=2, le=10)
    review_interval_seconds: float = Field(default=2, ge=0, le=60)
    max_review_calls_per_day: int = Field(default=100, ge=1, le=10000)
    research_enabled: bool = False
    research_interval_seconds: int = Field(default=86400, ge=3600, le=604800)
    research_history_bars: int = Field(default=1440, ge=720, le=4000)
    max_research_calls_per_day: int = Field(default=4, ge=1, le=20)
    treasury_path: str = "data/treasury.sqlite3"
    paper_funding_enabled: bool = True

    @model_validator(mode="after")
    def configured_provider(self):
        if self.agent_provider == "anthropic" and (not self.anthropic_api_key or not self.anthropic_model):
            raise ValueError("Anthropic mode requires ANTHROPIC_API_KEY and ANTHROPIC_MODEL.")
        if self.operator_token and len(self.operator_token.get_secret_value()) < 24:
            raise ValueError("OPERATOR_TOKEN must contain at least 24 characters.")
        return self

