"""验证配置优先级与应用启动边界"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kiribot.controller.app import create_app
from kiribot.infra.config import Settings
from kiribot.services.gateway import get_gateway_service
from kiribot.services.users import get_user_recorder


def test_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("KIRIBOT_PORT=8123\n", encoding="utf-8")
    monkeypatch.delenv("KIRIBOT_PORT", raising=False)
    assert Settings().port == 8123
    monkeypatch.setenv("KIRIBOT_PORT", "8124")
    assert Settings().port == 8124


def test_database_url_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "sqlite+aiosqlite:///custom/kiribot.db"
    monkeypatch.setenv("KIRIBOT_DATABASE_URL", database_url)

    assert Settings().database_url == database_url


def test_health_and_only_route(monkeypatch: pytest.MonkeyPatch) -> None:
    check = AsyncMock()
    monkeypatch.setattr("kiribot.controller.app.check_playwright", check)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "ok",
        }
        for path in ("/docs", "/redoc", "/openapi.json", "/"):
            assert client.get(path).status_code == 404
    check.assert_awaited_once()


def test_browser_failure_blocks_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kiribot.controller.app.check_playwright",
        AsyncMock(side_effect=RuntimeError("browser unavailable")),
    )
    with (
        pytest.raises(RuntimeError, match="browser unavailable"),
        TestClient(create_app()),
    ):
        pass


def test_database_failure_blocks_startup_and_releases_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("kiribot.controller.app.check_playwright", AsyncMock())
    database = AsyncMock()
    database.start.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(
        "kiribot.controller.app.get_database_client",
        lambda: database,
    )
    gateway = get_gateway_service()
    gateway.start = AsyncMock()  # type: ignore[method-assign]
    recorder = get_user_recorder()
    recorder.start = AsyncMock()  # type: ignore[method-assign]

    with (
        pytest.raises(RuntimeError, match="database unavailable"),
        TestClient(create_app()),
    ):
        pass

    database.start.assert_awaited_once()
    database.close.assert_awaited_once()
    recorder.start.assert_not_awaited()
    gateway.start.assert_not_awaited()
