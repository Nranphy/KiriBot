"""OneBot v11 外部与内部 WebSocket 端点"""

from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket

from kiribot.services.gateway import GatewayService, get_gateway_service

router = APIRouter()


@router.websocket('/external/{connection_name}/onebot/v11/ws')
async def onebot_external(
    websocket: WebSocket,
    connection_name: str,
    gateway: Annotated[GatewayService, Depends(get_gateway_service)],
) -> None:
    await gateway.serve_onebot_external(websocket, connection_name)


@router.websocket('/internal/{client_id}/{connection_name}/onebot/v11/ws')
async def onebot_internal(
    websocket: WebSocket,
    client_id: str,
    connection_name: str,
    gateway: Annotated[GatewayService, Depends(get_gateway_service)],
) -> None:
    await gateway.serve_onebot_internal(websocket, client_id, connection_name)
