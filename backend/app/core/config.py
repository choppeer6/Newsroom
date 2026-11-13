from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Newsroom"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api/news"
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "mysql+asyncmy://newsroom:newsroom@localhost:3306/newsroom"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o"
    search_provider: str = "tavily"
    search_api_key: SecretStr | None = None

    max_revision_rounds: int = Field(default=2, ge=0)
    max_concurrent_tasks: int = Field(default=10, ge=1)

    @field_validator("llm_api_key", "search_api_key", mode="before")
    @classmethod
    def _blank_secret_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
