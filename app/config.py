
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Event and Movie Ticket Booking System"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT Authentication
    SECRET_KEY: str = Field(
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET_KEY")
    )
    ALGORITHM: str = Field(
        default="HS256",
        validation_alias=AliasChoices("ALGORITHM", "JWT_ALGORITHM")
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Booking
    SEAT_LOCK_SECONDS: int = 300
    BOOKING_EXPIRY_MINUTES: int = 10

    # Ticket security
    TICKET_HMAC_SECRET: str

    # Razorpay
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
