"""Infrastructure configuration.

Environment variables live ONLY in the infrastructure layer, per the
architecture contract. Domain and application never read env vars.

All secret-bearing values are typed as `SecretStr` so they render as
`**********` in reprs, logs, and tracebacks instead of their raw value.
Callers must explicitly call `.get_secret_value()` to obtain the real
value, and should only ever do so right at the point where a third-party
client requires a plain string.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when required configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "ApplyFlow"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True

    # Database (point this at Supabase's connection string outside of
    # local development — see README "Provisioning the database & auth".)
    #
    # A `SecretStr`, like the API keys below, because a connection string *is* a
    # credential: the password sits in its userinfo. It was a plain `str` until
    # the Epic 07 hardening pass, which meant any `repr(settings)` — a debug
    # dump, a `print`, an exception rendering its context — spelled out the
    # database password. The log scrubber now redacts URL userinfo wherever it
    # appears (see `pii_redaction._URL_CREDENTIAL_RE`), so this is the second
    # layer rather than the only one; both are cheap and they fail
    # independently.
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://applyflow:applyflow@localhost:5432/applyflow"
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    # Supabase (database host + auth provider)
    supabase_url: str = ""
    supabase_jwt_secret: SecretStr = SecretStr("")

    # Encryption at rest for sensitive fields (Epic 07 —
    # src/infrastructure/security/). Contact details, citizenship, work
    # authorization, and EEO self-identification are encrypted in the columns
    # that hold them; these are the only two places the keys come from.
    #
    # `field_encryption_keys` is a comma-separated list of `key_id:base64_key`
    # pairs, MOST RECENT FIRST — the first entry signs new writes and the rest
    # stay readable, which is what makes a key rotation possible without
    # rewriting every row. Each key is 32 bytes (AES-256), base64-encoded:
    # `openssl rand -base64 32`. See
    # src/infrastructure/security/encryption_keyring.py for the full format.
    #
    # `field_blind_index_key` keys the deterministic digest that keeps
    # `job_applications.candidate_email` searchable while encrypted. It is
    # deliberately NOT part of the rotating keyring above: rotating it
    # invalidates every digest already stored, so it is a data migration rather
    # than a config change.
    #
    # Both are empty by default, which falls back to an in-repository
    # development key (see `EncryptionKeyring.for_development`) so a fresh
    # clone runs. The validator below refuses that fallback outside
    # `development`.
    field_encryption_keys: SecretStr = SecretStr("")
    field_blind_index_key: SecretStr = SecretStr("")

    # Redis / Celery. `SecretStr` for the same reason as `database_url`: a
    # managed Redis or broker URL carries its password inline
    # (`redis://:pw@host:6379/0`), and these three are the URLs most likely to
    # end up in a worker's startup banner.
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    celery_broker_url: SecretStr = SecretStr("redis://localhost:6379/1")
    celery_result_backend: SecretStr = SecretStr("redis://localhost:6379/2")

    # LLM / LangChain (OpenAI — used by LangChainResumeAnalyzer)
    openai_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    # Embeddings (part of the Epic 00 LLM layer, see OpenAiEmbeddingClient).
    # Anthropic has no embeddings endpoint, so this reuses the OpenAI
    # credential above rather than the Anthropic one below.
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic — the ONLY LLM credential path (see AnthropicLlmClient).
    # Must be a pay-as-you-go API key from console.anthropic.com; never a
    # claude.ai subscription/session credential.
    anthropic_api_key: SecretStr = SecretStr("")
    # Model routing: callers pick a LlmTaskType, never a model. These two
    # settings are the only override point for which concrete model backs
    # each cost tier — see AnthropicLlmClient and TASK_TYPE_TIERS.
    anthropic_model_cheap: str = "claude-haiku-4-5-20251001"
    anthropic_model_strong: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 1024
    # Retry/backoff for transient errors (rate limits, timeouts, 5xxs) — see
    # AnthropicLlmClient. `anthropic_max_retries` is retries AFTER the initial
    # attempt, so total attempts = anthropic_max_retries + 1. Delay doubles
    # each attempt starting at the base and is capped at the max.
    anthropic_max_retries: int = 3
    anthropic_retry_base_delay_seconds: float = 1.0
    anthropic_retry_max_delay_seconds: float = 20.0

    # Resume file storage (src/infrastructure/storage/local_file_storage.py).
    # Raw resume bytes are written here, addressed only by an opaque
    # server-generated key — never a candidate's filename or email — so
    # this directory's contents and any path logged from it carry no PII.
    resume_storage_dir: str = "./var/resumes"

    # Job aggregator integration — Adzuna (see
    # src/infrastructure/job_aggregators/adzuna_client.py). Adzuna
    # authenticates with a pair of credentials: `app_id` identifies the
    # calling application (not secret — Adzuna's own docs show it in
    # sample URLs) and `app_key` is the actual secret, reusing the generic
    # `job_aggregator_api_key` name so other aggregators can slot into the
    # same settings later.
    job_aggregator_app_id: str = ""
    job_aggregator_api_key: SecretStr = SecretStr("")
    job_aggregator_base_url: str = "https://api.adzuna.com/v1/api/jobs"
    job_aggregator_country: str = "us"
    job_aggregator_results_per_page: int = 50
    # Retry/backoff for transient errors (rate limits, timeouts, 5xxs) —
    # same shape as the Anthropic settings above. Total attempts =
    # job_aggregator_max_retries + 1.
    job_aggregator_max_retries: int = 3
    job_aggregator_retry_base_delay_seconds: float = 1.0
    job_aggregator_retry_max_delay_seconds: float = 20.0

    # Search API integration — Tavily
    # (src/infrastructure/search/tavily_search_client.py). Used only to
    # LOCATE which ATS board (Greenhouse/Lever/Ashby) a company posts
    # through (see AtsListingResolver) — never to answer a listing's
    # apply URL/description directly. The free tier is a tight daily quota
    # (`search_api_daily_quota`), so a discovered board is cached
    # permanently by company (ResolvedCompanyBoardRepository — the same
    # company's board is never searched for twice) and the quota is
    # tracked in Redis (DailySearchQuota) so exhausting it degrades
    # ingestion gracefully instead of failing it.
    search_api_key: SecretStr = SecretStr("")
    search_api_base_url: str = "https://api.tavily.com/search"
    search_api_daily_quota: int = 100
    search_api_max_retries: int = 3
    search_api_retry_base_delay_seconds: float = 1.0
    search_api_retry_max_delay_seconds: float = 20.0
    # How many ranked search results AtsListingResolver scans past a
    # company's marketing homepage looking for the first one that is
    # actually a recognized ATS board, before giving up on that company.
    search_api_board_locate_result_count: int = 5

    # ATS board integration — Greenhouse/Lever/Ashby public job-board APIs
    # (src/infrastructure/ats_boards/). These are unauthenticated public
    # feeds, so there are no credentials to configure here — only
    # retry/backoff, same shape as the other HTTP integrations above.
    ats_board_max_retries: int = 3
    ats_board_retry_base_delay_seconds: float = 1.0
    ats_board_retry_max_delay_seconds: float = 20.0

    # Stale-posting / dead-apply-link detection
    # (src/application/use_cases/detect_stale_job_postings.py,
    # src/infrastructure/link_checking/http_apply_url_checker.py). Runs on
    # a schedule via Celery beat (see celery_app.py) to keep job_postings'
    # active set free of postings too old to still be open, or whose
    # apply link no longer resolves.
    apply_url_check_timeout_seconds: float = 10.0
    # A posting is presumed expired this many days after posted_at (or
    # created_at, absent one), absent any other signal.
    stale_posting_after_days: int = 45
    # How many days may pass before an ACTIVE posting is due another
    # reachability check.
    stale_posting_recheck_after_days: int = 3
    # Consecutive ambiguous (timeout/5xx/connection-error) reachability
    # failures required before flagging DEAD_LINK. A single unambiguous
    # 404/410 always flags immediately, bypassing this threshold.
    stale_posting_dead_link_after_failures: int = 3
    # How many due postings one sweep pass processes — bounds a single
    # scheduled run's work (and outbound HTTP calls) on an unbounded table.
    stale_posting_sweep_batch_size: int = 200

    # Job requirements extraction (Epic 03 —
    # src/application/use_cases/extract_job_requirements.py,
    # src/infrastructure/llm/llm_job_requirements_extractor.py). Runs on a
    # schedule via Celery beat (see celery_app.py) to keep newly ingested
    # postings' `requirements` populated. Bounds one scheduled run's work
    # (and LLM calls) on an unbounded table, same rationale as the
    # stale-posting sweep above.
    job_requirements_sweep_batch_size: int = 200

    # Browser automation for application portals (Epic 05 —
    # src/infrastructure/browser_automation/). Drives a real Chromium over
    # a posting's apply_url to read and fill its form. Unlike every other
    # integration above there is no API and no credential — the "endpoint"
    # is whatever HTML the portal serves — so what's tunable here is the
    # browser itself and how long it's given.
    #
    # Requires the Chromium build Playwright expects to be present on the
    # host (`playwright install chromium`); the harness says so explicitly
    # if it isn't, rather than failing at launch with a driver error.
    browser_headless: bool = True
    # How long one navigation attempt gets. Portals are slower than APIs:
    # an ATS form is typically several redirects plus a JS app boot.
    browser_navigation_timeout_seconds: float = 30.0
    # How long any single field interaction gets (locating the element,
    # writing the value).
    browser_action_timeout_seconds: float = 10.0
    # After load, how long to wait for in-flight requests to go quiet so a
    # JS-rendered form has actually painted its fields. Best-effort —
    # expiring here is normal on pages that poll, and never an error.
    browser_settle_timeout_seconds: float = 5.0
    # How long read_fields() keeps re-checking a page that has presented
    # no fillable field yet, before accepting that it has none. Covers a
    # form that mounts after first paint.
    browser_field_wait_timeout_seconds: float = 5.0
    # Retry/backoff for navigation only, same shape as the HTTP
    # integrations above (total attempts = max_retries + 1). A browser
    # page load has many more transient failure modes than an API call, so
    # unlike HttpApplyUrlChecker one retry is worth it here; 4xx responses
    # other than 429 are never retried, since the portal answered.
    browser_navigation_max_retries: int = 1
    browser_navigation_retry_base_delay_seconds: float = 1.0
    browser_navigation_retry_max_delay_seconds: float = 8.0
    # Presented viewport. Some portals render a different (or no) form
    # below a mobile breakpoint, so this stays comfortably desktop-sized.
    browser_viewport_width: int = 1280
    browser_viewport_height: int = 900
    # Overrides the browser's own user agent when non-empty. Left empty by
    # default: Playwright's real Chromium UA is accurate, and claiming to
    # be something else is how you end up debugging a portal that served a
    # different page than the one you tested against.
    browser_user_agent: str = ""
    # Extra Chromium launch flags. Needed in containers, which typically
    # cannot use Chromium's sandbox (`["--no-sandbox"]`); set via JSON in
    # the environment, e.g. BROWSER_LAUNCH_ARGS=["--no-sandbox"].
    browser_launch_args: tuple[str, ...] = ()

    # A filled application form stays open in a browser while the candidate
    # reviews it and decides whether to submit (see
    # `ApplicationReviewSessions`). These two bound what that costs: how long
    # one abandoned review holds a browser context, and how many this
    # process holds at once. Both are resource ceilings rather than product
    # limits — raising them raises this process's memory floor, and the
    # sessions are process-local, so an API served by several workers needs
    # sticky routing for the review flow.
    autofill_review_ttl_seconds: float = 900.0
    autofill_max_parked_reviews: int = 8

    # The privacy notice this deployment is serving. Stamped onto every consent
    # decision, which is what makes the consent demonstrably *informed*: consent
    # is only valid for what the user was actually told, so a materially changed
    # notice invalidates consent collected under the old one and this is what
    # makes "who has to be re-asked?" a query rather than a guess (GDPR Art.
    # 7(1) — see `ConsentDecision`).
    #
    # Configuration rather than a constant because it changes with the notice,
    # not with a release — and it comes from here rather than from the request
    # body because a client that could assert which notice it had shown could
    # record consent against a notice the user never saw.
    #
    # Date-stamped by convention: it has to sort and it has to be recognizable
    # in a ledger row years later. Bump it when the notice changes materially.
    privacy_policy_version: str = "2026-08-03"

    @model_validator(mode="after")
    def _require_secrets_outside_development(self) -> Settings:
        if self.environment == "development":
            return self
        if not self.openai_api_key.get_secret_value():
            raise ValueError(
                f"OPENAI_API_KEY is required when ENVIRONMENT is '{self.environment}'."
            )
        if not self.supabase_jwt_secret.get_secret_value():
            raise ValueError(
                "SUPABASE_JWT_SECRET is required when ENVIRONMENT is "
                f"'{self.environment}'."
            )
        if not self.anthropic_api_key.get_secret_value():
            raise ValueError(
                "ANTHROPIC_API_KEY is required when ENVIRONMENT is "
                f"'{self.environment}'."
            )
        # Refused rather than defaulted, unlike most settings here. The
        # fallback for an unset encryption key is a key committed to this
        # repository (see `EncryptionKeyring.for_development`), so booting
        # without one outside development would encrypt a real candidate's
        # citizenship and EEO answers under a public key — worse than not
        # booting, and invisible afterwards.
        if not self.field_encryption_keys.get_secret_value().strip():
            raise ValueError(
                "FIELD_ENCRYPTION_KEYS is required when ENVIRONMENT is "
                f"'{self.environment}' — sensitive fields would otherwise be "
                "encrypted under the in-repository development key. Generate "
                "one with `openssl rand -base64 32` and set it as "
                "'<key_id>:<base64_key>'."
            )
        if not self.field_blind_index_key.get_secret_value().strip():
            raise ValueError(
                "FIELD_BLIND_INDEX_KEY is required when ENVIRONMENT is "
                f"'{self.environment}' — see FIELD_ENCRYPTION_KEYS above for "
                "why the development fallback is refused here."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc
