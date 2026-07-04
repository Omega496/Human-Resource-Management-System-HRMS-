from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    REDIS_URL: str
    JWT_SIGNING_KEY: SecretStr
    JWT_ACCESS_TOKEN_TTL_SECONDS: int = Field(default=600)
    ENVIRONMENT: str = Field(default="production")
    AUTOMATION_CALLBACK_SECRET: SecretStr
    REPLAY_WINDOW_SECONDS: int = Field(default=300)


settings = Settings()
