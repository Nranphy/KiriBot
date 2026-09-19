"""验证健康命令的 SUPERADMIN 鉴权与实际事件处理"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, PrivateMessageEvent
from nonebot.message import handle_event

from kiribot.clients.database import get_database_client
from kiribot.controller.app import create_app


@pytest.mark.asyncio
async def test_manager_command_requires_superadmin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    permissions_path = tmp_path / 'permissions.json'
    permissions_path.write_text(
        json.dumps(
            {
                'superadmins': [
                    {'platform': 'qq', 'open_user_id': '123456'}
                ]
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setenv('KIRIBOT_PERMISSIONS_CONFIG_PATH', str(permissions_path))
    create_app()
    database = get_database_client()
    await database.start()
    send = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(Bot, "send", send)
    bot = Bot(nonebot.get_adapter(Adapter), "10000")
    commands = (
        ('/health', 'KiriBot Manager 运行正常'),
        ('/instance', '请使用 instance list'),
        ('/instance list', '没有配置 Worker 实例'),
        ('/instance status missing', 'Worker 实例不存在'),
        ('/instance start missing', 'Worker 实例不存在'),
        ('/instance stop missing', 'Worker 实例不存在'),
        ('/instance restart missing', 'Worker 实例不存在'),
    )
    try:
        for message_id, (command, _) in enumerate(commands, start=1):
            for user_id in (999999, 123456):
                event = PrivateMessageEvent.model_validate(
                    {
                        "time": 0,
                        "self_id": 10000,
                        "post_type": "message",
                        "message_type": "private",
                        "sub_type": "friend",
                        "message_id": message_id,
                        "user_id": user_id,
                        "message": command,
                        "raw_message": command,
                        "font": 0,
                        "sender": {"user_id": user_id},
                    }
                )
                await handle_event(bot, event)
    finally:
        await database.close()
    assert send.await_count == len(commands) * 2
    calls = [str(call) for call in send.await_args_list]
    for index, (_, success_message) in enumerate(commands):
        assert '权限不足' in calls[index * 2]
        assert success_message in calls[index * 2 + 1]
