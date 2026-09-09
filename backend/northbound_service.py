import logging
import logging.config
import warnings

import uvicorn

from dotenv import load_dotenv


from apps.northbound_base_app import northbound_app
from utils.logging_utils import get_uvicorn_logging_config


warnings.filterwarnings("ignore", category=UserWarning)
load_dotenv()

logging.config.dictConfig(get_uvicorn_logging_config(categories=["northbound"]))
logger = logging.getLogger("northbound")

if __name__ == "__main__":
    uvicorn.run(northbound_app, host="0.0.0.0", port=5013, log_level="info", log_config=get_uvicorn_logging_config(categories=["northbound"]))
