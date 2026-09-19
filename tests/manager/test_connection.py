"""验证连接注册表和生命周期基础约束"""

from unittest.mock import AsyncMock

import pytest

from kiribot.services.gateway.models import GatewayProtocol
from kiribot.services.gateway.registry import (
    ConnectionRegistry,
    ExternalSession,
    Subscriber,
)
from kiribot.services.gateway.transport import (
    Connection,
    ForwardConnection,
    ReverseConnection,
)


def test_connection_abstraction_boundaries() -> None:
    for cls in (Connection, ForwardConnection):
        assert cls.__abstractmethods__
    assert not ReverseConnection.__abstractmethods__


@pytest.mark.asyncio
async def test_registry_rejects_protocol_mismatch_and_disconnects_subscribers() -> None:
    registry = ConnectionRegistry()
    external = AsyncMock()
    external.ready = True
    registry.register_external(
        ExternalSession("source", GatewayProtocol.SATORI, external)
    )
    registry.mark_external_ready("source", GatewayProtocol.SATORI)
    internal = AsyncMock()
    internal.ready = True
    subscriber = Subscriber("source", "worker", GatewayProtocol.ONEBOT_V11, internal)
    with pytest.raises(ConnectionError):
        registry.register_subscriber(subscriber)
    subscriber.protocol = GatewayProtocol.SATORI
    registry.register_subscriber(subscriber)
    await registry.disconnect_subscribers("source")
    internal.close.assert_awaited()
