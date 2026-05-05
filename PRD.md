# OptiRCAgent — LangGraph 多 Agent 光网络运维辅助系统 PRD

## 1. 项目概述

**目标**：构建一个基于 **LangGraph 编译时图编排 + 子图记忆隔离** 架构的多 Agent 系统，辅助光网络运维团队完成告警根因定位与修复建议生成，支持人工审核断点与知识闭环。

**核心特征**：
- **编译时图编排**：Agent 流水线在代码层面显式定义，非运行时消息队列拼装
- **子图记忆隔离**：每个 Agent 拥有私有 `InternalState`，RAG 检索文档、知识图谱子图、LLM 思考链等中间记忆不跨 Agent 泄漏
- **原生 HITL**：利用 `langgraph.interrupt` 在审核节点自动暂停，支持外部 API 注入决策后精确恢复
- **统一 LLM 接口**：基于 OpenAI API 格式的 SDK 调用，支持 OpenRouter 与 ModelScope 双后端

---

## 2. 技术栈

| 组件 | 选型 | 版本约束 |
|------|------|----------|
| 语言 | Python | 3.8+（typing 必须用 `List/Optional/Dict`，禁用内置泛型 `list\|None/dict`） |
| 包管理 | uv | latest |
| Agent 框架 | LangGraph | >=0.2.0 |
| LLM SDK | openai (AsyncOpenAI) | >=1.30.0 |
| API 框架 | FastAPI + Uvicorn | >=0.110.0 |
| 向量数据库 | postgres的pgvector 
| 图数据库 | Neo4j Community | 5 |
| 缓存 | Redis | 7 |
| 配置管理 | Pydantic Settings | >=2.1.0，全部字段从 `.env` 读取 |
| 测试 | pytest + pytest-asyncio | >=8.0.0 |

---

## 3. 架构设计

### 3.1 父图（OptiGraph）编排

```
CSV/OCR 上传
     │
     ▼
┌─────────────┐
│  感知子图    │  ──▶ CSV解析、表头标准化、拓扑ID提取、OCR文本提取
│ (Perception)│
└─────────────┘
     │
     ▼
┌─────────────┐
│  诊断子图    │  ──▶ RAG检索 + 知识图谱查询 + LLM根因推理
│ (Diagnosis) │
└─────────────┘
     │
     ▼
┌─────────────┐
│  诊断校验子图 │  ──▶ 验证诊断置信度、证据完整性、根因可信度
│(DiagValidate)│      不通过则退回诊断重试，不确定则标记人工介入
└─────────────┘
     │
     ▼
┌─────────────┐
│  方案子图    │  ──▶ 基于诊断与影响范围生成修复建议 + 回滚步骤
│ (Planning)  │
└─────────────┘
     │
     ▼
┌─────────────┐
│  方案校验子图 │  ──▶ 验证方案与诊断一致性、可行性、资源匹配、风险评估
│(PlanValidate)│      不通过则退回方案重试
└─────────────┘
     │
     ▼
┌─────────────┐
│  人工审核子图 │  ──▶ interrupt 断点，等待外部人工决策
│(HumanReview) │
└─────────────┘
     │
     ▼
┌─────────────┐
│  回收子图    │  ──▶ 知识抽取、写入ChromaDB向量库、写入Neo4j图谱
│ (Closure)   │
└─────────────┘
```

### 3.2 状态隔离原则

- **父图 `OverallState`**：仅保存跨阶段传递的**最终结果字段**，字段名与子图私有字段零重叠
- **子图 `InternalState`**：包含完整的私有中间状态（检索文档、思考链、图谱子图、候选方案等），子图对外只暴露输出节点定义的字段

---

## 4. 状态设计（Python 3.8 兼容）

### 4.1 父图全局状态

```python
from typing import Optional, List, Dict, Any, TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class OverallState(TypedDict):
    session_id: str
    raw_input: str                    # 上传文件路径或OCR文本
    status: str                       # 状态机当前状态
    perception_result: Optional[Dict[str, Any]]
    diagnosis_result: Optional[Dict[str, Any]]
    diagnosis_validation_result: Optional[Dict[str, Any]]   # 诊断校验最终结果
    planning_result: Optional[Dict[str, Any]]
    solution_validation_result: Optional[Dict[str, Any]]    # 方案校验最终结果
    human_review_result: Optional[Dict[str, Any]]
    closure_result: Optional[Dict[str, Any]]
    pending_human: bool
    human_decision: Optional[str]     # "approved" | "rejected" | "escalated"
    error_message: Optional[str]
    messages: Annotated[List[BaseMessage], add_messages]
```

