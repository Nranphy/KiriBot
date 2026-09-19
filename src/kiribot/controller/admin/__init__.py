"""管理 Controller 的共享路由与初始化入口"""

from fastapi import APIRouter

router = APIRouter()

_initialized = False


def initialize_admin_controllers() -> None:
    """在 NoneBot 初始化完成后导入并注册管理 Controller"""
    global _initialized

    if _initialized:
        return

    from kiribot.controller.admin import health as health

    _initialized = True
