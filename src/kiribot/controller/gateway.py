"""Gateway 外部和内部协议端点"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, WebSocket

from kiribot.services.gateway import GatewayService, get_gateway_service

router = APIRouter(prefix='/gateway')


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


@router.websocket('/internal/{client_id}/{connection_name}/satori/v1/events')
async def satori_events(
    websocket: WebSocket,
    client_id: str,
    connection_name: str,
    gateway: Annotated[GatewayService, Depends(get_gateway_service)],
) -> None:
    await gateway.serve_satori_internal(websocket, client_id, connection_name)


@router.api_route(
    '/internal/{client_id}/{connection_name}/satori/v1/{api_path:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
)
async def satori_api(
    request: Request,
    client_id: str,
    connection_name: str,
    api_path: str,
    gateway: Annotated[GatewayService, Depends(get_gateway_service)],
) -> Response:
    result = await gateway.proxy_satori_api(
        connection_name,
        api_path,
        request.method,
        dict(request.headers),
        await request.body(),
        request.url.query,
    )
    return Response(
        content=result.content,
        status_code=result.status_code,
        headers=result.headers,
    )