### 4.2 各子图私有状态

```python
# 感知子图
class PerceptionInternalState(TypedDict):
    raw_input: str                    # 文件路径或原始文本
    detected_encoding: Optional[str]
    raw_rows: Optional[List[Dict[str, Any]]]
    normalized_headers: Optional[List[str]]
    topology_ids: Optional[List[str]]
    ocr_text: Optional[str]           # OCR提取的文本
    perception_summary: Optional[Dict[str, Any]]

# 诊断子图（记忆隔离核心）
class DiagnosisInternalState(TypedDict):
    perception_summary: Dict[str, Any]
    query_text: Optional[str]
    query_embedding: Optional[List[float]]
    retrieved_docs: Optional[List[Dict[str, Any]]]      # 私有：RAG结果
    kg_subgraph: Optional[Dict[str, Any]]               # 私有：Neo4j子图
    candidate_causes: Optional[List[Dict[str, Any]]]    # 私有：候选根因
    reasoning_chain: Optional[str]                      # 私有：CoT
    llm_raw_output: Optional[str]                       # 私有：原始LLM输出
    root_cause: Optional[str]                           # 输出到父图
    confidence: Optional[float]
    evidence: Optional[List[str]]
    recommended_action: Optional[str]

# 诊断校验子图
class DiagnosisValidationInternalState(TypedDict):
    diagnosis_result: Dict[str, Any]
    # 私有中间状态
    confidence_threshold: float       # 校验规则：最低置信度阈值
    evidence_completeness_score: Optional[float]
    llm_revalidation_output: Optional[str]   # LLM二次验证思考链
    # 输出到父图
    validation_passed: Optional[bool]
    validation_notes: Optional[str]
    suggested_action: Optional[str]   # "proceed" | "retry_diagnosis" | "needs_human"

# 方案子图
class PlanningInternalState(TypedDict):
    diagnosis_result: Dict[str, Any]
    diagnosis_validation: Dict[str, Any]
    retrieved_sops: Optional[List[Dict[str, Any]]]      # 私有：标准作业程序
    candidate_plans: Optional[List[Dict[str, Any]]]     # 私有：候选方案
    risk_assessment: Optional[str]                      # 私有：风险评估
    final_plan: Optional[Dict[str, Any]]                # 输出到父图
    rollback_procedure: Optional[str]

# 方案校验子图
class SolutionValidationInternalState(TypedDict):
    planning_result: Dict[str, Any]
    diagnosis_result: Dict[str, Any]
    # 私有中间状态
    consistency_matrix: Optional[Dict[str, Any]]        # 方案-诊断一致性检查
    feasibility_score: Optional[float]
    resource_match_check: Optional[bool]
    llm_evaluation_output: Optional[str]
    # 输出到父图
    solution_valid: Optional[bool]
    risk_level: Optional[str]         # "low" | "medium" | "high"
    validation_notes: Optional[str]
    needs_replan: Optional[bool]

# 人工审核子图
class HumanReviewInternalState(TypedDict):
    session_id: str
    planning_result: Dict[str, Any]
    solution_validation: Dict[str, Any]
    diagnosis_result: Dict[str, Any]
    review_package: Optional[Dict[str, Any]]
    decision: Optional[str]
    reviewer_notes: Optional[str]
    approved_at: Optional[str]

# 回收子图
class ClosureInternalState(TypedDict):
    session_id: str
    full_case: Dict[str, Any]
    extracted_knowledge: Optional[List[Dict[str, Any]]]
    stored_to_vector_db: Optional[bool]
    stored_to_graph_db: Optional[bool]
    closure_summary: Optional[str]
```

---

## 5. 子图详细设计

### 5.1 感知子图（Perception Subgraph）

**职责**：文件类型判断、CSV编码检测与解析、表头标准化、拓扑ID提取、OCR文本提取

