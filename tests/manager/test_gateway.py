"""验证 OneBot Gateway 的登记、广播与 Action 关联"""

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve

from kiribot.controller.gateway import router
from kiribot.models.gateway import GatewayConfig
from kiribot.services.gateway import GatewayService, get_gateway_service
from kiribot.services.gateway.models import ConnectionState, GatewayProtocol
from kiribot.services.gateway.onebot11.session import OneBot11ForwardSession

HEADERS = {"X-Self-ID": "10001", "X-Client-Role": "Universal"}


def create_client(token: str | None = None) -> TestClient:
    config = GatewayConfig.model_validate(
        {
            "connections": {
                "napcat-1": {
                    "protocol": "onebot_v11",
                    "mode": "reverse",
                    "token": token,
                },
                "napcat-2": {
                    "protocol": "onebot_v11",
                    "mode": "reverse",
                    "token": token,
                },
            }
        }
    )
    app = FastAPI()
    gateway = GatewayService(config, request_timeout=0.1)
    app.state.gateway = gateway
    app.dependency_overrides[get_gateway_service] = lambda: gateway
    app.include_router(router)
    return TestClient(app)


def external(name: str) -> str:
    return f"/gateway/external/{name}/onebot/v11/ws"


def internal(client_id: str, name: str = "napcat-1") -> str:
    return f"/gateway/internal/{client_id}/{name}/onebot/v11/ws"


def internal_headers(client: TestClient) -> dict[str, str]:
    app = cast(FastAPI, client.app)
    gateway: GatewayService = app.state.gateway
    return {"Authorization": f"Bearer {gateway.internal_token}"}


def test_missing_config_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "nested/gateway.json"
    assert GatewayService.from_config_file(path).config.connections == {}
    assert not path.exists()
    path.parent.mkdir()
    path.write_text('{"connections":{"bad/name":{}}}')
    with pytest.raises(ValidationError):
        GatewayService.from_config_file(path)


def test_ready_event_and_echo_routing() -> None:
    with create_client() as client:
        headers = internal_headers(client)
        with (
            client.websocket_connect(external("napcat-1"), headers=HEADERS) as upstream,
            client.websocket_connect(internal("manager"), headers=headers) as manager,
            client.websocket_connect(internal("worker"), headers=headers) as worker,
        ):
            assert manager.receive_json()["sub_type"] == "connect"
            assert worker.receive_json()["sub_type"] == "connect"
            event = {
                "post_type": "message",
                "self_id": 10001,
                "message": "hello",
            }
            upstream.send_json(event)
            assert manager.receive_json() == event
            assert worker.receive_json() == event
            manager.send_json({"action": "get_status", "echo": "same"})
            first = upstream.receive_json()
            worker.send_json({"action": "get_status", "echo": "same"})
            second = upstream.receive_json()
            assert first["echo"] != second["echo"]
            upstream.send_json(
                {"status": "ok", "data": "worker", "echo": second["echo"]}
            )
            upstream.send_json(
                {"status": "ok", "data": "manager", "echo": first["echo"]}
            )
            assert worker.receive_json()["data"] == "worker"
            assert manager.receive_json()["data"] == "manager"


def test_internal_requires_external_and_duplicate_external_is_rejected() -> None:
    with create_client() as client:
        headers = internal_headers(client)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(internal("worker"), headers=headers),
        ):
            pass
        with client.websocket_connect(external("napcat-1"), headers=HEADERS):
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(external("napcat-1"), headers=HEADERS),
            ):
                pass
            with client.websocket_connect(external("napcat-2"), headers=HEADERS):
                pass


def test_forward_config_rejects_reverse_external_endpoint() -> None:
    config = GatewayConfig.model_validate(
        {
            "connections": {
                "napcat": {
                    "protocol": "onebot_v11",
                    "mode": "forward",
                    "url": "ws://127.0.0.1:3001/",
                }
            }
        }
    )
    app = FastAPI()
    gateway = GatewayService(config)
    app.state.gateway = gateway
    app.dependency_overrides[get_gateway_service] = lambda: gateway
    app.include_router(router)
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(external("napcat"), headers=HEADERS),
    ):
        pass


def test_config_discriminates_protocol_fields() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate({"internal_token": "must-not-be-configured"})
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            {"connections": {"bad": {"protocol": "onebot_v11"}}}
        )
    with pytest.raises(ValidationError):
        GatewayConfig.model_validate(
            {
                "connections": {
                    "bad": {"protocol": "satori", "mode": "reverse", "self_id": "1"}
                }
            }
        )

    forward = GatewayConfig.model_validate(
        {
            "connections": {
                "napcat": {
                    "protocol": "onebot_v11",
                    "mode": "forward",
                    "url": "ws://127.0.0.1:3001/",
                }
            }
        }
    )
    assert forward.connections["napcat"].mode == "forward"
    for invalid_url in ("http://127.0.0.1:3001/", "ws:///missing-host"):
        with pytest.raises(ValidationError):
            GatewayConfig.model_validate(
                {
                    "connections": {
                        "napcat": {
                            "protocol": "onebot_v11",
                            "mode": "forward",
                            "url": invalid_url,
                        }
                    }
                }
            )


def test_internal_token_is_generated_per_gateway() -> None:
    first = GatewayService().internal_token
    second = GatewayService().internal_token
    assert first != second
    assert len(first) >= 32


@pytest.mark.asyncio
async def test_forward_connection_reconnects_and_uses_bearer_token() -> None:
    attempts = 0
    second_connection = asyncio.Event()
    authorization: list[str | None] = []

    async def handler(websocket: ServerConnection) -> None:
        nonlocal attempts
        attempts += 1
        assert websocket.request is not None
        authorization.append(websocket.request.headers.get("authorization"))
        await websocket.send(
            json.dumps(
                {
                    "time": 0,
                    "self_id": 10001,
                    "post_type": "meta_event",
                    "meta_event_type": "lifecycle",
                    "sub_type": "connect",
                }
            )
        )
        if attempts == 1:
            await websocket.close()
            return
        second_connection.set()
        await websocket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        config = GatewayConfig.model_validate(
            {
                "connections": {
                    "napcat": {
                        "protocol": "onebot_v11",
                        "mode": "forward",
                        "url": f"ws://127.0.0.1:{port}/",
                        "token": "secret",
                    }
                }
            }
        )
        gateway = GatewayService(config)
        await gateway.start()
        try:
            async with asyncio.timeout(5):
                await second_connection.wait()
                while gateway.connection_states.get("napcat") != ConnectionState.READY:
                    await asyncio.sleep(0.01)
            external_session = gateway.registry.get_external(
                "napcat", GatewayProtocol.ONEBOT_V11
            )
            assert external_session is not None
            assert isinstance(external_session.connection, OneBot11ForwardSession)
            assert external_session.connection.self_id == "10001"
            assert attempts >= 2
            assert authorization == ["Bearer secret", "Bearer secret"]
        finally:
            await gateway.close()
