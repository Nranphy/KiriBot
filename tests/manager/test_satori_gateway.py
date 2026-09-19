"""验证 Satori 握手、广播和代理边界"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kiribot.controller.gateway import router
from kiribot.models.gateway import GatewayConfig
from kiribot.services.gateway import GatewayService, get_gateway_service
from kiribot.services.gateway.models import GatewayProtocol, SubscriberKey
from kiribot.services.gateway.registry import ExternalSession, Subscriber
from kiribot.services.gateway.satori.api_client import SatoriApiClient
from kiribot.services.gateway.satori.service import SatoriGateway
from kiribot.services.gateway.satori.session import SatoriExternalSession


def create_client(online: bool = True) -> tuple[TestClient, GatewayService]:
    config = GatewayConfig.model_validate(
        {
            "connections": {
                "chronocat": {
                    "protocol": "satori",
                    "platform": "qq",
                    "url": "http://127.0.0.1:5500",
                    "token": "secret",
                }
            }
        }
    )
    gateway = GatewayService(config)
    if online:
        connection = SatoriExternalSession(
            "chronocat", "ws://localhost/v1/events", "secret"
        )
        connection.ready = True
        connection.ready_payload = {"op": 4, "body": {"logins": [], "proxy_urls": []}}
        gateway.registry.register_external(
            ExternalSession("chronocat", GatewayProtocol.SATORI, connection)
        )
        gateway.registry.mark_external_ready("chronocat", GatewayProtocol.SATORI)
    app = FastAPI()
    app.state.gateway = gateway
    app.dependency_overrides[get_gateway_service] = lambda: gateway
    app.include_router(router)
    return TestClient(app), gateway


def events() -> str:
    return "/gateway/internal/weather/chronocat/satori/v1/events"


def test_internal_handshake_and_heartbeat() -> None:
    client, gateway = create_client()
    with client, client.websocket_connect(events()) as websocket:
        websocket.send_json({"op": 3, "body": {"token": gateway.internal_token}})
        assert websocket.receive_json()["op"] == 4
        websocket.send_json({"op": 1, "body": {}})
        assert websocket.receive_json() == {"op": 2, "body": {}}


def test_internal_rejects_offline_external() -> None:
    client, _ = create_client(False)
    with client, pytest.raises(WebSocketDisconnect), client.websocket_connect(events()):
        pass


@pytest.mark.asyncio
async def test_event_broadcast_is_non_blocking_and_isolated() -> None:
    gateway = GatewayService()
    ready = AsyncMock()
    ready.ready = True
    other = AsyncMock()
    other.ready = True
    first_key = SubscriberKey("chronocat", "worker")
    other_key = SubscriberKey("other", "worker")
    gateway.registry.subscribers = {
        first_key: Subscriber("chronocat", "worker", GatewayProtocol.SATORI, ready),
        other_key: Subscriber("other", "worker", GatewayProtocol.SATORI, other),
    }
    payload = {"op": 0, "body": {"sn": 1, "type": "message-created"}}
    await gateway.satori.router.route("chronocat", payload)
    assert gateway.registry.subscribers[first_key].queue.get_nowait() == payload
    assert gateway.registry.subscribers[other_key].queue.empty()
    await gateway.close()


def test_satori_urls() -> None:
    assert (
        SatoriGateway.events_url("https://example.com/service")
        == "wss://example.com/service/v1/events"
    )
    assert SatoriApiClient.build_url(
        "https://example.com/service", "message.create"
    ) == ("https://example.com/service/v1/message.create")
    for api_path in (
        "../admin",
        "proxy/../admin",
        "/message.create",
        r"proxy\admin",
        "%2e%2e/admin",
        "proxy//admin",
    ):
        with pytest.raises(ValueError):
            SatoriApiClient.build_url("https://example.com/service", api_path)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "https:///missing-host",
        "https://user:password@example.com",
        "https://example.com?token=secret",
        "https://example.com#fragment",
    ],
)
def test_satori_config_rejects_invalid_service_url(url: str) -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            {
                "connections": {
                    "chronocat": {
                        "protocol": "satori",
                        "platform": "qq",
                        "url": url,
                    }
                }
            }
        )
