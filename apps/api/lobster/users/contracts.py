from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def nonzero_address(value: str) -> str:
    if int(value, 16) == 0:
        raise ValueError("Use a nonzero account address.")
    return value.lower()


Address = Annotated[str, Field(pattern=r"^0x[0-9a-fA-F]{40}$"), AfterValidator(nonzero_address)]


def fee_percent(tenths_bps: int) -> str:
    return format(Decimal(tenths_bps) / 1000, "f").rstrip("0").rstrip(".") + "%" if tenths_bps else "0%"


class UserTestnetSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="USER_TESTNET_", extra="ignore", hide_input_in_errors=True)
    builder_address: Address | None = None
    builder_fee_tenths_bps: int = Field(default=50, ge=0, le=100)
    financial_enabled: bool = False
    execution_root: str = "data/users-financial"

    @field_validator("builder_address", mode="before")
    @classmethod
    def blank_builder(cls, value): return None if value == "" else value


class UserMainnetSettings(UserTestnetSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="USER_MAINNET_", extra="ignore", hide_input_in_errors=True)
    execution_root: str = "data/users-mainnet"
