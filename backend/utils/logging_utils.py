import logging

class ColorFormatter(logging.Formatter):
    COLOR_MAP = {
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[41m', # Red background
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLOR_MAP.get(record.levelname, '')
        message = super().format(record)
        if color:
            message = f"{color}{message}{self.RESET}"
        return message

def configure_logging(level=logging.INFO):
    """
    Configure root logger with color formatter and stream handler.
    Call this at the top of your main service scripts.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    formatter = ColorFormatter('[%(asctime)s %(levelname)-1s %(name)-1s] %(message)s', datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

def configure_elasticsearch_logging():
    """Configure logging for Elasticsearch client to reduce verbosity"""
    
    # Configure logging for elasticsearch
    logging.getLogger('elastic_transport.transport').setLevel(logging.WARNING)
    
    # Configure logging for urllib3 (used by elasticsearch)
    # logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    # Configure logging for elasticsearch.trace
    # This logger logs the body of requests and responses which can be very verbose
    logging.getLogger('elasticsearch.trace').setLevel(logging.WARNING)
    
    # Configure logging for FastAPI/uvicorn access logs
    # logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    # logging.getLogger('fastapi').setLevel(logging.WARNING) 
    
    # Disable httpx INFO logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    