**节点**：
| 节点 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `detect_input_type` | `raw_input` | `input_type` | 判断是CSV文件还是图片 |
| `detect_encoding` | `raw_input` | `detected_encoding` | chardet检测CSV编码 |
| `parse_csv` | `raw_input`, `detected_encoding` | `raw_rows`, `normalized_headers`, `topology_ids` | csv.DictReader解析 |
| `extract_ocr` | `raw_input` | `ocr_text` | 若输入为图片，调用OCR模型提取文本 |
| `summarize` | 上述全部 | `perception_summary` | 构造统一摘要 |

**边**：`detect_input_type` 分支 → `parse_csv` 或 `extract_ocr` → `summarize`

### 5.2 诊断子图（Diagnosis Subgraph）

**职责**：RAG检索 + 知识图谱查询 + LLM根因推理

**节点**：
| 节点 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `build_query` | `perception_summary` | `query_text`, `query_embedding` | 拼接告警类型+设备ID+描述，生成向量 |
| `retrieve_rag` | `query_text`, `query_embedding` | `retrieved_docs` | ChromaDB相似度检索（top_k=5） |
| `retrieve_kg` | `topology_ids` | `kg_subgraph` | Neo4j子图查询（depth=2） |
| `analyze` | `retrieved_docs`, `kg_subgraph`, `perception_summary` | `candidate_causes`, `reasoning_chain`, `llm_raw_output` | LLM生成JSON |
| `finalize` | `candidate_causes` | `root_cause`, `confidence`, `evidence`, `recommended_action` | 提炼最佳候选 |

**边**：
- `build_query` → `retrieve_rag`
- `build_query` → `retrieve_kg`
- `retrieve_rag` → `analyze`
- `retrieve_kg` → `analyze`
- `analyze` → `finalize`

**记忆隔离点**：`retrieved_docs`, `kg_subgraph`, `reasoning_chain`, `candidate_causes`, `llm_raw_output` 均为私有字段，父图 wrapper 节点只读取 `finalize` 输出的 4 个字段。

### 5.3 诊断校验子图（Diagnosis Validation Subgraph）

**职责**：验证诊断结果的置信度、证据完整性、根因可信度

**节点**：
| 节点 | 说明 |
|------|------|
| `rule_check` | 规则校验：confidence >= 0.6，evidence 非空，root_cause 非"未知" |
| `llm_revalidate` | LLM二次验证根因与证据链的合理性 |
| `finalize_validation` | 输出 `validation_passed` + `validation_notes` + `suggested_action` |

**输出到父图**：
- `validation_passed`: bool
- `validation_notes`: str
- `suggested_action`: "proceed" | "retry_diagnosis" | "needs_human"

### 5.4 方案子图（Planning Subgraph）

**职责**：基于诊断结果生成修复建议与回滚步骤

**节点**：
| 节点 | 说明 |
|------|------|
| `retrieve_sops` | ChromaDB检索标准作业程序（SOP），filter_type="sop" |
| `generate_candidates` | LLM生成2-3个候选修复方案 |
| `finalize_plan` | 输出 `final_plan` + `rollback_procedure` |

### 5.5 方案校验子图（Solution Validation Subgraph）

**职责**：验证方案与诊断的一致性、可行性、资源匹配、风险评估

**节点**：
| 节点 | 说明 |
|------|------|
| `consistency_check` | 检查方案步骤是否直接关联 root_cause |
| `feasibility_check` | 检查所需资源、时间窗口、操作权限 |
| `risk_evaluation` | LLM评估执行风险，输出 risk_level |
| `finalize_solution_validation` | 输出 `solution_valid` + `risk_level` + `validation_notes` + `needs_replan` |

**输出到父图**：
- `solution_valid`: bool
- `risk_level`: "low" | "medium" | "high"
- `validation_notes`: str
- `needs_replan`: bool

### 5.6 人工审核子图（Human Review Subgraph）

**核心机制**：`langgraph.interrupt`

**节点**：
| 节点 | 说明 |
|------|------|
| `prepare_review` | 组装审核材料包（诊断+方案+两个校验结果） |
| `wait_human_decision` | 调用 `interrupt(payload)` 暂停执行，等待 `Command(resume=...)` |

