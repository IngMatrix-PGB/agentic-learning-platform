from agentic_learning_platform.routes.documents import router as documents_router
from agentic_learning_platform.routes.health import router as health_router
from agentic_learning_platform.routes.query import router as query_router
from agentic_learning_platform.routes.query_stream import router as query_stream_router

__all__ = ["documents_router", "health_router", "query_router", "query_stream_router"]
