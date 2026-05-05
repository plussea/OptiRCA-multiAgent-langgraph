# OptiRCAgent — LangGraph Multi-Agent Optical Network Operations Assistant

基于 LangGraph 编译时图编排 + 子图记忆隔离架构的多 Agent 系统，辅助光网络运维团队完成告警根因定位与修复建议生成，支持人工审核断点与知识闭环。

## 核心特征

- **编译时图编排**：Agent 流水线在代码层面显式定义
- **子图记忆隔离**：每个 Agent 拥有私有 `InternalState`，中间记忆不跨 Agent 泄漏
- **原生 HITL**：利用 `langgraph.interrupt` 在审核节点自动暂停
- **统一 LLM 接口**：基于 OpenAI API 格式的 SDK 调用，支持 OpenRouter 与 ModelScope 双后端

## 快速启动

### 本地开发

```bash
# 安装依赖
uv sync

# 启动服务
uv run python -m optirc.api.main

# 运行测试
uv run pytest
```

### Docker 全栈

```bash
docker compose up --build -d

# 健康检查
curl http://localhost/v1/health
```

### 本地演示

```bash
uv run python demo.py
```

## 项目结构

```
src/optirc/
├── core/           # 配置、状态、LLM 客户端
├── graphs/         # 父图与子图编排
├── api/            # FastAPI REST + WebSocket
├── ingestion/      # CSV/OCR 数据摄入
├── rag/            # 向量检索
├── knowledge/      # 知识图谱
├── memory/         # Redis + PostgreSQL 持久化
├── models/         # 数据模型
└── tools/          # 工具注册表
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/sessions` | 上传文件并启动诊断 |
| GET | `/v1/sessions/{id}` | 查询会话状态 |
| GET | `/v1/sessions/{id}/review-package` | 获取审核材料包 |
| POST | `/v1/sessions/{id}/human-decision` | 提交人工决策 |
| GET | `/v1/sessions/{id}/trace` | 获取执行 Trace |
| GET | `/v1/health` | 健康检查 |
| WS | `/v1/ws/human-review` | 实时推送审核任务 |
