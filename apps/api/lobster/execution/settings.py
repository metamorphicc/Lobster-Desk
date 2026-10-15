from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def require_separate_database(paper_url: str, testnet_url: str):
    paper, testnet = make_url(paper_url), make_url(testnet_url)
    same = paper == testnet
    if paper.drivername.startswith("sqlite") and testnet.drivername.startswith("sqlite"):
        if paper.database and testnet.database and ":memory:" not in {paper.database, testnet.database}:
            same = Path(paper.database).resolve() == Path(testnet.database).resolve()
    if same:
        raise ValueError("Use separate database URLs for paper and testnet execution.")


class TestnetSettings(BaseSettings):
    __test__ = False
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HL_TESTNET_", extra="ignore", hide_input_in_errors=True)
    account_address: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    api_wallet_address: str | None = Field(default=None, pattern=r"^0x[0-9a-fA-F]{40}$")
    database_url: str = "sqlite:///data/testnet.db"
    max_entry_notional: Decimal = Field(default=Decimal("50"), ge=10, le=100, allow_inf_nan=False)

    @field_validator("account_address", "api_wallet_address")
    @classmethod
    def nonzero(cls, value):
        if value is not None and int(value, 16) == 0:
            raise ValueError("Use a nonzero wallet address.")
        return value.lower() if value else None


class SignerSettings(BaseSettings):
    # Instantiated ONLY by the separate owner-run CLI, never by FastAPI.
    model_config = SettingsConfigDict(env_file=".env.testnet-signer", env_prefix="HL_SIGNER_", extra="ignore", hide_input_in_errors=True)
    private_key: SecretStr | None = None
    enabled: bool = False
