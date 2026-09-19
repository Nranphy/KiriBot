"""Satori HTTP API 的共享连接池与透明代理"""

from urllib.parse import urlparse, urlunparse

import httpx

from kiribot.services.gateway.models import ProxyResponse

HOP_BY_HOP_HEADERS = {
    'connection',
    'content-length',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'transfer-encoding',
    'upgrade',
}


class SatoriApiClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.client: httpx.AsyncClient | None = None

    @staticmethod
    def validate_api_path(api_path: str) -> None:
        """拒绝可能逃逸 Satori `/v1/` 前缀的 API 路径"""
        if not api_path or api_path.startswith(('/', '\\')):
            raise ValueError('Satori API 路径必须是相对路径')
        if '%' in api_path:
            raise ValueError('Satori API 路径不能包含百分号编码')
        if any(ord(character) < 32 for character in api_path):
            raise ValueError('Satori API 路径不能包含控制字符')
        if '?' in api_path or '#' in api_path or '\\' in api_path:
            raise ValueError('Satori API 路径包含非法字符')
        if any(segment in {'', '.', '..'} for segment in api_path.split('/')):
            raise ValueError('Satori API 路径包含非法层级')

    @staticmethod
    def build_url(base_url: str, api_path: str, query: str = '') -> str:
        SatoriApiClient.validate_api_path(api_path)
        parsed = urlparse(base_url)
        scheme = {'http': 'http', 'https': 'https', 'ws': 'http', 'wss': 'https'}.get(parsed.scheme)
        if scheme is None or not parsed.netloc:
            raise ValueError('Satori url 必须是有效的 HTTP(S) 或 WS(S) 地址')
        path = f'{parsed.path.rstrip("/")}/v1/{api_path}'
        return urlunparse(parsed._replace(scheme=scheme, path=path, query=query))

    async def request(
        self,
        base_url: str,
        token: str | None,
        api_path: str,
        method: str,
        headers: dict[str, str],
        content: bytes,
        query: str,
    ) -> ProxyResponse:
        outgoing = {
            key: value
            for key, value in headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS | {'host', 'authorization'}
        }
        if token is not None:
            outgoing['Authorization'] = f'Bearer {token}'
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout)
        try:
            url = self.build_url(base_url, api_path, query)
        except ValueError:
            return ProxyResponse(400, {})
        try:
            response = await self.client.request(
                method,
                url,
                headers=outgoing,
                content=content,
            )
        except httpx.HTTPError:
            return ProxyResponse(502, {})
        response_headers = {
            key: value for key, value in response.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return ProxyResponse(response.status_code, response_headers, response.content)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
