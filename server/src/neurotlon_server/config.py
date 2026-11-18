from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEUROTLON_")

    database_url: str = "sqlite:///./neurotlon.db"
    # Staff sessions live all day (docs/architecture.md, section 5).
    session_ttl_seconds: int = 24 * 60 * 60
