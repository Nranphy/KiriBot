"""组装 Gateway 协议路由"""

from fastapi import APIRouter

from .onebot11 import router as onebot11_router
from .satori import router as satori_router

router = APIRouter(prefix='/gateway')
router.include_router(onebot11_router)
router.include_router(satori_router)
