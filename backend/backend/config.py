"""Runtime settings, all from environment variables. No secrets are ever written
to disk: the Vultr key and inference key live in env on the control plane only.

Defaults assume FakeVultr (demo/test) unless VULTR_API_KEY is set; every timeout
then switches to production-scale values via env overrides.
"""
from __future__ import annotations

import os
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEV_APP_SECRET = "body-double-dev-secret"


def default_database_url() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(DATA_DIR / 'bodydouble.db').as_posix()}"


def normalize_db_url(url: str) -> str:
    """Map driverless postgres URLs onto the psycopg3 dialect SQLAlchemy needs.
    Supabase-style `postgres://` and `postgresql://` both work."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+" not in url.split(":", 1)[1]:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


@dataclass(slots=True)
class Settings:
    database_url: str = ""
    vultr_api_key: str | None = None  # never set by this code; read from env only
    operator_password: str | None = None  # required when vultr_api_key enables real mode
    iso_id: str = "iso-bd-forensics"
    twin_plan: str = "vc2-1c-2gb"
    control_url: str | None = "http://10.0.0.1:8000"  # control plane address on investigation VPC
    investigation_vpc_id: str | None = None
    investigation_vpc_subnet: str | None = None
    admin_ip: str = "203.0.113.7"  # the one IP allowed SSH in the quarantine group
    public_url: str = "http://localhost:5173"
    webhook_secret: str | None = None
    inference_key: str | None = field(default=None, repr=False)
    model_planner: str | None = None
    model_solver: str | None = None

    # polling / timeouts (seconds); tests pass small values directly
    poll_interval_s: float = 0.05
    snapshot_timeout_s: float = 900.0
    boot_timeout_s: float = 300.0
    register_timeout_s: float = 300.0
    job_timeout_s: float = 180.0
    case_budget_s: float = 600.0
    twin_job_poll_s: float = 25.0  # GET /twin/jobs/next long-poll window
    heartbeat_ttl_s: float = 90.0

    t1_fallback: bool = False  # create twin from snapshot then attach ISO (no combined call)
    spawn_fake_twin: bool = True  # FakeVultr runs an in-process forensics ISO stand-in
    full_pipeline: bool = True  # POST /cases continues past sealing through report/close

    app_secret: str = DEV_APP_SECRET  # HMAC key for human sessions (prod: env)
    session_ttl_s: int = 86400


def settings_from_env() -> Settings:
    real = bool(os.environ.get("VULTR_API_KEY"))
    settings = Settings(
        database_url=normalize_db_url(os.environ.get("DATABASE_URL") or default_database_url()),
        vultr_api_key=os.environ.get("VULTR_API_KEY") or None,
        operator_password=os.environ.get("BD_OPERATOR_PASSWORD") or None,
        iso_id=os.environ.get("VULTR_ISO_ID", "iso-bd-forensics"),
        twin_plan=os.environ.get("TWIN_PLAN", "vc2-1c-2gb"),
        control_url=(os.environ.get("CONTROL_URL") or
                     (None if real else "http://10.0.0.1:8000")),
        investigation_vpc_id=os.environ.get("BD_VPC_ID") or None,
        investigation_vpc_subnet=os.environ.get("BD_VPC_SUBNET") or None,
        admin_ip=os.environ.get("ADMIN_IP", "203.0.113.7"),
        public_url=os.environ.get("BD_PUBLIC_URL", "http://localhost:5173").rstrip("/"),
        webhook_secret=os.environ.get("BD_WEBHOOK_SECRET") or None,
        inference_key=os.environ.get("VULTR_INFERENCE_KEY") or None,
        model_planner=os.environ.get("BD_MODEL_PLANNER") or None,
        model_solver=os.environ.get("BD_MODEL_SOLVER") or None,
        poll_interval_s=_f("POLL_INTERVAL_S", 5.0 if real else 0.05),
        snapshot_timeout_s=_f("SNAPSHOT_TIMEOUT_S", 900.0),
        boot_timeout_s=_f("BOOT_TIMEOUT_S", 300.0),
        register_timeout_s=_f("REGISTER_TIMEOUT_S", 300.0),
        job_timeout_s=_f("JOB_TIMEOUT_S", 180.0),
        twin_job_poll_s=_f("TWIN_JOB_POLL_S", 25.0),
        heartbeat_ttl_s=_f("HEARTBEAT_TTL_S", 90.0),
        t1_fallback=os.environ.get("T1_FALLBACK", "1" if real else "0").lower() in ("1", "true", "yes"),
        app_secret=os.environ.get("APP_SECRET", DEV_APP_SECRET),
    )
    validate_real_mode(settings)
    return settings


def validate_real_mode(settings: Settings) -> None:
    """Fail closed before real-Vultr mode can mint forgeable sessions."""
    if settings.inference_key and not (
            settings.model_planner and settings.model_solver):
        raise RuntimeError(
            "VULTR_INFERENCE_KEY requires both BD_MODEL_PLANNER and BD_MODEL_SOLVER"
        )
    if not settings.vultr_api_key:
        return
    secret = settings.app_secret or ""
    if (secret == DEV_APP_SECRET or "CHANGE_ME" in secret.upper()
            or len(secret) < 32):
        raise RuntimeError(
            "refusing to start in real-Vultr mode without a strong APP_SECRET "
            "of at least 32 characters"
        )


def validate_investigation_vpc(settings: Settings) -> None:
    if settings.vultr_api_key and not (
            settings.investigation_vpc_id
            and settings.investigation_vpc_subnet
            and settings.control_url):
        raise RuntimeError(
            "real-Vultr mode requires BD_VPC_ID, BD_VPC_SUBNET, and CONTROL_URL"
        )
    if settings.investigation_vpc_id:
        try:
            network = ipaddress.ip_network(settings.investigation_vpc_subnet,
                                           strict=False)
            control_ip = ipaddress.ip_address(urlsplit(settings.control_url).hostname)
        except (TypeError, ValueError) as error:
            raise RuntimeError("BD_VPC_SUBNET and CONTROL_URL must identify the investigation VPC") from error
        if control_ip not in network or control_ip in {
                network.network_address, network.broadcast_address}:
            raise RuntimeError("CONTROL_URL must use a host address inside BD_VPC_SUBNET")


def test_settings(database_url: str) -> Settings:
    """Fast, deterministic settings for tests (FakeVultr, tiny timeouts)."""
    return Settings(
        database_url=database_url,
        poll_interval_s=0.0,
        snapshot_timeout_s=2.0,
        boot_timeout_s=2.0,
        register_timeout_s=2.0,
        job_timeout_s=2.0,
        twin_job_poll_s=0.05,
        heartbeat_ttl_s=30.0,
        full_pipeline=False,
    )
