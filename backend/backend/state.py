"""Application state assembly. build_state() is the single place where the
engine, the VultrClient, the log, the bus and the service are wired together.

Vultr access only through contracts.vultr.VultrClient:
  * FakeVultr by default and in every test;
  * RealVultr only when VULTR_API_KEY is set — this code never sets it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import sessionmaker

from contracts.vultr import FakeVultr, RealVultr, VultrClient

from .config import Settings, settings_from_env
from .db import make_engine, init_db


@dataclass
class AppState:
    settings: Settings
    engine: object
    sf: sessionmaker
    vultr: VultrClient
    bus: object = field(default=None)
    log: object = field(default=None)
    channel: object = field(default=None)
    service: object = field(default=None)
    app: object = field(default=None)
    fake_twin_tasks: dict = field(default_factory=dict)

    @property
    def is_fake(self) -> bool:
        return isinstance(self.vultr, FakeVultr)

    def close(self) -> None:
        try:
            self.engine.dispose()
        except Exception:
            pass


def make_vultr_client(settings: Settings) -> VultrClient:
    if settings.vultr_api_key:
        return RealVultr(api_key=settings.vultr_api_key)
    return FakeVultr()


def build_state(settings: Settings | None = None) -> AppState:
    from .app import create_app  # local import: app.py imports this module

    settings = settings or settings_from_env()
    engine = make_engine(settings.database_url)
    init_db(engine)
    state = AppState(
        settings=settings,
        engine=engine,
        sf=sessionmaker(engine, expire_on_commit=False),
        vultr=make_vultr_client(settings),
    )
    from .bus import CaseBus
    from .log import CaseLog
    from .service import CaseService
    from .twin import TwinChannel

    state.bus = CaseBus()
    state.log = CaseLog(state.sf, state.bus)
    state.channel = TwinChannel(state.sf, settings)
    state.service = CaseService(state)
    state.app = create_app(state)
    return state


def module_level_app():
    """For `uvicorn backend.app:app` — builds once from env at import."""
    return build_state().app
