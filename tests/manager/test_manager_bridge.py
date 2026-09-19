"""验证 Manager 作为普通内部客户端自动接入 OneBot Gateway"""

import asyncio
import json
import socket
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import uvicorn
from websockets.asyncio.client import connect

from kiribot.controller.app import create_app
from kiribot.services.gateway import GatewayService, get_gateway_service
from kiribot.services.gateway.models import SubscriberKey


@pytest.mark.asyncio
async def test_manager_uses_standard_internal_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps(
            {
                "connections": {
                    "napcat-1": {
                        "protocol": "onebot_v11",
                        "mode": "reverse",
                        "platform": "qq",
                    }
                }
            }
        )
    )
    monkeypatch.setattr("kiribot.controller.app.check_playwright", AsyncMock())
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    monkeypatch.setenv("KIRIBOT_PORT", str(port))
    monkeypatch.setenv("KIRIBOT_GATEWAY_CONFIG_PATH", str(config))
    app = create_app()
    gateway: GatewayService = get_gateway_service()
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(15):
            while not server.started:
                await asyncio.sleep(0.01)
            async with connect(
                f"ws://127.0.0.1:{port}/gateway/external/napcat-1/onebot/v11/ws",
                additional_headers={"X-Self-ID": "10001", "X-Client-Role": "Universal"},
            ) as upstream:
                while (
                    SubscriberKey("napcat-1", "manager")
                    not in gateway.registry.subscribers
                ):
                    await asyncio.sleep(0.01)
                await upstream.send(
                    json.dumps(
                        {
                            "time": 0,
                            "self_id": 10001,
                            "post_type": "message",
                            "message_type": "private",
                            "sub_type": "friend",
                            "message_id": 1,
                            "user_id": 123456,
                            "message": "/health",
                            "raw_message": "/health",
                            "font": 0,
                            "sender": {"user_id": 123456},
                        }
                    )
                )
                action = json.loads(await upstream.recv())
                assert "正常" in json.dumps(action["params"], ensure_ascii=False)
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            listener.close()
