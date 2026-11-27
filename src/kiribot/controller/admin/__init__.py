"""管理 Controller 的共享路由与初始化入口"""

from fastapi import APIRouter, Depends

from kiribot.controller.auth import require_admin_token

router = APIRouter(dependencies=[Depends(require_admin_token)])
