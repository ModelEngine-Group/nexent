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
    import os
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    log_format = '[%(asctime)s %(levelname)-1s %(name)-1s] %(message)s'
    date_format = '%H:%M:%S'
    formatter = ColorFormatter(log_format, datefmt=date_format)

    # Console output
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File output - save to backend.log in project root directory
    # Project root is one level up from backend/ directory
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_file_path = os.path.join(project_root, 'backend.log')
    try:
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        print(f"[logging_utils] Log file saved to: {log_file_path}")
    except Exception as e:
        print(f"[logging_utils] Failed to create log file handler: {e}")

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
    