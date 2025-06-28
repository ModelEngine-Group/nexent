import uvicorn
import logging

from services.agent_service import import_default_agents_to_pg

from apps.base_app import app
from utils.logging_utils import configure_elasticsearch_logging

# Configure logging
configure_elasticsearch_logging()

logger = logging.getLogger("main service")


if __name__ == "__main__":
    # scan agents and update to database
    import_default_agents_to_pg()

    uvicorn.run(app, host="0.0.0.0", port=5010, access_log=False)
