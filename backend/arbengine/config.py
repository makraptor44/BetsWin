"""Configuration.

Values come from environment variables / a .env file. Nothing secret is ever
hard-coded (Part II, §3.3). Every threshold in here maps to a concept from the
theory volume; the section reference is given in the comment.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- server
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ------------------------------------------------------------ data feeds
    # Polymarket and Kalshi market data are public and need no credentials.
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    kalshi_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"

    enable_polymarket: bool = True
    enable_kalshi: bool = True

    # The Odds API is optional; without a key the sportsbook source stays dark.
    odds_api_key: str = ""
    odds_api_url: str = "https://api.the-odds-api.com/v4"
    odds_api_regions: str = "us,us2"
    odds_api_sports: str = (
        "americanfootball_nfl,basketball_nba,baseball_mlb,icehockey_nhl"
    )

    # How much of each venue to pull per cycle.
    polymarket_page_limit: int = 100
    polymarket_max_pages: int = 15
    kalshi_page_limit: int = 200
    kalshi_max_pages: int = 8

    # Only consider markets with at least this much resting liquidity / volume.
    min_market_volume_usd: float = 5_000.0
    min_market_liquidity_usd: float = 500.0

    # ---------------------------------------------------- detection thresholds
    # Part I §4.4: arb exists iff combined book B < 1; margin m = 1/B - 1.
    min_arb_margin: float = 0.004      # 0.4% floor — below this, fees eat it
    max_arb_margin: float = 0.25       # above this it is almost certainly bad data
    suspect_margin: float = 0.05       # Part I §5.3: >5% is a red flag
    min_confidence: int = 25           # 0-100 quality score floor for surfacing

    # Cross-venue title matching (Part II §6.1).
    fuzzy_match_threshold: int = 82

    # -------------------------------------------------------- stake / bankroll
    bankroll: float = 10_000.0
    default_stake: float = 500.0       # target turnover per opportunity
    max_stake_fraction_per_event: float = 0.05   # Part I §7.4: cap 2-5%
    min_stake_per_leg: float = 5.0
    min_total_stake: float = 20.0      # Part II §8.2
    stake_step: float = 0.01

    # ------------------------------------------------------------------ fees
    # Kalshi: fee = ceil(0.07 * C * P * (1-P) * 100) cents  (per order).
    kalshi_fee_coefficient: float = 0.07
    kalshi_maker_fee_coefficient: float = 0.0025
    # Polymarket CLOB currently charges no taker fee; gas is paid by the relayer.
    polymarket_fee_bps: float = 0.0
    polymarket_gas_cost_usd: float = 0.0
    # Exchange commission for back/lay maths (Part I §6.1).
    exchange_commission: float = 0.02

    # --------------------------------------------------------------- scanner
    poll_interval_seconds: int = 45
    dedup_window_seconds: int = 300
    autostart_scanner: bool = True
    demo_mode: bool = False            # serve deterministic fixtures, no network

    # Circuit breaker (Part II §16.4).
    breaker_threshold: int = 25
    breaker_window_seconds: int = 60
    breaker_min_margin: float = 0.10

    # ---------------------------------------------------------------- storage
    database_path: str = "data/betswin.db"
    retention_days: int = 30

    # --------------------------------------------------------------- alerting
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_min_margin: float = 0.015
    alert_min_confidence: int = 55

    # ---------------------------------------------------------- void modelling
    # Part I §13.3: E[pi] ~= (1-v)*m - v*L
    assumed_void_rate: float = 0.02
    assumed_void_loss: float = 0.30

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def odds_api_sport_list(self) -> list[str]:
        return [s.strip() for s in self.odds_api_sports.split(",") if s.strip()]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def odds_api_enabled(self) -> bool:
        return bool(self.odds_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
