"""B1: BD_REAL_MODE is the gate for real-Vultr mode.

* unset (default): existing fake behavior untouched — FakeVultr even when
  VULTR_API_KEY happens to be exported.
* set without a key: fail closed at startup (RuntimeError), no partial mode.
* set with a key: every instance/snapshot/VPC/ISO call goes through
  RealVultr. The client is only *constructed* here — no live calls in tests.
"""
from __future__ import annotations

import pytest

from backend.config import Settings, settings_from_env, validate_real_mode
from backend.state import make_vultr_client
from contracts.vultr import FakeVultr, RealVultr

STRONG_SECRET = "y" * 40


def real_mode_env(monkeypatch, mode: str | None = None):
    """Env for a validate-clean settings_from_env() run with a (fake) key."""
    monkeypatch.setenv("VULTR_API_KEY", "test-key")
    monkeypatch.setenv("APP_SECRET", STRONG_SECRET)
    monkeypatch.setenv("BD_OPERATOR_PASSWORD", "operator-password-12")
    if mode is not None:
        monkeypatch.setenv("BD_REAL_MODE", mode)
    else:
        monkeypatch.delenv("BD_REAL_MODE", raising=False)


async def test_default_is_fake(monkeypatch):
    monkeypatch.delenv("VULTR_API_KEY", raising=False)
    monkeypatch.delenv("BD_REAL_MODE", raising=False)
    settings = settings_from_env()
    assert settings.bd_real_mode is False
    assert type(make_vultr_client(settings)) is FakeVultr


async def test_key_without_bd_real_mode_is_still_fake(monkeypatch):
    """Unset BD_REAL_MODE = existing fake behavior untouched, key or no key."""
    real_mode_env(monkeypatch)
    monkeypatch.delenv("BD_REAL_MODE", raising=False)
    settings = settings_from_env()
    assert settings.bd_real_mode is False
    assert settings.real_mode is False
    assert type(make_vultr_client(settings)) is FakeVultr


async def test_bd_real_mode_without_key_fails_closed(monkeypatch):
    settings = Settings(bd_real_mode=True, vultr_api_key=None)
    with pytest.raises(RuntimeError):
        validate_real_mode(settings)
    with pytest.raises(RuntimeError):
        make_vultr_client(settings)


async def test_bd_real_mode_with_key_builds_realvultr(monkeypatch):
    real_mode_env(monkeypatch, mode="1")
    settings = settings_from_env()
    assert settings.bd_real_mode is True
    assert settings.real_mode is True
    client = make_vultr_client(settings)
    assert type(client) is RealVultr
    await client.aclose()  # construction only; no live calls in tests


async def test_other_setters_of_bd_real_mode(monkeypatch):
    settings = settings_from_env()
    assert settings.bd_real_mode is False  # fixture default

    assert Settings(bd_real_mode=True, vultr_api_key="k").real_mode is True
    assert Settings(bd_real_mode=False, vultr_api_key="k").real_mode is False
    assert Settings(vultr_api_key=None).real_mode is False


async def test_bd_real_mode_truthy_values(monkeypatch):
    for value, expected in (("1", True), ("true", True), ("yes", True),
                            ("0", False), ("false", False), ("junk", False)):
        monkeypatch.setenv("VULTR_API_KEY", "test-key")
        monkeypatch.setenv("APP_SECRET", STRONG_SECRET)
        monkeypatch.setenv("BD_REAL_MODE", value)
        settings = settings_from_env()
        assert settings.bd_real_mode is expected, value
