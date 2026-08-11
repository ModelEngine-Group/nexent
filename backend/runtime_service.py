import logging
import warnings

import uvicorn

from consts.const import APP_VERSION


warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv


load_dotenv()

from apps.runtime_app import app
from utils.logging_utils import configure_elasticsearch_logging, configure_logging


configure_logging(logging.INFO)
configure_elasticsearch_logging()
# smolagents logs every agent step at INFO/DEBUG; quiet it globally to avoid
# log floods in batch scenarios (evaluation runs many cases, each runs an agent).
logging.getLogger("smolagents").setLevel(logging.WARNING)
logger = logging.getLogger("runtime_service")


if __name__ == "__main__":
    logger.info("Starting server initialization...")
    logger.info(f"APP version is: {APP_VERSION}")
    uvicorn.run(app, host="0.0.0.0", port=5014, log_level="info")


