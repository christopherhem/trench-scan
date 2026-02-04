from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Database
    database_url: str = Field(default="sqlite:///./trench_scan.db")

    # Telegram Bot
    telegram_bot_token: Optional[str] = Field(default=None)
    telegram_chat_id: Optional[str] = Field(default=None)

    # Discord Bot
    discord_bot_token: Optional[str] = Field(default=None)
    discord_channel_id: Optional[str] = Field(default=None)

    # RapidAPI (Twitter scraping)
    rapidapi_key: Optional[str] = Field(default=None)
    rapidapi_host: str = Field(default="twitterapi-cheap.p.rapidapi.com")

    # Scraper Settings
    scrape_interval_minutes: int = Field(default=5)
    min_mentions_threshold: int = Field(default=3)
    trending_velocity_threshold: int = Field(default=5)

    # Search Keywords for crypto/memecoin tweets
    search_keywords: list[str] = Field(
        default=[
            "$",  # Ticker symbol prefix
            "memecoin",
            "100x",
            "1000x",
            "moon",
            "gem",
            "degen",
            "ape",
            "solana",
            "sol",
            "eth",
            "base",
        ]
    )

    # Accounts to monitor (crypto influencers, alpha callers)
    watch_accounts: list[str] = Field(default=[])

    # Dashboard
    dashboard_host: str = Field(default="127.0.0.1")
    dashboard_port: int = Field(default=8000)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
