"""Gateway WebSocket 端点，连接维护由 Service 承担"""

from fastapi import APIRouter, WebSocket

from kiribot.services.gateway import Gateway

router = APIRouter()


@router.websocket("/ws/internal/{client_id}/{self_id}")
async def internal_ws(
    websocket: WebSocket,
    client_id: str,
    self_id: str,
) -> None:
    """转交 Worker 内部连接"""
    gateway: Gateway = websocket.app.state.gateway
    await gateway.serve_internal(websocket, client_id, self_id)


@router.websocket("/ws/{name}")
async def reverse_ws(
    websocket: WebSocket,
    name: str,
) -> None:
    """转交登记服务的外部反向连接"""
    gateway: Gateway = websocket.app.state.gateway
    await gateway.serve_external(websocket, name)
