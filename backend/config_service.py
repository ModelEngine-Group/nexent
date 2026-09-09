import logging
import logging.config
import warnings

import uvicorn

from consts.const import APP_VERSION


warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv


load_dotenv()

from apps.config_app import app
from utils.logging_utils import (
    configure_elasticsearch_logging,
    get_uvicorn_logging_config,
)


logging.config.dictConfig(get_uvicorn_logging_config(categories=["config"]))
configure_elasticsearch_logging()
logger = logging.getLogger("config")

if __name__ == "__main__":
    logger.info("Starting server initialization...")
    logger.info(f"APP version is: {APP_VERSION}")
    uvicorn.run(app, host="0.0.0.0", port=5010, log_level="info", log_config=get_uvicorn_logging_config(categories=["config"]))
