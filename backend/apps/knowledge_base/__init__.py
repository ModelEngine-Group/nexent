# Knowledge Base Apps
# Collection of knowledge base retrieval and management related FastAPI applications

from apps.knowledge_base.vectordatabase_app import router as vectordatabase_router
from apps.knowledge_base.datamate_app import router as datamate_router
from apps.knowledge_base.dify_app import router as dify_router

__all__ = [
    "vectordatabase_router",
    "datamate_router",
    "dify_router",
]