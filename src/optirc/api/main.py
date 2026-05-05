import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, status
from fastapi.responses import JSONResponse
from langgraph.types import Command

from optirc.core.config import settings
from optirc.core.state import OverallState
from optirc.core.tracing import configure_langsmith_tracing
from optirc.graphs.parent import build_optigraph, create_checkpointer
from optirc.memory.db_store import db_store
from optirc.memory.redis_store import redis_store

logger = logging.getLogger(__name__)

# Global graph instance
optigraph: Optional[Any] = None


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


@app.post("/v1/sessions")
async def create_session(file: UploadFile = File(...)):
    """Upload file and start diagnosis pipeline."""
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
        "messages": [],
    }

    # Start graph in background
    config = {"configurable": {"thread_id": session_id}}
    import asyncio
    asyncio.create_task(optigraph.ainvoke(initial_state, config=config))

    return JSONResponse({
        "session_id": session_id,
        "status": "init",
        "message": "Diagnosis pipeline started",
    })


@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session state."""
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await optigraph.aget_state(config)
        values = state.values if state else {}
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
    except Exception as e:
        logger.warning("Get session failed: %s", e)
        return JSONResponse(
            {"error": "Session not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )


@app.get("/v1/sessions/{session_id}/review-package")
async def get_review_package(session_id: str):
    """Get review package for human review."""
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await optigraph.aget_state(config)
        values = state.values if state else {}
        return JSONResponse({
            "session_id": session_id,
            "diagnosis": values.get("diagnosis_result"),
            "planning": values.get("planning_result"),
            "diagnosis_validation": values.get("diagnosis_validation_result"),
            "solution_validation": values.get("solution_validation_result"),
            "timeout_seconds": settings.hitl_timeout_seconds,
        })
    except Exception as e:
        logger.warning("Get review package failed: %s", e)
        return JSONResponse(
            {"error": "Session not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )


@app.post("/v1/sessions/{session_id}/human-decision")
async def submit_human_decision(
    session_id: str,
    decision: str = Form(...),
    notes: str = Form(""),
):
    """Submit human decision to resume pipeline."""
    config = {"configurable": {"thread_id": session_id}}

    # Verify there is an active interrupt
    try:
        state = await optigraph.aget_state(config)
        if not state or not state.tasks:
            return JSONResponse(
                {"error": "No active interrupt found"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        has_interrupt = any(
            getattr(task, "interrupts", None) for task in state.tasks
        )
        if not has_interrupt:
            return JSONResponse(
                {"error": "No active interrupt found"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    except Exception as e:
        logger.warning("Interrupt check failed: %s", e)
        return JSONResponse(
            {"error": "Failed to check interrupt state"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

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
        return JSONResponse(
            {"error": str(e)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@app.get("/v1/sessions/{session_id}/trace")
async def get_trace(session_id: str):
    """Get execution trace."""
    config = {"configurable": {"thread_id": session_id}}
    try:
        history = await optigraph.aget_state_history(config)
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
    except Exception as e:
        logger.warning("Get trace failed: %s", e)
        return JSONResponse({"session_id": session_id, "trace": []})


@app.get("/v1/health")
async def health():
    """Health check endpoint."""
    checkpointer_type = type(optigraph.checkpointer).__name__ if optigraph else "unknown"
    return JSONResponse({
        "status": "healthy",
        "checkpointer": checkpointer_type,
    })


@app.websocket("/v1/ws/human-review")
async def human_review_ws(websocket: WebSocket):
    """WebSocket for real-time human review notifications."""
    await websocket.accept()
    try:
        while True:
            # Simple ping-pong to keep connection alive
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except Exception:
        await websocket.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "optirc.api.main:app",
        host=settings.omniops_api_host,
        port=settings.omniops_api_port,
        reload=settings.omniops_api_debug,
    )
