import uvicorn
import logging
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv
load_dotenv()

from services.agent_service import import_default_agents_to_pg
from apps.base_app import app
from utils.logging_utils import configure_logging, configure_elasticsearch_logging


configure_logging(logging.INFO)
configure_elasticsearch_logging()
logger = logging.getLogger("main_service")

if __name__ == "__main__":
    # Scan agents and update to database
    import_default_agents_to_pg()
    uvicorn.run(app, host="0.0.0.0", port=5010, log_level="warning")
