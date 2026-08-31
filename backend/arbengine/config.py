"""Configuration.

Values come from environment variables / a .env file. Nothing secret is ever
hard-coded (Part II, §3.3). Every threshold in here maps to a concept from the
theory volume; the section reference is given in the comment.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
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
    # Shared secret for the endpoints that change something: config, scanner
    # control, placements, settlements. Sent as X-API-Key.
    #
    # Blank is allowed ONLY while bound to loopback, which is the default and
    # the deployment this tool is actually built for. Binding to any other
    # interface without a key is refused at startup rather than quietly serving
    # bankroll settings and a stop button to the network.
    api_key: str = ""

    # ------------------------------------------------------------ data feeds
    # Polymarket and Kalshi market data are public and need no credentials.
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    polymarket_clob_url: str = "https://clob.polymarket.com"
    kalshi_api_url: str = "https://api.elections.kalshi.com/trade-api/v2"

    enable_polymarket: bool = True
    enable_kalshi: bool = True

    # UK/EU exchange zone. Smarkets publishes market data without credentials;
    # Betfair needs an application key and a session token and stays dark
    # without them.
    smarkets_api_url: str = "https://api.smarkets.com/v3"
    betfair_api_url: str = "https://api.betfair.com/exchange/betting/json-rpc/v1"
    betfair_login_url: str = "https://identitysso.betfair.com/api/login"
    # Smarkets is on by default because its data needs no credentials and the
    # zone is worthless with one venue in it. Betfair is off because it cannot
    # read anything without a key, and a source that always fails is noise.
    enable_smarkets: bool = True
    enable_betfair: bool = False
    betfair_app_key: str = ""
    betfair_session_token: str = ""
    betfair_username: str = ""
    betfair_password: str = ""

    # Which Smarkets event types to pull. Three-way football and politics
    # markets are the useful ones: their outcomes genuinely partition the
    # sample space, which is what the Dutch-book detector needs.
    smarkets_event_types: str = "football_match,politics,politics_outright"
    smarkets_max_events: int = 60

    # Betfair event type ids: 1 = Soccer, 2378961 = Politics.
    betfair_event_type_ids: str = "1,2378961"
    betfair_max_markets: int = 60

    # The Odds API is optional; without a key the sportsbook source stays dark.
    odds_api_key: str = ""
    odds_api_url: str = "https://api.the-odds-api.com/v4"
    # Every bookmaker region the key is entitled to. Regions are the single
    # biggest lever on how many cross-book arbitrages exist at all: an edge
    # appears when two books disagree, and four regions of books disagree far
    # more often than one does.
    odds_api_regions: str = "us,us2,uk,eu,au"
    # Blank means "every sport The Odds API reports as in season", discovered
    # per cycle through the free /sports endpoint. A comma-separated list here
    # pins it to specific sport keys instead.
    odds_api_sports: str = ""
    # Outright winner, handicap and over/under lines. Handicaps and totals are
    # two-way markets, so they arbitrage exactly like a moneyline -- and there
    # are far more of them, because every book prices its own line.
    odds_api_markets: str = "h2h,spreads,totals"
    # Sport groups to consider when discovering in-season sports. Sports only:
    # politics and entertainment novelty markets are priced by the same books
    # but settle on rules that do not survive cross-book comparison.
    odds_api_groups: str = (
        "American Football,Basketball,Baseball,Ice Hockey,Soccer,Tennis,"
        "Mixed Martial Arts,Boxing,Cricket,Rugby League,Rugby Union,"
        "Aussie Rules,Golf,Lacrosse"
    )
    # Guard on the discovery path. Each sport costs
    # len(markets) * len(regions) credits per cycle, so an unbounded in-season
    # list on a busy Saturday will empty a monthly quota in an afternoon.
    odds_api_max_sports: int = 12
    # The Odds API publishes prices, not books: there is no depth and no stake
    # limit in the payload, so the capacity of a sportsbook leg is UNKNOWN
    # rather than zero. The sizer refuses a leg with no capacity, which is the
    # right rule -- so the assumption has to be stated explicitly here instead
    # of arriving by accident as `size_available = 0`. This is the most one leg
    # at a single book will be sized at; it is a risk limit you own, not a
    # number the feed told us. Set it to 0 to disable sportsbook sizing.
    sportsbook_assumed_stake_usd: float = 250.0

    # Only surface opportunities that resolve soon.
    #
    # An arbitrage locks capital on both legs until settlement, so a 2% edge on
    # a market resolving in nine months is a worse annualised return than a
    # savings account, and it carries nine months of rule-change and
    # account-closure risk on top (Part I s8.2). Short-dated sport is where the
    # edge is actually collectable. Set to 0 to disable the window.
    max_hours_to_start: float = 72.0

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

    # ------------------------------------------------------- execution zones
    # A cross-venue arb is only real if one operator can place both legs. Venues
    # are grouped into zones (see venues.py) that share a currency, a
    # settlement convention and a plausible account footprint; pairing runs
    # inside a zone and never across one. Turning this off will surface
    # Betfair-vs-Kalshi style pairs whose "hedge" needs accounts in two
    # jurisdictions and carries an unhedged FX leg.
    enforce_zone_pairing: bool = True
    # ISO-3166 alpha-2 of where you actually trade from. Blank means "do not
    # filter by location"; set it and the engine hides anything you could not
    # legitimately place from there.
    operator_jurisdiction: str = ""
    # Zones to scan, comma-separated. Blank means every zone with an enabled
    # source behind it.
    active_zones: str = ""

    # Nothing beyond this is worth an order-book fetch, but books within it are
    # worth WATCHING: they are the near misses the operator wants to see when
    # no arbitrage exists, and the evidence that the engine is doing work.
    near_miss_slack: float = 0.02
    max_near_misses: int = 40

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
    # Per-exchange commission on net winnings. Both are the published standard
    # rate; Betfair's drops with the loyalty discount and Smarkets' is flat.
    smarkets_commission: float = 0.02
    betfair_commission: float = 0.05

    # --------------------------------------------------------------- scanner
    poll_interval_seconds: int = 45

    # How long a quote stays evidence.
    #
    # A price is a fact about the book at the instant its venue published it,
    # and it decays from there. This is the horizon past which the engine will
    # not assert an opportunity still holds -- it drives `expires_at` and so the
    # countdown the operator sees. Ten minutes matches the STALE_QUOTE risk
    # flag, so the point at which a quote is flagged as possibly-moved is the
    # same point at which the opportunity built on it expires.
    stale_quote_seconds: float = 600.0
    dedup_window_seconds: int = 300
    autostart_scanner: bool = True
    demo_mode: bool = False            # serve deterministic fixtures, no network
    # How long an opportunity is held after the last cycle that could actually
    # re-price it. Only reached when a venue stays unreachable: a venue that
    # answers retires its own opportunities immediately. Roughly six missed
    # cycles at the default interval.
    stale_arb_seconds: int = 300

    # Circuit breaker (Part II §16.4).
    breaker_threshold: int = 25
    breaker_window_seconds: int = 60
    breaker_min_margin: float = 0.10

    # --------------------------------------------------------- correlation arb
    # See correlation_arb.py. Pairs are configured via /api/correlation/pairs
    # (there is no automatic discovery of which markets share a joint contract).
    enable_correlation_arb: bool = True
    # Fraction of full Kelly actually staked -- Part I §7.3's fraction applied
    # to a bet with real variance, same conservative default as /api/calc/kelly.
    correlation_kelly_fraction: float = 0.25
    # Deadband below which a mispricing is not worth trading; a pair can
    # override this with its own min_edge.
    correlation_min_edge: float = 0.02
    # Below this many historical outcome pairs, rho_prior is too noisy to trust
    # and the opportunity is scored down rather than hidden outright.
    correlation_min_rho_prior_samples: int = 5

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
    def auth_required(self) -> bool:
        return bool(self.api_key)

    @property
    def binds_loopback(self) -> bool:
        return self.host in ("127.0.0.1", "::1", "localhost")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def odds_api_sport_list(self) -> list[str]:
        return [s.strip() for s in self.odds_api_sports.split(",") if s.strip()]

    @property
    def odds_api_market_list(self) -> list[str]:
        return [m.strip() for m in self.odds_api_markets.split(",") if m.strip()]

    @property
    def odds_api_group_set(self) -> set[str]:
        return {g.strip() for g in self.odds_api_groups.split(",") if g.strip()}

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def odds_api_enabled(self) -> bool:
        return bool(self.odds_api_key)

    @property
    def smarkets_event_type_list(self) -> list[str]:
        return [s.strip() for s in self.smarkets_event_types.split(",") if s.strip()]

    @property
    def betfair_event_type_id_list(self) -> list[str]:
        return [s.strip() for s in self.betfair_event_type_ids.split(",") if s.strip()]

    @property
    def betfair_enabled(self) -> bool:
        """Betfair needs an app key plus either a session token or a login."""
        if not (self.enable_betfair and self.betfair_app_key):
            return False
        return bool(
            self.betfair_session_token
            or (self.betfair_username and self.betfair_password)
        )

    @property
    def active_zone_list(self) -> list[str]:
        return [z.strip() for z in self.active_zones.split(",") if z.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
