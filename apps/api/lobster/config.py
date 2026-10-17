from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
import re

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
    deployment_mode: Literal["local", "public-single-host"] = "local"
    web_origin: str = "http://127.0.0.1:3000"
    proxy_token: SecretStr | None = None

    @model_validator(mode="after")
    def configured_provider(self):
        if self.agent_provider == "anthropic" and (not self.anthropic_api_key or not self.anthropic_model):
            raise ValueError("Anthropic mode requires ANTHROPIC_API_KEY and ANTHROPIC_MODEL.")
        if self.operator_token and len(self.operator_token.get_secret_value()) < 24:
            raise ValueError("OPERATOR_TOKEN must contain at least 24 characters.")
        origin = urlsplit(self.web_origin)
        if (origin.username or origin.password or origin.path or origin.query or origin.fragment or not origin.hostname
                or self.web_origin != f"{origin.scheme}://{origin.netloc}" or origin.scheme not in {"http", "https"}):
            raise ValueError("A canonical exact web origin is required, without credentials/path/query.")
        if self.deployment_mode == "public-single-host":
            if (origin.scheme != "https" or origin.port not in {None, 443}
                    or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", origin.hostname)
                    or origin.hostname.endswith((".localhost", ".local"))
                    or not self.proxy_token or len(self.proxy_token.get_secret_value()) < 32
                    or not self.operator_token or len(self.operator_token.get_secret_value()) < 32):
                raise ValueError("Public single-host mode requires HTTPS origin and separate strong proxy/operator tokens.")
            if self.proxy_token.get_secret_value() == self.operator_token.get_secret_value(): raise ValueError("Proxy/operator secrets must differ.")
            if not self.database_url.startswith("sqlite:///") or ":memory:" in self.database_url or not self.worker_enabled:
                raise ValueError("Public single-host packaging requires one file-backed SQLite worker owner.")
        elif self.web_origin not in {"http://127.0.0.1:3000", "http://localhost:3000"}:
            raise ValueError("Non-loopback origins require explicit public-single-host mode.")
        return self