**恢复方式**：
```python
await graph.ainvoke(
    Command(resume={"decision": "approved", "notes": "同意执行"}),
    config={"configurable": {"thread_id": session_id}}
)
```

### 5.7 回收子图（Closure Subgraph）

**职责**：知识抽取、写入ChromaDB、写入Neo4j、生成闭环摘要

**节点**：
| 节点 | 说明 |
|------|------|
| `extract_knowledge` | 从全案提取结构化知识片段 |
| `store_vector` | 写入 ChromaDB 向量库 |
| `store_graph` | 写入 Neo4j 图谱（案例-根因-设备关系） |
| `summarize` | 输出 `closure_summary` |

---

## 6. 父图编排器（OptiGraph）

### 6.1 节点封装器（状态转换闸门）

每个子图通过 async wrapper 函数嵌入父图，严格控制输入输出：

```python
async def diagnosis_node(state: OverallState) -> Dict[str, Any]:
    sub_input = {"perception_summary": state["perception_result"]}
    result = await diagnosis_subgraph.ainvoke(sub_input)
    return {
        "diagnosis_result": {
            "root_cause": result["root_cause"],
            "confidence": result["confidence"],
            "evidence": result["evidence"],
            "recommended_action": result["recommended_action"],
        },
        "status": "diagnosed",
    }

async def diagnosis_validation_node(state: OverallState) -> Dict[str, Any]:
    sub_input = {"diagnosis_result": state["diagnosis_result"]}
    result = await diagnosis_validation_subgraph.ainvoke(sub_input)
    return {
        "diagnosis_validation_result": {
            "validation_passed": result["validation_passed"],
            "validation_notes": result["validation_notes"],
            "suggested_action": result["suggested_action"],
        },
        "status": "diagnosis_validated",
    }
```

### 6.2 条件边路由

| 条件边 | 逻辑 |
|--------|------|
| `diagnosis_validation` → `planning` | `suggested_action == "proceed"` |
| `diagnosis_validation` → `diagnosis` | `suggested_action == "retry_diagnosis"`（退回重试） |
| `diagnosis_validation` → `human_review` | `suggested_action == "needs_human"`（不确定，直接升人工） |
| `solution_validation` → `human_review` | `solution_valid == True` |
| `solution_validation` → `planning` | `needs_replan == True`（退回方案重制） |
| `human_review` → `closure` | `human_decision == "approved"` |
| `human_review` → `planning` | `human_decision == "rejected"`（整体退回重制） |
| `human_review` → `END` | `human_decision == "escalated"` |

### 6.3 Checkpointer 配置

- **生产**：`AsyncPostgresSaver`（PostgreSQL 后端，支持多实例共享状态与断点续跑）
- **降级/Demo**：`MemorySaver`（内存存储，服务重启丢失）

```python
try:
    checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
    await checkpointer.setup()
except Exception:
    checkpointer = MemorySaver()
```

---

## 7. LLM 客户端设计（统一 OpenAI API 格式）

### 7.1 设计原则

- **统一 SDK**：全部使用 `openai.AsyncOpenAI` 客户端调用
- **双后端**：主链路 OpenRouter，备用链路 ModelScope（均兼容 OpenAI API 格式）
- **配置驱动**：模型名称、API Key、Base URL 全部从 `.env` 读取，代码中硬编码零模型名称

### 7.2 配置映射（.env）

```bash
# 主链路（OpenRouter）
LLM_PROVIDER=openrouter
LLM_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
OPENROUTER_API_KEY=sk-or-v1-xxx

# 备用链路（ModelScope）
LLM_BACKUP_PROVIDER=openrouter          # 实际指向 modelscope 兼容端点
LLM_BACKUP_MODEL=MiniMax/MiniMax-M2.7
LLM_BACKUP_API_KEY=ms-b2fe34b0-xxx
LLM_BACKUP_BASE_URL=https://api-inference.modelscope.cn/v1

# OCR（OpenRouter兼容端点）
OCR_API_KEY=sk-or-v1-xxx
OCR_MODEL=baidu/qianfan-ocr-fast:free

# Embedding（OpenRouter兼容端点）
EMBEDDING_API_KEY=sk-or-v1-xxx
EMBEDDING_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free
```

