"""NoneBot 应用与 Gateway 适配器初始化"""

import nonebot
from fastapi import FastAPI
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
from nonebot.adapters.satori import Adapter as SatoriAdapter

from kiribot.infra.config import Settings
from kiribot.infra.network import gateway_url_host
from kiribot.services.gateway import get_gateway_service


def initialize_nonebot(settings: Settings) -> FastAPI:
    """初始化 NoneBot 及协议 Adapter，返回其 ASGI 应用"""
    gateway = get_gateway_service()
    gateway_host = gateway_url_host(settings.host)
    onebot_clients = {
        f'ws://{gateway_host}:{settings.port}/gateway/internal/manager/{name}/onebot/v11/ws'
        for name, config in gateway.config.external.items()
        if config.protocol == 'onebot_v11'
    }
    satori_clients = [
        {
            'host': gateway_host,
            'port': settings.port,
            'path': f'gateway/internal/manager/{name}/satori',
            'token': gateway.internal_token,
        }
        for name, config in gateway.config.external.items()
        if config.protocol == 'satori' and config.mode == 'forward'
    ]
    nonebot.init(
        _env_file=(),
        driver='~fastapi+~httpx+~websockets',
        log_level=settings.log_level,
        command_start={'/'},
        onebot_v11_ws_urls=onebot_clients,
        onebot_v11_access_token=gateway.internal_token,
        satori_clients=satori_clients,
    )
    driver = nonebot.get_driver()
    for adapter in (OneBotAdapter, SatoriAdapter):
        driver.register_adapter(adapter)
    bot_app: FastAPI = nonebot.get_asgi()
    return bot_app
