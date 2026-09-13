from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./helpdesk.db"
    environment: Literal["development", "production"] = "development"
    access_token_expire_minutes: int = Field(480, ge=1, le=10080)
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    max_upload_bytes: int = Field(10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @model_validator(mode="after")
    def production(self):
        self.cors_origins = ",".join(origin.strip() for origin in self.cors_origins.split(","))
        if self.environment == "production" and (
            not self.cookie_secure or not self.database_url.startswith("postgresql")
        ):
            raise ValueError("Production requires PostgreSQL and secure cookies")
        return self


settings = Settings()