### 7.3 客户端实现

```python
from openai import AsyncOpenAI
from typing import Dict, Any, Optional

class LLMClient:
    """统一 LLM 客户端：OpenAI API 格式，支持主备双后端自动降级。"""
    
    def __init__(self):
        # 主客户端：OpenRouter
        self.primary = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
        self.primary_model = settings.llm_model
        
        # 备用客户端：ModelScope
        self.backup = AsyncOpenAI(
            base_url=settings.llm_backup_base_url,
            api_key=settings.llm_backup_api_key,
        )
        self.backup_model = settings.llm_backup_model
    
    async def generate_json(
        self,
        system: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """优先主模型，异常时自动降级到备用模型。"""
        async def _call(client: AsyncOpenAI, model_name: str) -> Dict[str, Any]:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            import json
            return json.loads(content)
        
        try:
            return await _call(self.primary, model or self.primary_model)
        except Exception:
            return await _call(self.backup, self.backup_model)
    
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Embedding 接口，使用配置的 EMBEDDING_MODEL。"""
        response = await self.primary.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]
    
    async def ocr(self, image_base64: str) -> str:
        """OCR 接口，使用配置的 OCR_MODEL（通过 vision API 调用）。"""
        response = await self.primary.chat.completions.create(
            model=settings.ocr_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "提取图片中的所有文本和表格内容"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                ],
            }],
        )
        return response.choices[0].message.content
```

### 7.4 使用方式

```python
from omniops.core.llm_client import llm_client

# 诊断子图中调用
result = await llm_client.generate_json(
    system="你是光网络故障诊断专家...",
    user_message=context_text,
)
```

---

## 8. API 接口定义

### 8.1 上传并启动诊断

```
POST /v1/sessions
Content-Type: multipart/form-data

file: <CSV文件或图片>

Response:
{
    "session_id": "uuid",
    "status": "init",
    "message": "诊断流水线已启动"
}
```

### 8.2 查询会话状态

```
GET /v1/sessions/{session_id}

Response:
{
    "session_id": "uuid",
    "status": "diagnosis_validated",
    "perception": {...},
    "diagnosis": {...},
    "diagnosis_validation": {...},
    "planning": {...},
    "solution_validation": {...},
    "human_review": {...},
    "closure": {...},
    "pending_human": false,
    "human_decision": null
}
```

### 8.3 获取待审核材料包

```
GET /v1/sessions/{session_id}/review-package

Response:
{
    "session_id": "uuid",
    "diagnosis": {...},
    "planning": {...},
    "diagnosis_validation": {...},
    "solution_validation": {...},
    "timeout_seconds": 600
}
```

### 8.4 提交人工决策（恢复中断）

```
POST /v1/sessions/{session_id}/human-decision
Content-Type: application/x-www-form-urlencoded

decision=approved&notes=方案合理，同意执行

Response:
{
    "session_id": "uuid",
    "status": "closed",
    "human_decision": "approved",
    "message": "人工决策已处理，流水线恢复"
}
```

### 8.5 获取执行 Trace

```
GET /v1/sessions/{session_id}/trace

Response:
{
    "session_id": "uuid",
    "trace": [
        {"step": "perception", "timestamp": "...", "status": "perceived"},
        {"step": "diagnosis", "timestamp": "...", "status": "diagnosed"},
        {"step": "diagnosis_validation", "timestamp": "...", "status": "diagnosis_validated"},
        {"step": "planning", "timestamp": "...", "status": "planned"},
        {"step": "solution_validation", "timestamp": "...", "status": "solution_validated"},
        {"step": "human_review", "timestamp": "...", "status": "human_reviewed"},
        {"step": "closure", "timestamp": "...", "status": "closed"}
    ]
}
```

### 8.6 WebSocket 实时推送

```
WS /v1/ws/human-review
```

向前端实时广播人工审核任务到达事件。

---

## 9. 数据持久化

### 9.1 LangGraph Checkpointer（状态机级）

- **后端**：`AsyncPostgresSaver` 自动管理 `checkpoint`, `checkpoint_blobs`, `checkpoint_writes` 表
- **作用**：保存每个 step 的状态快照，支持 `aget_state_history` 审计与 `aget_state` 断点续跑

