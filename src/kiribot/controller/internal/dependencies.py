"""Instance 运行期身份认证"""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from kiribot.controller.auth import bearer
from kiribot.services.instances import InstanceService, get_instance_service


async def require_instance(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    instances: Annotated[InstanceService, Depends(get_instance_service)],
) -> str:
    instance_id = (
        instances.authenticate_instance(credentials.credentials) if credentials else None
    )
    if instance_id is None:
        raise HTTPException(
            401, "Instance Token 无效", headers={"WWW-Authenticate": "Bearer"}
        )
    return instance_id


InstanceIdentity = Annotated[str, Depends(require_instance)]
