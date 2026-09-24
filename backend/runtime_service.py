import logging
import warnings

import uvicorn

from consts.const import APP_VERSION


warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv


load_dotenv()

from apps.runtime_app import app
from utils.logging_utils import (
    configure_runtime_uvicorn_logging,
    get_uvicorn_logging_config,
)


configure_runtime_uvicorn_logging()
logger = logging.getLogger("runtime")

if __name__ == "__main__":
    logger.info("Starting server initialization...")
    logger.info(f"APP version is: {APP_VERSION}")
    uvicorn.run(app, host="0.0.0.0", port=5014, log_level="info", log_config=get_uvicorn_logging_config(categories=["runtime"]))
