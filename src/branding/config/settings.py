from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = ""

    # Meta Graph API
    meta_access_token: str = ""
    meta_ig_user_id: str = ""
    meta_threads_user_id: str = ""
    # 토큰 자동 갱신용 (Meta 앱 자격증명)
    meta_app_id: str = ""
    meta_app_secret: str = ""

    # App
    data_dir: Path = Path("./data")
    brand_config_path: Path = Path("./brand/config.yaml")
    log_level: str = "INFO"

    # AI
    anthropic_model: str = "claude-opus-4-8"

    # Meta / Threads Graph API
    meta_graph_version: str = "v21.0"
    meta_graph_base: str = "https://graph.facebook.com"
    threads_graph_base: str = "https://graph.threads.net"
    threads_publish_delay_seconds: int = 5  # 컨테이너 생성 후 발행까지 대기

    # Scheduler
    publish_poll_minutes: int = 5        # 발행 대기 큐 폴링 주기
    weekly_plan_cron_day: str = "sun"    # 주간 계획 생성 요일
    weekly_plan_cron_hour: int = 18      # 주간 계획 생성 시각 (로컬)
    token_refresh_hour: int = 3          # 토큰 갱신 점검 시각 (로컬, 매일)
    insights_sync_hour: int = 4          # 성과 인사이트 수집 시각 (로컬, 매일)
    scheduler_timezone: str = "Asia/Seoul"

    # 토큰 자동 갱신
    token_refresh_threshold_days: int = 7  # 만료 N일 이내면 갱신

    # 알림
    notify_webhook_url: str = ""         # Slack 호환 incoming webhook URL (비우면 콘솔만)

    # 참여·응대 (계정 활성화)
    comment_poll_minutes: int = 15       # 댓글 수집 주기
    auto_reply: bool = False             # True면 초안을 검토 없이 바로 발행
    golden_hour_minutes: int = 60        # 발행 직후 집중 응대 권장 시간

    @property
    def db_path(self) -> Path:
        return self.data_dir / "content.db"


def get_settings() -> Settings:
    return Settings()
