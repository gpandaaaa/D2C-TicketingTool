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

    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "itecom.d2c@samsung.com"
    public_origin: str = "https://107.108.42.60:5050"

    @model_validator(mode="after")
    def production(self):
        self.cors_origins = ",".join(origin.strip() for origin in self.cors_origins.split(","))
        if self.environment == "production" and (
            not self.cookie_secure or not self.database_url.startswith("postgresql")
        ):
            raise ValueError("Production requires PostgreSQL and secure cookies")
        if self.smtp_enabled:
            if (
                not self.smtp_host
                or "@" not in self.smtp_from
                or any(c in self.smtp_from for c in "\r\n")
            ):
                raise ValueError("SMTP requires a host and valid sender")
            if not self.public_origin.startswith("https://"):
                raise ValueError("Email links require an HTTPS public origin")
            if bool(self.smtp_username) != bool(self.smtp_password):
                raise ValueError("SMTP username and password must be configured together")
            if self.smtp_username and self.smtp_security == "none":
                raise ValueError("SMTP authentication requires TLS")
        return self


settings = Settings()
