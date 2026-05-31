import logging
import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, status, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from langgraph.types import Command

from optirc.core.config import settings
from optirc.core.error_handlers import (
    RateLimitMiddleware,
    TraceIdMiddleware,
    setup_exception_handlers,
)
from optirc.core.exceptions import FileValidationError, SessionNotFoundError
from optirc.core.state import OverallState
from optirc.core.tracing import configure_langsmith_tracing
from optirc.graphs.parent import build_optigraph, create_checkpointer
from optirc.memory.db_store import db_store
from optirc.memory.redis_store import redis_store
from optirc.api import kg_routes

logger = logging.getLogger(__name__)

# Global graph instance
optigraph: Optional[Any] = None

# Security
security = HTTPBearer(auto_error=False)

# Allowed upload MIME types
ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/csv",
}

# Concurrency semaphore to prevent resource exhaustion
MAX_CONCURRENT_PIPELINES = 10
_pipeline_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PIPELINES)


async def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """Verify API token. In production, use proper JWT or OAuth2."""
    # Simple token check - in production, validate against database or auth service
    expected_token = os.environ.get("OMNIOPS_API_TOKEN", "")
    if not expected_token:
        # Development mode: no token required
        return "dev"
    if credentials is None:
        raise SessionNotFoundError("Authentication required")
    if credentials.credentials != expected_token:
        raise SessionNotFoundError("Invalid authentication token")
    return credentials.credentials


def _validate_upload(file: UploadFile) -> None:
    """Validate uploaded file for security and format."""
    # Check file size (read a bit to verify it's not huge)
    if file.size and file.size > settings.omniops_max_upload_size:
        raise FileValidationError(
            f"File too large: {file.size} bytes (max {settings.omniops_max_upload_size})"
        )

    # Check content type
    content_type = file.content_type or ""
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        # Allow unknown types but log warning; block explicitly wrong types
        if content_type.startswith(("image/", "application/x-executable")):
            raise FileValidationError(
                f"Unsupported file type: {content_type}. Please upload CSV files only."
            )

    # Check filename extension
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        logger.warning("Upload filename does not end with .csv: %s", filename)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global optigraph
    logging.basicConfig(level=getattr(logging, settings.log_level))
    configure_langsmith_tracing()
    checkpointer = await create_checkpointer()
    optigraph = build_optigraph(checkpointer=checkpointer)
    await db_store._init()
    logger.info("OptiGraph initialized, checkpointer type: %s", type(optigraph.checkpointer).__name__)
    yield
    await db_store.close()
    logger.info("Application shutdown")


app = FastAPI(
    title="OptiRCAgent API",
    version="0.1.0",
    lifespan=lifespan,
)

# Register middleware and exception handlers
app.add_middleware(TraceIdMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=60, burst_size=10)
setup_exception_handlers(app)

# Register knowledge graph routes
app.include_router(kg_routes.router)


@app.post("/v1/sessions")
async def create_session(
    file: UploadFile = File(...),
    token: str = Depends(verify_token),
):
    """Upload file and start diagnosis pipeline."""
    # Validate upload
    _validate_upload(file)

    session_id = str(uuid.uuid4())
    upload_dir = settings.omniops_upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{session_id}_{file.filename}")

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    await db_store.create_session(session_id)

    initial_state: OverallState = {
        "session_id": session_id,
        "raw_input": file_path,
        "status": "init",
        "perception_result": None,
        "diagnosis_result": None,
        "diagnosis_validation_result": None,
        "planning_result": None,
        "solution_validation_result": None,
        "human_review_result": None,
        "closure_result": None,
        "pending_human": False,
        "human_decision": None,
        "error_message": None,
        "retry_count": 0,
        "messages": [],
    }

    # Start graph in background with semaphore-controlled concurrency
    config = {"configurable": {"thread_id": session_id}}

    async def _run_pipeline():
        async with _pipeline_semaphore:
            try:
                await optigraph.ainvoke(initial_state, config=config)
            except Exception as e:
                logger.error("Pipeline failed for session %s: %s", session_id, e)
                # Update session with error status
                await db_store.update_session(
                    session_id,
                    status="error",
                    final_result={"error": str(e)},
                )

    asyncio.create_task(_run_pipeline())

    return JSONResponse({
        "session_id": session_id,
        "status": "init",
        "message": "Diagnosis pipeline started",
    })