### 9.2 业务持久化（应用级）

**表 `opticrc_sessions`**：
| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | TEXT PK | 会话 ID |
| status | TEXT | 当前状态 |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |
| final_result | JSONB | 最终结果摘要 |

**表 `opticrc_conversations`**：
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL PK | 自增 ID |
| session_id | TEXT FK | 关联会话 |
| agent_name | TEXT | Agent 名称 |
| step | TEXT | 步骤 |
| input_payload | JSONB | 输入 |
| output_payload | JSONB | 输出 |
| created_at | TIMESTAMPTZ | 时间 |

### 9.3 Redis 缓存

- 会话状态短期缓存（TTL 60s），加速前端轮询
- Pub/Sub 频道 `opticrc:human_review`，推送审核任务到达

---

## 10. Docker 部署

### 10.1 服务拓扑

| 服务 | 端口 | 说明 |
|------|------|------|
| nginx | 80 | 反向代理（`/`→前端，`/v1/`→API，`/v1/ws/`→WS） |
| api | 8000 | FastAPI + LangGraph |
| postgres | 5432 | PostgreSQL + pgvector |
| redis | 6379 | 缓存 |
| neo4j | 7474/7687 | 图数据库 |
| frontend | 3000 | Next.js（nginx 后） |

### 10.2 启动命令

```bash
# 全栈启动
docker compose up --build -d

# 查看 API 日志
docker compose logs -f api

# 健康检查
curl http://localhost/v1/health
```

### 10.3 环境变量（全部来自 .env）

```bash
# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/omniops

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM 主链路（OpenRouter）
LLM_PROVIDER=openrouter
LLM_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
OPENROUTER_API_KEY=sk-or-v1-xxx

# LLM 备用链路（ModelScope）
LLM_BACKUP_PROVIDER=openrouter
LLM_BACKUP_MODEL=MiniMax/MiniMax-M2.7
LLM_BACKUP_API_KEY=ms-b2fe34b0-d76f-456e-9abf-4985e827bb60
LLM_BACKUP_BASE_URL=https://api-inference.modelscope.cn/v1

# OCR
OCR_API_KEY=sk-or-v1-xxx
OCR_MODEL=baidu/qianfan-ocr-fast:free

# Embedding
EMBEDDING_API_KEY=sk-or-v1-xxx
EMBEDDING_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free

# 向量数据库
CHROMA_PERSISTENT_PATH=./data/chroma
CHROMA_COLLECTION=omniops_knowledge

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# 应用
OMNIOPS_API_HOST=0.0.0.0
OMNIOPS_API_PORT=8000
OMNIOPS_API_DEBUG=true
OMNIOPS_UPLOAD_DIR=./uploads
OMNIOPS_MAX_UPLOAD_SIZE=10485760
LOG_LEVEL=INFO

# HITL
HITL_TIMEOUT_SECONDS=600
HITL_ESCALATION_WEBHOOK_URL=
```

---

## 11. 项目目录结构

```
opticrc-agent/
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
├── .env
├── .env.example
├── .gitignore
├── README.md
├── demo.py
├── nginx/
│   └── default.conf
├── frontend/
│   ├── Dockerfile
│   └── package.json
├── src/optirc/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Pydantic Settings，全部字段从 .env 读取
│   │   ├── state.py               # OverallState + 所有 InternalState
│   │   ├── encoding.py            # CSV 编码检测
│   │   ├── topology_manager.py    # 拓扑查询封装
│   │   └── llm_client.py          # 统一 OpenAI SDK 客户端（主备双后端）
│   ├── graphs/
│   │   ├── __init__.py
│   │   ├── parent.py              # OptiGraph 父图编排器
│   │   └── subgraphs/
│   │       ├── __init__.py
│   │       ├── perception.py
│   │       ├── diagnosis.py
│   │       ├── diagnosis_validation.py
│   │       ├── planning.py
│   │       ├── solution_validation.py
│   │       ├── human_review.py
│   │       └── closure.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI + lifespan + WebSocket
│   │   └── routes.py              # REST 路由
│   ├── ingestion/
│   │   ├── __init__.py
│   │   └── csv_parser.py          # CSV 解析与标准化
│   ├── rag/
│   │   ├── __init__.py
│   │   └── vector_store.py        # ChromaDB 向量存储封装
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── neo4j_client.py        # Neo4j 异步客户端
│   │   ├── graph_builder.py       # 图谱构建器
│   │   ├── entity_parser.py       # 实体关系抽取
│   │   └── kg_query.py            # 图谱查询服务
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── redis_store.py         # Redis 异步缓存
│   │   └── db_store.py            # PostgreSQL 持久化
│   ├── models/
│   │   ├── __init__.py
│   │   ├── session.py             # Session 状态机枚举
│   │   └── knowledge.py           # 知识模型
│   └── tools/
│       ├── __init__.py
│       └── registry.py            # 工具注册表
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_perception.py
    │   ├── test_diagnosis.py
    │   ├── test_diagnosis_validation.py
    │   ├── test_solution_validation.py
    │   └── test_parent_graph.py
    └── integration/
        └── test_api.py
```

