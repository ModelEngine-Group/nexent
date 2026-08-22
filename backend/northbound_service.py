import uvicorn
import logging
import warnings
from dotenv import load_dotenv
from apps.northbound_base_app import northbound_app
from utils.logging_utils import configure_logging

warnings.filterwarnings("ignore", category=UserWarning)
load_dotenv()


configure_logging(logging.INFO)
logger = logging.getLogger("northbound_service")

if __name__ == "__main__":
    uvicorn.run(northbound_app, host="0.0.0.0", port=5013, log_level="info")