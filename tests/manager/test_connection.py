"""验证连接契约的重试、就绪与清理行为"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from kiribot.services.gateway import Gateway
from kiribot.services.gateway.connection import (
    Connection,
    ForwardConnection,
    ReverseConnection,
)
from kiribot.services.gateway.onebot_connection import OneBot11ForwardConnection


def test_connection_types_are_abstract() -> None:
    for cls in (Connection, ForwardConnection, ReverseConnection):
        assert cls.__abstractmethods__


@pytest.mark.asyncio
async def test_forward_retry_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = Gateway()
    connection = OneBot11ForwardConnection("10001", "ws://localhost/manager")
    opened = AsyncMock(side_effect=[OSError("离线"), None])
    closed = AsyncMock()
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])

    async def handshake() -> None:
        assert "manager" not in gateway.clients.get("10001", {})
        connection.ready = True

    async def receive() -> dict:
        assert gateway.clients["10001"]["manager"] is connection
        raise ConnectionError("连接断开")

    async def close(code: int = 1001) -> None:
        connection.ready = False
        await closed(code)

    monkeypatch.setattr(connection, "open", opened)
    monkeypatch.setattr(connection, "handshake", handshake)
    monkeypatch.setattr(connection, "receive", receive)
    monkeypatch.setattr(connection, "close", close)
    monkeypatch.setattr("kiribot.services.gateway.gateway.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await gateway._reconnect(connection, "manager")
    assert opened.await_count == 2
    assert closed.await_count == 2
    assert sleep.await_count == 2
    assert all(call.args == (3,) for call in sleep.await_args_list)
    assert not connection.ready
    assert gateway.clients == {}
