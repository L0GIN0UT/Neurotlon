from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEUROTLON_")

    database_url: str = "sqlite:///./neurotlon.db"