@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str, token: str = Depends(verify_token)):
    """Get session state."""
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await optigraph.aget_state(config)
    except Exception as e:
        logger.warning("Get session failed: %s", e)
        raise SessionNotFoundError(f"Session {session_id} not found") from e

    if not state:
        raise SessionNotFoundError(f"Session {session_id} not found")

    values = state.values
    return JSONResponse({
        "session_id": session_id,
        "status": values.get("status", "unknown"),
        "perception": values.get("perception_result"),
        "diagnosis": values.get("diagnosis_result"),
        "diagnosis_validation": values.get("diagnosis_validation_result"),
        "planning": values.get("planning_result"),
        "solution_validation": values.get("solution_validation_result"),
        "human_review": values.get("human_review_result"),
        "closure": values.get("closure_result"),
        "pending_human": values.get("pending_human", False),
        "human_decision": values.get("human_decision"),
    })


@app.get("/v1/sessions/{session_id}/review-package")
async def get_review_package(session_id: str, token: str = Depends(verify_token)):
    """Get review package for human review."""
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await optigraph.aget_state(config)
    except Exception as e:
        logger.warning("Get review package failed: %s", e)
        raise SessionNotFoundError(f"Session {session_id} not found") from e

    if not state:
        raise SessionNotFoundError(f"Session {session_id} not found")

    values = state.values
    return JSONResponse({
        "session_id": session_id,
        "diagnosis": values.get("diagnosis_result"),
        "planning": values.get("planning_result"),
        "diagnosis_validation": values.get("diagnosis_validation_result"),
        "solution_validation": values.get("solution_validation_result"),
        "timeout_seconds": settings.hitl_timeout_seconds,
    })


@app.post("/v1/sessions/{session_id}/human-decision")
async def submit_human_decision(
    session_id: str,
    decision: str = Form(...),
    notes: str = Form(""),
    token: str = Depends(verify_token),
):
    """Submit human decision to resume pipeline."""
    from optirc.core.exceptions import NoActiveInterruptError

    config = {"configurable": {"thread_id": session_id}}

    # Verify there is an active interrupt
    try:
        state = await optigraph.aget_state(config)
    except Exception as e:
        logger.warning("Interrupt check failed: %s", e)
        raise SessionNotFoundError(f"Session {session_id} not found") from e

    if not state or not state.tasks:
        raise NoActiveInterruptError("No active interrupt found for this session")

    has_interrupt = any(
        getattr(task, "interrupts", None) for task in state.tasks
    )
    if not has_interrupt:
        raise NoActiveInterruptError("No active interrupt found for this session")

    try:
        result = await optigraph.ainvoke(
            Command(resume={"decision": decision, "notes": notes}),
            config=config,
        )
        return JSONResponse({
            "session_id": session_id,
            "status": result.get("status", "unknown"),
            "human_decision": decision,
            "message": "Human decision processed, pipeline resumed",
        })
    except Exception as e:
        logger.error("Resume failed: %s", e)
        raise


@app.get("/v1/sessions/{session_id}/trace")
async def get_trace(session_id: str, token: str = Depends(verify_token)):
    """Get execution trace."""
    config = {"configurable": {"thread_id": session_id}}
    try:
        history = await optigraph.aget_state_history(config)
    except Exception as e:
        logger.warning("Get trace failed: %s", e)
        raise SessionNotFoundError(f"Session {session_id} not found") from e

    trace = []
    for item in history:
        values = item.values if hasattr(item, "values") else {}
        trace.append({
            "step": values.get("status", "unknown"),
            "timestamp": str(item.config.get("checkpoint_ns", "")) if hasattr(item, "config") else "",
        })
    return JSONResponse({
        "session_id": session_id,
        "trace": trace,
    })


