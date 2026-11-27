"""管理 Controller 的共享路由与初始化入口"""

from fastapi import APIRouter, Depends

from kiribot.controller.auth import require_admin_token

from .health import router as health_router
from .instances import router as instances_router
from .permissions import router as permissions_router

router = APIRouter(dependencies=[Depends(require_admin_token)])
router.include_router(health_router)
router.include_router(instances_router)
router.include_router(permissions_router)
