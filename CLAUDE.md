# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OptiRCAgent is a multi-agent optical network operations assistant built on LangGraph. It uses a compile-time graph orchestration with subgraph-level memory isolation to perform alarm root cause analysis and generate fix recommendations, supporting human-in-the-loop (HITL) checkpoints and knowledge closure.

## Commands

```bash
# Install dependencies
uv sync

# Run API server (development)
uv run python -m optirc.api.main

# Run tests
uv run pytest tests/ -v

# Run single test file
uv run pytest tests/unit/test_diagnosis.py -v

# Lint
uv run black src/ tests/
uv run isort src/ tests/
uv run mypy src/

# Docker full stack (Postgres, Redis, Neo4j, API, Frontend, Nginx)
docker compose up --build -d
curl http://localhost:8000/v1/health

# Local demo (no services required)
uv run python demo.py

# Individual docker services
make docker-up / make docker-down
```

## Architecture

### Graph Architecture (LangGraph)

The system is structured as a **parent graph** (`src/optirc/graphs/parent.py`) that orchestrates **7 subgraphs**, each with its own isolated internal state (TypedDict). Parent graph state is `OverallState`.

```
perception → diagnosis → diagnosis_validation
                             ↓ (routing)
              planning → solution_validation
                             ↓ (routing)
              human_review → closure → END
```

**Subgraph isolation**: Each subgraph (perception, diagnosis, planning, etc.) has a private TypedDict internal state (`PerceptionInternalState`, `DiagnosisInternalState`, etc. in `src/optirc/core/state.py`). This prevents memory leakage between agents. The parent graph only passes scalar values or serialized dicts between subgraphs via wrapper nodes (`perception_node`, `diagnosis_node`, etc.).

**Conditional routing**: After `diagnosis_validation`, the graph routes back to `diagnosis` (retry), `planning` (proceed), or `human_review` (escalate) based on `suggested_action`. After `solution_validation`, routes back to `planning` if `needs_replan` is true. After `human_review`, routes to `closure` (approved), back to `planning` (rejected), or terminates.

### HITL via `langgraph.types.interrupt`

The `human_review` subgraph calls `interrupt(review_package)` in `wait_human_decision_node`. This **pauses the entire graph** and serializes the checkpoint. The API endpoint `POST /v1/sessions/{id}/human-decision` resumes with `Command(resume={"decision": "...", "notes": "..."})`.

### State Management

- **In-memory (default)**: `MemorySaver` checkpointing, lost on restart
- **Postgres (production)**: `AsyncPostgresSaver` via `create_checkpointer()` in `parent.py` — falls back to `MemorySaver` if connection fails
- **Redis**: Used for ephemeral cache (`src/optirc/memory/redis_store.py`)
- **Postgres**: Used for session persistence (`src/optirc/memory/db_store.py`)

### LLM Client (`src/optirc/core/llm_client.py`)

`LLMClient` wraps OpenAI-compatible API. **Primary**: OpenRouter (`https://openrouter.ai/api/v1`). **Backup**: ModelScope (`https://api-inference.modelscope.cn/v1`). Auto-failover on exception. Interface methods: `generate_json()`, `generate_text()`, `embed()`, `ocr()` (vision).

### Knowledge Stack

- **Neo4j** (`src/optirc/knowledge/neo4j_client.py`): Knowledge graph for topology and causal relationships
- **ChromaDB** (`src/optirc/rag/vector_store.py`): Vector store for SOP and alarm knowledge retrieval
- **Embedding**: Configured via `embedding_model` in settings

### API Design

All state flows through the LangGraph checkpointer. API endpoints call `optigraph.aget_state(config)` or `optigraph.ainvoke(Command(...))` with `{"configurable": {"thread_id": session_id}}` — thread_id IS the session_id.

## File Layout

```
src/optirc/
├── api/main.py              # FastAPI app, all REST endpoints
├── core/
│   ├── config.py            # Settings (pydantic-settings, .env)
│   ├── state.py             # All TypedDict state schemas (OverallState + 7 internal states)
│   ├── llm_client.py        # LLMClient (primary/backup failover)
│   ├── tracing.py           # LangSmith tracing config
│   ├── topology_manager.py  # Network topology management
│   └── encoding.py          # CSV encoding detection
├── graphs/
│   ├── parent.py             # Parent graph + wrapper nodes + checkpointer factory
│   └── subgraphs/
│       ├── perception.py    # CSV/OCR parsing
│       ├── diagnosis.py     # Root cause analysis
│       ├── diagnosis_validation.py
│       ├── planning.py      # Fix plan generation
│       ├── solution_validation.py
│       ├── human_review.py  # interrupt() for HITL
│       └── closure.py       # Knowledge extraction and storage
├── models/session.py        # Session data models
├── memory/
│   ├── redis_store.py        # Redis cache
│   └── db_store.py          # Postgres session persistence
├── knowledge/               # Neo4j client + KG queries
├── rag/vector_store.py      # ChromaDB vector operations
├── ingestion/csv_parser.py # CSV parsing
└── tools/registry.py        # Tool registration
```

## Key Patterns

- Each subgraph is built with `StateGraph(InternalState).compile()` and invoked via `subgraph.ainvoke(sub_input)` in a parent wrapper node
- API uses `asyncio.create_task(optigraph.ainvoke(...))` for fire-and-forget pipeline execution
- Session state is queried via `optigraph.aget_state(config)` — NOT stored in a separate DB
- All config comes from `.env` via `pydantic-settings`; no hardcoded URLs

## Dependencies

- **LangGraph 0.2.50+**: graph orchestration, interrupts, checkpointing
- **FastAPI + Uvicorn**: REST API + WebSocket
- **PostgreSQL (asyncpg) + Redis**: persistence + cache
- **Neo4j + ChromaDB**: knowledge graph + vector store
- **OpenAI SDK (AsyncOpenAI)**: LLM calls