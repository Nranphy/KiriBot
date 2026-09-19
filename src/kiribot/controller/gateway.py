"""Gateway 外部和内部协议端点"""

from fastapi import APIRouter, Request, Response, WebSocket

from kiribot.services.gateway import GatewayService

router = APIRouter(prefix='/gateway')


@router.websocket('/external/{connection_name}/onebot/v11/ws')
async def onebot_external(websocket: WebSocket, connection_name: str) -> None:
    gateway: GatewayService = websocket.app.state.gateway
    await gateway.serve_onebot_external(websocket, connection_name)


@router.websocket('/internal/{client_id}/{connection_name}/onebot/v11/ws')
async def onebot_internal(websocket: WebSocket, client_id: str, connection_name: str) -> None:
    gateway: GatewayService = websocket.app.state.gateway
    await gateway.serve_onebot_internal(websocket, client_id, connection_name)


@router.websocket('/internal/{client_id}/{connection_name}/satori/v1/events')
async def satori_events(websocket: WebSocket, client_id: str, connection_name: str) -> None:
    gateway: GatewayService = websocket.app.state.gateway
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
) -> Response:
    gateway: GatewayService = request.app.state.gateway
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
