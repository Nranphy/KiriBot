"""验证协议观察提取与用户、群聊持久化"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from kiribot.clients.database import (
    DatabaseClient,
    GroupTable,
    IdentityTable,
    UserTable,
)
from kiribot.models.gateway import GatewayConfig
from kiribot.models.users import ChatPlatform, GroupObservation, UserObservation
from kiribot.services.gateway import GatewayService
from kiribot.services.gateway.onebot11.extractor import (
    extract_user_observation as extract_onebot_observation,
)
from kiribot.services.gateway.satori.extractor import (
    extract_user_observation as extract_satori_observation,
)
from kiribot.services.users import UserService


class ObservationCollector:
    def __init__(self) -> None:
        self.observations: list[UserObservation] = []

    def submit(self, observation: UserObservation) -> bool:
        self.observations.append(observation)
        return True


def test_extracts_onebot_private_and_group_messages() -> None:
    private = extract_onebot_observation(
        {
            "time": 1,
            "post_type": "message",
            "message_type": "private",
            "user_id": 10001,
            "sender": {"nickname": "Alice"},
        },
        ChatPlatform.QQ,
    )
    assert private is not None
    assert private.open_user_id == "10001"
    assert private.name == "Alice"
    assert private.group is None

    group = extract_onebot_observation(
        {
            "post_type": "message",
            "message_type": "group",
            "user_id": 10001,
            "group_id": 20002,
            "sender": {"nickname": "Alice", "card": "群名片"},
        },
        ChatPlatform.QQ,
    )
    assert group is not None
    assert group.name == "群名片"
    assert group.group == GroupObservation(ChatPlatform.QQ, "20002")


def test_extracts_satori_user_and_qq_group() -> None:
    observation = extract_satori_observation(
        {
            'platform': 'qq',
            'timestamp': 1000,
            'user': {'id': '10001', 'name': 'Alice'},
            'guild': {'id': '20002', 'name': '测试群'},
            'channel': {'id': '30003'},
        },
        ChatPlatform.QQ,
    )
    assert observation is not None
    assert observation.open_user_id == '10001'
    assert observation.group == GroupObservation(
        ChatPlatform.QQ,
        "20002",
        name="测试群",
    )

    with pytest.raises(ValueError, match="平台"):
        extract_satori_observation(
            {"platform": "discord", "user": {"id": "1"}},
            ChatPlatform.QQ,
        )


@pytest.mark.asyncio
async def test_gateway_submits_observation_without_changing_event() -> None:
    collector = ObservationCollector()
    config = GatewayConfig.model_validate(
        {
            "connections": {
                "napcat": {
                    "protocol": "onebot_v11",
                    "mode": "reverse",
                    "platform": "qq",
                }
            }
        }
    )
    gateway = GatewayService(config, observation_sink=collector)
    event = {
        "post_type": "message",
        "message_type": "private",
        "self_id": 20000,
        "user_id": 10001,
        "sender": {"nickname": "Alice"},
    }

    await gateway.onebot11.router.route("napcat", "20000", event)

    assert len(collector.observations) == 1
    assert collector.observations[0].open_user_id == "10001"
    await gateway.close()


@pytest.mark.asyncio
async def test_records_identity_and_group_idempotently(tmp_path: Path) -> None:
    database = DatabaseClient(
        f"sqlite+aiosqlite:///{(tmp_path / 'users.db').as_posix()}"
    )
    await database.start()
    service = UserService(database)
    first_seen = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    try:
        await service.record(
            UserObservation(
                platform=ChatPlatform.QQ,
                open_user_id='10001',
                observed_at=first_seen,
                name='Alice',
                group=GroupObservation(ChatPlatform.QQ, '20002'),
            )
        )
        await service.record(
            UserObservation(
                platform=ChatPlatform.QQ,
                open_user_id="10001",
                observed_at=later,
                name=None,
                group=GroupObservation(ChatPlatform.QQ, "20002", name="测试群"),
            )
        )
        await service.record(
            UserObservation(
                platform=ChatPlatform.QQ,
                open_user_id="10001",
                observed_at=first_seen,
                name="过期昵称",
                group=GroupObservation(ChatPlatform.QQ, "20002", name="过期群名"),
            )
        )

        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(UserTable)) == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(IdentityTable))
                == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(GroupTable)) == 1
            )
            identity = await session.get(IdentityTable, ("qq", "10001"))
            assert identity is not None
            assert identity.name == 'Alice'
            assert identity.last_seen_at == later.replace(tzinfo=None)
            group = await session.scalar(select(GroupTable))
            assert group is not None
            assert group.name == "测试群"
            assert group.open_channel_id is None
    finally:
        await database.close()