@app.get("/v1/health")
async def health():
    """Health check endpoint with detailed subsystem status."""
    from optirc.core.llm_client import llm_client
    from optirc.core.circuit_breaker import circuit_registry

    checkpointer_type = type(optigraph.checkpointer).__name__ if optigraph else "unknown"

    # Check LLM health
    llm_health = {"status": "unknown"}
    try:
        llm_metrics = llm_client.get_health_metrics()
        primary_open = llm_metrics["primary"]["circuit"]["state"] == "open"
        backup_open = llm_metrics["backup"]["circuit"]["state"] == "open"
        if primary_open and backup_open:
            llm_health = {"status": "degraded", "reason": "All circuits open"}
        elif primary_open:
            llm_health = {"status": "degraded", "reason": "Primary circuit open, using backup"}
        else:
            llm_health = {"status": "healthy"}
        llm_health["metrics"] = llm_metrics
    except Exception as e:
        llm_health = {"status": "error", "reason": str(e)}

    # Circuit breaker metrics
    circuit_metrics = circuit_registry.all_metrics()

    # Database health
    db_health = {"status": "unknown"}
    try:
        if db_store._initialized and db_store._pool is not None:
            db_health = {"status": "healthy", "pool_size": db_store._pool.get_size()}
        else:
            db_health = {"status": "degraded", "reason": "Database not initialized"}
    except Exception as e:
        db_health = {"status": "error", "reason": str(e)}

    # Knowledge Graph health
    kg_health = {"status": "unknown"}
    try:
        from optirc.knowledge.neo4j_client import neo4j_client
        kg_result = await neo4j_client.query("RETURN 1 AS health")
        kg_health = {"status": "healthy"} if kg_result else {"status": "degraded"}
    except Exception as e:
        kg_health = {"status": "degraded", "reason": str(e)}

    return JSONResponse({
        "status": "healthy",
        "checkpointer": checkpointer_type,
        "llm": llm_health,
        "circuits": circuit_metrics,
        "database": db_health,
        "knowledge_graph": kg_health,
        "concurrency": {
            "max_pipelines": MAX_CONCURRENT_PIPELINES,
            "available_slots": _pipeline_semaphore._value,
        },
    })


@app.get("/v1/health/ready")
async def readiness():
    """Kubernetes-style readiness probe."""
    checks = {
        "graph": optigraph is not None,
        "db": db_store._initialized and db_store._pool is not None,
    }
    all_ready = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ready else 503,
        content={
            "ready": all_ready,
            "checks": checks,
        },
    )


@app.websocket("/v1/ws/human-review")
async def human_review_ws(websocket: WebSocket):
    """WebSocket for real-time human review notifications."""
    await websocket.accept()
    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected for real-time updates",
        })

        while True:
            # Wait for client messages (ping/heartbeat)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.startswith("subscribe:"):
                session_id = data.split(":", 1)[1]
                await websocket.send_json({
                    "type": "subscribed",
                    "session_id": session_id,
                })
            else:
                await websocket.send_json({
                    "type": "echo",
                    "message": data,
                })
    except Exception as e:
        logger.debug("WebSocket connection closed: %s", e)
        await websocket.close()


@app.get("/v1/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    from optirc.core.metrics import metrics
    content, content_type = metrics.get_prometheus_metrics()
    return JSONResponse(
        content=content.decode("utf-8"),
        media_type=content_type,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "optirc.api.main:app",
        host=settings.omniops_api_host,
        port=settings.omniops_api_port,
        reload=settings.omniops_api_debug,
    )