---

## 12. 关键实现约束

1. **Python 3.8 兼容**：所有类型注解使用 `List[X]` / `Optional[X]` / `Dict[K, V]`，严禁使用 `list[X]` / `X | None` / `dict[K, V]`
2. **状态隔离**：子图 `InternalState` 字段名必须与父图 `OverallState` 不同，防止 LangGraph reducer 意外 merge 污染
3. **LLM 零硬编码**：代码中禁止出现任何模型名称字符串，全部从 `settings.llm_model` / `settings.llm_backup_model` 等读取
4. **OpenAI SDK 统一**：所有 LLM/OCR/Embedding 调用必须通过 `openai.AsyncOpenAI`，禁止直接裸调 httpx 请求 OpenRouter/ModelScope
5. **错误降级**：RAG/KG/LLM 任一环节失败不得阻断主链路，返回空结果或降级默认值，由校验子图捕获并决策重试
6. **幂等设计**：`DBSessionStore.create_session()` 必须实现 `INSERT ... ON CONFLICT DO UPDATE`
7. **HITL 检测**：API 层恢复中断前，必须通过 `state.tasks` 和 `task.interrupts` 确认存在活跃 interrupt，否则返回 400
8. **Checkpointer 降级**：`AsyncPostgresSaver` 初始化失败时自动降级到 `MemorySaver`，不得抛异常导致服务启动失败
9. **uv 包管理**：所有依赖通过 `pyproject.toml` 声明，开发命令统一用 `uv run` 前缀
10. **配置集中管理**：新增任何环境依赖（如第三方 API URL）必须先加入 `.env.example` 和 `core/config.py`，禁止代码中出现裸字符串 URL

---

## 13. 测试策略

| 测试类型 | 覆盖点 |
|----------|--------|
| 单元测试 | 各子图独立 `ainvoke`，验证输入输出字段完整性 |
| 单元测试 | 诊断校验子图分支逻辑（proceed/retry/needs_human） |
| 单元测试 | 方案校验子图分支逻辑（valid/needs_replan） |
| 单元测试 | 父图条件边路由逻辑（所有分支路径） |
| 单元测试 | LLM 客户端主备自动降级逻辑 |
| 集成测试 | API 上传→查询→HITL resume 完整链路 |
| 集成测试 | Postgres Checkpointer 断点续跑验证 |

---

## 14. 交付 checklist

- [ ] `pyproject.toml` 完整，支持 `uv sync` 一键安装
- [ ] `docker compose up --build -d` 可启动全栈（API + Postgres + Redis + Neo4j + nginx）
- [ ] `demo.py` 无需外部服务可本地运行（MemorySaver 降级 + 模拟 LLM 返回）
- [ ] 所有子图编译通过，父图 `build_optigraph()` 无异常
- [ ] API `/v1/health` 返回正常，包含 checkpointer 类型信息
- [ ] HITL 中断后，`/v1/sessions/{id}/human-decision` 使用 `Command(resume=...)` 可恢复流水线
- [ ] 诊断子图中间状态（`retrieved_docs`, `reasoning_chain`）不出现在父图 `OverallState` 中
- [ ] LLM 客户端主链路故障时，自动降级到备用 ModelScope 链路
- [ ] 所有模型名称、API Key、Base URL 均从 `.env` 读取，代码中零硬编码模型名