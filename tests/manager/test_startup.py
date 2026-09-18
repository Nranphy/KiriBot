"""验证配置优先级与应用启动边界"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kiribot.controller.app import create_app
from kiribot.infra.config import Settings


def test_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("KIRIBOT_PORT=8123\n", encoding="utf-8")
    monkeypatch.delenv("KIRIBOT_PORT", raising=False)
    assert Settings().port == 8123
    monkeypatch.setenv("KIRIBOT_PORT", "8124")
    assert Settings().port == 8124


def test_health_and_only_route(monkeypatch: pytest.MonkeyPatch) -> None:
    check = AsyncMock()
    monkeypatch.setattr("kiribot.controller.app.check_playwright", check)
    app = create_app(Settings())
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
        TestClient(create_app(Settings())),
    ):
        pass
