"""Ortak test yardımcıları: her test kendi uygulama örneğini (AppContext + TestClient) kurar — global durum yok."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arrivalguard.api.app import create_app
from arrivalguard.api.context import AppContext
from arrivalguard.api.settings import Settings
from arrivalguard.nac_client import FixtureBackend, NacClient, NacConfig
from arrivalguard.rules import Config

ROOT = Path(__file__).resolve().parents[1]
PATIENT = "+447700900001"
SWAPPED = "+447700900003"
DRIVER = "+447700900101"
IMPOSTOR = "+447700900109"
TOKEN = "test-webhook-token-0123456789"


def fixture_nac(retries: int = 0) -> NacClient:
    fx = FixtureBackend.from_json(ROOT / "fixtures" / "profiles.json")
    now = datetime.now(timezone.utc)
    fx.update_profile(PATIENT, {"sim_swap_at": (now - timedelta(days=120)).isoformat(), "fail": None})
    fx.update_profile(SWAPPED, {"sim_swap_at": (now - timedelta(hours=3)).isoformat(), "fail": None})
    return NacClient(NacConfig(mode="fixture", retries=retries), fixtures=fx)


@pytest.fixture
def make_app(tmp_path):
    """make_app(**Settings alanları) → (TestClient, AppContext)."""

    def _make(ctx_kwargs: dict | None = None, **overrides):
        base = {"scheduler_interval_s": 0, "webhook_token": TOKEN, "public_base_url": "https://ag.test"}
        settings = Settings(**(base | overrides))
        ctx = AppContext(settings, cfg=Config(), nac=fixture_nac(), **(ctx_kwargs or {}))
        return TestClient(create_app(settings, ctx)), ctx

    return _make


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app[0]


@pytest.fixture
def ctx(app):
    return app[1]
