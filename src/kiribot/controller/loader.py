"""Controller 模块加载入口"""

from fastapi import FastAPI


def mount_controllers(app: FastAPI) -> None:
    """在应用初始化后注册管理指令并挂载所有 Controller 路由"""

    # 导入 Controller 模块将自动注册 NoneBot 管理指令
    from kiribot.controller.admin import router as admin_router
    from kiribot.controller.gateway import router as gateway_router
    from kiribot.controller.internal import router as internal_router

    # 将 FastAPI 路由挂载到应用
    app.include_router(admin_router)
    app.include_router(internal_router)
    app.include_router(gateway_router)
