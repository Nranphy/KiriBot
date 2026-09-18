"""验证公开健康命令的实际事件处理"""

from unittest.mock import AsyncMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot, PrivateMessageEvent
from nonebot.message import handle_event

from kiribot.controller.app import create_app


@pytest.mark.asyncio
async def test_health_command(monkeypatch: pytest.MonkeyPatch) -> None:
    create_app()
    send = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(Bot, "send", send)
    bot = Bot(nonebot.get_adapter(Adapter), "10000")
    for user_id in (999999, 123456):
        event = PrivateMessageEvent.model_validate(
            {
                "time": 0,
                "self_id": 10000,
                "post_type": "message",
                "message_type": "private",
                "sub_type": "friend",
                "message_id": 1,
                "user_id": user_id,
                "message": "/health",
                "raw_message": "/health",
                "font": 0,
                "sender": {"user_id": user_id},
            }
        )
        await handle_event(bot, event)
    assert send.await_count == 2
