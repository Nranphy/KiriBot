"""验证服务登记、独立就绪与请求路由"""

from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kiribot.controller.gateway import router
from kiribot.models.gateway import GatewayConfig
from kiribot.services.gateway import Gateway

HEADERS = {"X-Self-ID": "10001", "X-Client-Role": "Universal"}


def create_client(token: str | None = None) -> TestClient:
    config = GatewayConfig.model_validate(
        {"connections": {"napcat-1": {"protocol": "onebot_v11", "token": token}}}
    )
    app = FastAPI()
    app.state.gateway = Gateway(config, request_timeout=0.1)
    app.include_router(router)
    return TestClient(app)


def test_missing_config_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "nested/gateway.json"
    assert (
        Gateway.from_config_file(path, "ws://localhost/manager").config.connections
        == {}
    )
    assert not path.exists()
    assert not path.parent.exists()
    path.parent.mkdir()
    path.write_text('{"connections":{"bad/name":{}}}')
    with pytest.raises(ValidationError):
        Gateway.from_config_file(path, "ws://localhost/manager")
    assert "bad/name" in path.read_text()


def test_ready_and_echo_routing() -> None:
    with (
        create_client() as client,
        client.websocket_connect("/ws/napcat-1", headers=HEADERS) as upstream,
        client.websocket_connect("/ws/internal/controller/10001") as manager,
        client.websocket_connect("/ws/internal/worker/10001") as worker,
        client.websocket_connect("/ws/internal/worker-2/10001") as worker_2,
    ):
        for internal in (manager, worker, worker_2):
            assert internal.receive_json()["sub_type"] == "connect"
        upstream.send_json(
            {
                "post_type": "meta_event",
                "self_id": 10001,
                "meta_event_type": "lifecycle",
            }
        )
        event = {"post_type": "message", "self_id": 10001, "message": "hello"}
        upstream.send_json(event)
        assert manager.receive_json() == event
        assert worker.receive_json() == event
        assert worker_2.receive_json() == event
        manager.send_json({"action": "get_status", "echo": "same"})
        first = upstream.receive_json()
        worker.send_json({"action": "get_status", "echo": "same"})
        second = upstream.receive_json()
        assert first["echo"] != second["echo"]
        for request, value in ((second, "worker"), (first, "manager")):
            upstream.send_json(
                {"status": "ok", "retcode": 0, "data": value, "echo": request["echo"]}
            )
        assert manager.receive_json()["data"] == "manager"
        assert worker.receive_json()["data"] == "worker"


def test_internal_survives_external_disconnect() -> None:
    with (
        create_client() as client,
        client.websocket_connect("/ws/internal/controller/10001") as manager,
    ):
        assert manager.receive_json()["sub_type"] == "connect"
        manager.send_json({"action": "get_status", "echo": "offline"})
        assert manager.receive_json()["retcode"] == 1503
        for _ in range(2):
            with client.websocket_connect("/ws/napcat-1", headers=HEADERS) as upstream:
                event = {"post_type": "message", "self_id": 10001, "message": "hello"}
                upstream.send_json(event)
                assert manager.receive_json() == event
        manager.send_json({"action": "get_status", "echo": "still-connected"})
        assert manager.receive_json()["echo"] == "still-connected"


def test_registration_authentication_and_single_connection() -> None:
    with create_client("secret") as client:
        for name, headers in (
            ("unknown", HEADERS),
            ("napcat-1", HEADERS),
            ("napcat-1", {**HEADERS, "X-Client-Role": "Event"}),
        ):
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect(f"/ws/{name}", headers=headers),
            ):
                pass
        headers = {**HEADERS, "Authorization": "Bearer secret"}
        with client.websocket_connect("/ws/napcat-1", headers=headers) as upstream:
            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect("/ws/napcat-1", headers=headers),
            ):
                pass
            upstream.send_json({"post_type": "message", "self_id": 2})
            with pytest.raises(WebSocketDisconnect):
                upstream.receive_json()


def test_timeout_and_internal_reconnect() -> None:
    with (
        create_client() as client,
        client.websocket_connect("/ws/napcat-1", headers=HEADERS) as upstream,
    ):
        for _ in range(2):
            with client.websocket_connect("/ws/internal/controller/10001") as manager:
                assert manager.receive_json()["sub_type"] == "connect"
                manager.send_json({"action": "get_status", "echo": {"request": 1}})
                upstream.receive_json()
                response = manager.receive_json()
                assert response["retcode"] == 1503
                assert response["echo"] == {"request": 1}
