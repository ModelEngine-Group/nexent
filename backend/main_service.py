import uvicorn
import logging
import warnings
import asyncio

from consts.const import APP_VERSION

warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv
load_dotenv()

from apps.base_app import app
from utils.logging_utils import configure_logging, configure_elasticsearch_logging
from services.tool_configuration_service import initialize_tools_on_startup

configure_logging(logging.INFO)
configure_elasticsearch_logging()
logger = logging.getLogger("main_service")


async def startup_initialization():
    """
    Perform initialization tasks during server startup
    """
    logger.info("Starting server initialization...")
    logger.info(f"APP version is: {APP_VERSION}")
    try:
        # Initialize tools on startup - service layer handles detailed logging
        await initialize_tools_on_startup()
        logger.info("Server initialization completed successfully!")
            
    except Exception as e:
        logger.error(f"Server initialization failed: {str(e)}")
        # Don't raise the exception to allow server to start even if initialization fails
        logger.warning("Server will continue to start despite initialization issues")


if __name__ == "__main__":
    asyncio.run(startup_initialization())
    uvicorn.run(app, host="0.0.0.0", port=5010, log_level="info")
