"""验证真实 WS 下自动接入 Manager 的多账号消息链路"""

import asyncio
import json
import socket
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import uvicorn
from websockets.asyncio.client import connect

from kiribot.controller.app import create_app
from kiribot.infra.config import Settings
from kiribot.services.gateway import Gateway


@pytest.mark.asyncio
async def test_external_accounts_automatically_route_to_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps(
            {
                "connections": {
                    "napcat-1": {"protocol": "onebot_v11"},
                    "napcat-2": {"protocol": "onebot_v11"},
                }
            }
        )
    )
    monkeypatch.setattr("kiribot.controller.app.check_playwright", AsyncMock())
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    app = create_app(Settings(port=port, gateway_config_path=config))
    gateway: Gateway = app.state.gateway
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    await task
                    pytest.fail("服务器未启动")
                await asyncio.sleep(0.01)
            for index, self_id in enumerate(("10001", "10002"), start=1):
                async with connect(
                    f"ws://127.0.0.1:{port}/ws/napcat-{index}",
                    additional_headers={
                        "X-Self-ID": self_id,
                        "X-Client-Role": "Universal",
                    },
                ) as upstream:
                    while "manager" not in gateway.clients.get(self_id, {}):
                        await asyncio.sleep(0.01)
                    await upstream.send(
                        json.dumps(
                            {
                                "time": 0,
                                "self_id": int(self_id),
                                "post_type": "message",
                                "message_type": "private",
                                "sub_type": "friend",
                                "message_id": index,
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
                    await upstream.send(
                        json.dumps(
                            {
                                "status": "ok",
                                "retcode": 0,
                                "data": {"message_id": index},
                                "echo": action["echo"],
                            }
                        )
                    )
                assert "manager" in gateway.clients[self_id]
            assert set(gateway.manager_tasks) == {"10001", "10002"}
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            listener.close()
