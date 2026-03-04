import logging

from apps.app_factory import create_app
from .northbound_app import router as northbound_router

logger = logging.getLogger("northbound_base_app")

# Create FastAPI app with common configurations
northbound_app = create_app(
    title="Nexent Northbound API",
    description="Northbound APIs for partners",
    version="1.0.0",
    cors_methods=["GET", "POST", "PUT", "DELETE"],
    enable_monitoring=False  # Disable monitoring for northbound API if not needed
)

northbound_app.include_router(northbound_router)
