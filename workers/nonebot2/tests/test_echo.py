from pathlib import Path

import pytest
from kiribot_worker.connection import WorkerSettings
from kiribot_worker.plugins.echo import render_echo
from nonebot_plugin_alconna import Alconna, Args, MultiVar


def test_echo_command_accepts_multiple_words() -> None:
    command = Alconna("echo", Args["content", MultiVar(str)])

    result = command.parse("echo hello world")

    assert result.matched
    assert render_echo(result.all_matched_args["content"]) == "hello world"


def test_worker_ignores_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "KIRIBOT_WORKER_GATEWAY_URL=ws://from-dotenv\n"
        "KIRIBOT_WORKER_ACCESS_TOKEN=from-dotenv\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KIRIBOT_WORKER_GATEWAY_URL", "ws://from-manager")
    monkeypatch.setenv("KIRIBOT_WORKER_ACCESS_TOKEN", "from-manager")

    settings = WorkerSettings()  # pyright: ignore[reportCallIssue]

    assert settings.gateway_url == "ws://from-manager"
    assert settings.access_token == "from-manager"
