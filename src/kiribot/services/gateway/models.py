"""Gateway 内部连接、协议和代理结果模型"""

from dataclasses import dataclass
from enum import StrEnum


class GatewayProtocol(StrEnum):
    """Gateway 当前支持的机器人协议"""

    ONEBOT_V11 = 'onebot_v11'
    SATORI = 'satori'


class ConnectionState(StrEnum):
    """外部连接生命周期状态"""

    STOPPED = 'stopped'
    WAITING = 'waiting'
    CONNECTING = 'connecting'
    READY = 'ready'
    RECONNECTING = 'reconnecting'


@dataclass(frozen=True)
class ConnectionKey:
    name: str
    protocol: GatewayProtocol


@dataclass(frozen=True)
class SubscriberKey:
    connection_name: str
    client_id: str


@dataclass(frozen=True)
class ProxyResponse:
    """不依赖 Web 框架的 HTTP 代理结果"""

    status_code: int
    headers: dict[str, str]
    content: bytes = b''
