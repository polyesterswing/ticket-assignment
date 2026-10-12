from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://clearfeed:clearfeed@localhost:5432/clearfeed"
    # Max active (not completed) tickets per agent; same for every agent.
    active_ticket_limit: int = Field(default=5, ge=1)
    # How long /assign waits for the per-company lock before returning 503.
    assignment_lock_timeout_seconds: float = Field(default=5.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
