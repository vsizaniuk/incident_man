from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    log_level: Annotated[
        Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], BeforeValidator(str.upper)
    ] = "INFO"

    anthropic_api_key: SecretStr = Field(validation_alias="ANTHROPIC_API_KEY", min_length=1)
    anthropic_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    # conservative bound: the SDK refuses non-streaming requests it expects to run over 10 minutes
    llm_max_tokens: int = Field(default=8000, ge=1, le=16000)
    llm_max_attempts: int = Field(default=3, ge=1)
    context_top_k: int = Field(default=2, ge=1)

    model_config = SettingsConfigDict(env_file="incident_man.env")

settings = Settings()
