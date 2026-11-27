"""Satori 事件流与 HTTP API 代理端点"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, WebSocket

from kiribot.services.gateway import GatewayService, get_gateway_service

router = APIRouter()


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
