"""启动 Manager"""

import uvicorn

from kiribot.controller.app import create_app
from kiribot.infra.config import Settings
from kiribot.infra.log import configure_logging

if __name__ == "__main__":
    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        log_level=settings.log_level.lower(),
    )
