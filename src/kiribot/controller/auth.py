"""管理接口凭据校验，与 Gateway 和 Worker 凭据分离"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from kiribot.infra.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


async def require_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """仅配置的管理 Token 可以调用管理 API，空配置拒绝开放"""
    if not settings.admin_token.strip():
        raise HTTPException(503, "尚未配置管理 Token")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.admin_token.encode()
    ):
        raise HTTPException(
            401, "管理 Token 无效", headers={"WWW-Authenticate": "Bearer"}
        )
