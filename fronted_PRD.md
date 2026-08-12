# OptiRCAgent 前端设计 PRD

## 1. 项目概述

**产品名称**：OptiRCAgent Console  
**定位**：光网络智能诊断系统的运维操作台  
**核心功能**：
- **对话式交互**：支持文本 Prompt 输入 + CSV/图片告警文件上传
- **LangGraph 实时可视化**：类似 LangSmith 的图结构展示，父图与子图层级嵌套，节点状态实时流转
- **HITL 人工审核面板**：流水线中断时弹出审核材料，支持一键决策

---

## 2. 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| 框架 | Next.js 14 (App Router) | SSR + API Route 代理 |
| 语言 | TypeScript | 严格模式 |
| 样式 | Tailwind CSS + shadcn/ui | 组件库基础 |
| 状态管理 | Zustand | 全局会话状态 |
| 图可视化 | ReactFlow + dagre | 节点布局自动计算 |
| 实时通信 | Socket.io-client | WebSocket 封装（兼容多实例） |
| HTTP 客户端 | axios | REST API 调用 |
| 动画 | Framer Motion | 节点状态过渡动画 |

---

## 3. 整体布局

```
┌─────────────────────────────────────────────────────────────────────┐
│  Header: OptiRCAgent Logo | 当前会话: session-xxx | 用户头像          │
├──────────────────────────┬──────────────────────────────────────────┤
│                          │                                          │
│   Chat Panel (35%)       │   Graph Visualization Panel (65%)      │
│   ┌──────────────────┐   │   ┌──────────────────────────────────┐   │
│   │  消息历史区      │   │   │  图控制栏: [父图▼] [重置视图] [实时] │   │
│   │  ─────────────  │   │   ├──────────────────────────────────┤   │
│   │  System: 诊断完成 │   │   │                                  │   │
│   │  User: 上传csv   │   │   │    ┌─────┐    ┌─────┐            │   │
│   │  ─────────────  │   │   │    │感知 ◉│───▶│诊断 ◉│            │   │
│   │  [输入框+上传]   │   │   │    └──┬──┘    └──┬──┘            │   │
│   │  [发送] [📎]     │   │   │       │          │               │   │
│   └──────────────────┘   │   │    ┌──┴──┐    ┌──┴──┐            │   │
│                          │   │    │CSV ○│    │RAG ○│            │   │
│   HITL Panel (浮动)      │   │    └─────┘    └─────┘            │   │
│   ┌──────────────────┐   │   │       ▲ 子图展开                  │   │
│   │ 待审核方案        │   │   │                                  │   │
│   │ [✓通过] [✗驳回]  │   │   │    ┌─────────┐                   │   │
│   │ [⚠升级]          │   │   │    │诊断校验 ◉│                   │   │
│   └──────────────────┘   │   │    └────┬────┘                   │   │
│                          │   │         │                          │   │
│                          │   │    ┌────┴────┐                     │   │
│                          │   │    │方案 ◉   │                     │   │
│                          │   │    └────┬────┘                     │   │
│                          │   │         │                          │   │
│                          │   │    ┌────┴────┐                     │   │
│                          │   │    │方案校验 ◉│                     │   │
│                          │   │    └────┬────┘                     │   │
│                          │   │         │                          │   │
│                          │   │    ┌────┴────┐                     │   │
│                          │   │    │人工审核 ◉│◀── 当前激活(脉冲)   │   │
│                          │   │    └─────────┘                     │   │
│                          │   │                                  │   │
│                          │   │  底部: 状态日志流                  │   │
│                          │   │  [10:00:01] 感知完成 | [10:00:03]  │   │
│                          │   │  诊断中...                         │   │
│                          │   └──────────────────────────────────┘   │
│                          │                                          │
└──────────────────────────┴──────────────────────────────────────────┘
```

---

## 4. 页面模块详细设计

### 4.1 Chat Panel（左侧 35%）

**功能**：用户输入与系统反馈的会话区。

#### 4.1.1 消息历史区
- **System 消息**：以灰色气泡展示，显示 Agent 阶段性结论（如"诊断完成：根因为 LOS，置信度 0.92"）
- **User 消息**：蓝色气泡，文本或文件上传确认
- **HITL 消息**：橙色边框气泡，提示"等待人工审核，请点击右侧面板决策"
- **Error 消息**：红色气泡，显示降级或异常信息

#### 4.1.2 输入区
```
┌────────────────────────────────────┐
│ [📎 上传]  输入 Prompt 或上传告警文件 │
│                                    │
│ ┌──────────────────────────────┐   │
│ │                              │   │
│ │                              │   │
│ └──────────────────────────────┘   │
│          [发送 ▶]                 │
└────────────────────────────────────┘
```

- **📎 上传按钮**：支持拖拽，文件类型过滤 `.csv`, `.xlsx`, `.png`, `.jpg`
- **输入框**：多行文本，Enter 发送，Shift+Enter 换行
- **发送按钮**：禁用态（无内容时灰色），加载态（发送中显示 spinner）

#### 4.1.3 文件上传流程
1. 用户拖拽/点击上传 CSV
2. 前端显示文件卡片（文件名 + 大小 + ✅已上传）
3. 调用 `POST /v1/sessions` 创建会话，获取 `session_id`
4. 自动开始轮询状态（每 2s `GET /v1/sessions/{id}`）
5. 状态变化时，左侧追加 System 消息，右侧图节点高亮

---

### 4.2 Graph Visualization Panel（右侧 65%）

**核心**：类似 LangSmith 的 Graph + Trace 混合视图。

#### 4.2.1 图控制栏
- **父图/子图选择器**：下拉框选择当前展示的图层级
  - `OptiGraph (父图)` — 展示 7 个顶层节点
  - `Diagnosis Subgraph` — 展开诊断内部 5 个节点
  - `Planning Subgraph` — 展开方案内部 3 个节点
  - ...
- **重置视图**：居中并适应画布
- **实时/暂停**：切换自动跟随最新激活节点

#### 4.2.2 节点设计（ReactFlow Custom Node）

**父图节点样式**：
```
┌─────────────────────────┐
│  🔵 感知 (Perception)   │
│  ━━━━━━━━━━━━━━━━━━━━━  │
│  Status: completed      │
│  Duration: 1.2s         │
│  [展开子图 ▼]           │
└─────────────────────────┘
```

**子图节点样式**（展开后嵌套在父图节点内部或独立画布）：
```
┌─────────────────────────┐
│  🟡 诊断 (Diagnosis)    │
│  ━━━━━━━━━━━━━━━━━━━━━  │
│  Status: running ◉◉◉   │
│  [RAG: 5 docs] [KG: 12 nodes] │
│  [查看详情 →]            │
└─────────────────────────┘
```

**状态颜色编码**：
| 状态 | 边框 | 背景 | 动画 |
|------|------|------|------|
| pending | 灰色 `#9CA3AF` | 白 | 无 |
| running | 蓝色 `#3B82F6` | 蓝 50 | 脉冲光环（box-shadow 呼吸） |
| completed | 绿色 `#10B981` | 绿 50 | 无 |
| error | 红色 `#EF4444` | 红 50 | 抖动 |
| interrupted | 橙色 `#F59E0B` | 橙 50 | 慢闪 |

**边样式**：
- 普通边：灰色 1px
- 激活边（当前流转路径）：蓝色 2px + 流动虚线动画（stroke-dashoffset 循环）
- 条件边（分支）：带标签（"proceed" / "retry" / "needs_human"）

#### 4.2.3 子图嵌套交互

**方案 A：画布切换**（推荐，实现简单）
- 点击父图节点的 `[展开子图 ▼]`，右侧画布切换为该子图的独立布局
- 顶部面包屑：`OptiGraph > Diagnosis Subgraph > retrieve_rag`
- 点击面包屑返回上级

**方案 B：节点内嵌**（高级，可选）
- 父图节点区域放大，内部用 ReactFlow 的 `SubFlow` 渲染子图节点
- 适合展示父子关系，但布局算法复杂

**本 PRD 采用方案 A**。

#### 4.2.4 节点详情抽屉

点击任意节点，右侧滑出抽屉面板：
```
┌──────────────────────┐
│ 节点: diagnosis      │
│ ━━━━━━━━━━━━━━━━━━━  │
│ 输入:                │
│ {perception_summary}  │
│                      │
│ 输出:                │
│ {root_cause, ...}   │
│                      │
│ 私有状态 (子图内):    │
│ retrieved_docs: 5    │
│ reasoning_chain: ...│
│ [查看完整 JSON]      │
├──────────────────────┤
│ 执行时间: 3.4s       │
│ LLM 调用次数: 1      │
│ Token 消耗: 2,400    │
└──────────────────────┘
```

---

### 4.3 HITL 人工审核面板（浮动/侧边）

**触发条件**：后端返回 `pending_human: true` 或 WebSocket 推送 `type: "human_review_required"`。

**布局**：从右侧滑入的固定面板（宽度 400px），或 Chat Panel 上方浮层。

```
┌──────────────────────────┐
│  ⚠️ 人工审核待决策        │
│  Session: xxx...         │
├──────────────────────────┤
│  📋 诊断结论              │
│  根因: LOS (置信度 0.92) │
│  证据: [NE-001, NE-002]  │
├──────────────────────────┤
│  📋 修复方案              │
│  步骤1: 检查光纤连接      │
│  步骤2: 更换光模块        │
│  回滚: 恢复原模块         │
├──────────────────────────┤
│  📋 校验结果              │
│  诊断校验: ✓ 通过         │
│  方案校验: ✓ 通过 (低风险)│
├──────────────────────────┤
│  [✅ 批准执行]            │
│  [❌ 驳回重制]            │
│  [⚠️ 升级上报]           │
│  ───────────────────────  │
│  审核意见 (可选):         │
│  ┌──────────────────┐    │
│  │                  │    │
│  └──────────────────┘    │
│  剩余时间: 09:23         │
└──────────────────────────┘
```

**交互**：
- 点击批准：调用 `POST /v1/sessions/{id}/human-decision?decision=approved&notes=xxx`
- 点击驳回：流水线退回方案重制（父图路由 `planning`）
- 点击升级：流水线结束（父图路由 `END`）
- 倒计时：从 `timeout_seconds` 递减，超时自动标记 `escalated`

---

### 4.4 底部状态日志流（Log Stream）

图面板底部固定高度区域（80px），显示时间线日志：
```
[10:00:01.234] [感知] 完成 | 解析 42 行告警 | 提取 8 个拓扑ID
[10:00:03.456] [诊断] 开始 | RAG检索中...
[10:00:05.678] [诊断] 完成 | 根因: LOS | 置信度: 0.92
[10:00:06.012] [诊断校验] 完成 | 结果: proceed
...
```

- 自动滚动到底部
- 点击某行日志，右侧图对应节点高亮并居中

---

## 5. 数据流与 API 对接

### 5.1 会话创建与状态轮询

```typescript
// 1. 上传文件创建会话
const formData = new FormData();
formData.append("file", csvFile);
const { data } = await axios.post("/v1/sessions", formData);
const sessionId = data.session_id;

// 2. 轮询状态（每 2 秒）
const poll = setInterval(async () => {
  const { data: state } = await axios.get(`/v1/sessions/${sessionId}`);
  
  // 更新 Zustand store
  useSessionStore.getState().updateState(state);
  
  // 检查 HITL
  if (state.pending_human) {
    clearInterval(poll);
    useSessionStore.getState().setHitlRequired(true);
  }
  
  // 检查结束
  if (state.status === "closed" || state.status === "error") {
    clearInterval(poll);
  }
}, 2000);
```

### 5.2 WebSocket 实时推送（可选增强）

```typescript
// Socket.io 连接
const socket = io("ws://localhost/v1/ws/human-review");

socket.on("human_review_required", (payload) => {
  useSessionStore.getState().setHitlPayload(payload);
  useSessionStore.getState().setHitlRequired(true);
});
```

### 5.3 图数据结构（前端构造）

前端根据已知子图定义静态构造图数据，无需后端返回图结构：

```typescript
// graphs/optigraph.ts
export const optiGraphNodes = [
  { id: "perception", label: "感知", type: "parent", subgraph: "perception" },
  { id: "diagnosis", label: "诊断", type: "parent", subgraph: "diagnosis" },
  { id: "diagnosis_validation", label: "诊断校验", type: "parent" },
  { id: "planning", label: "方案", type: "parent", subgraph: "planning" },
  { id: "solution_validation", label: "方案校验", type: "parent" },
  { id: "human_review", label: "人工审核", type: "parent" },
  { id: "closure", label: "回收", type: "parent" },
];

export const optiGraphEdges = [
  { id: "e1", source: "perception", target: "diagnosis" },
  { id: "e2", source: "diagnosis", target: "diagnosis_validation" },
  // ... 条件边带 label
  { id: "e3-proceed", source: "diagnosis_validation", target: "planning", label: "proceed" },
  { id: "e3-retry", source: "diagnosis_validation", target: "diagnosis", label: "retry", style: "dashed" },
];

// 子图定义
export const diagnosisSubgraphNodes = [
  { id: "build_query", label: "构建查询", parent: "diagnosis" },
  { id: "retrieve_rag", label: "RAG检索", parent: "diagnosis" },
  { id: "retrieve_kg", label: "图谱查询", parent: "diagnosis" },
  { id: "analyze", label: "LLM分析", parent: "diagnosis" },
  { id: "finalize", label: "提炼结果", parent: "diagnosis" },
];
```

**动态状态绑定**：
```typescript
// 根据后端返回的 status 字段，映射节点状态
const nodeStatusMap: Record<string, string> = {
  "init": "perception",
  "perceived": "diagnosis",
  "diagnosed": "diagnosis_validation",
  "diagnosis_validated": "planning",
  "planned": "solution_validation",
  "solution_validated": "human_review",
  "human_reviewed": "closure",
  "closed": null,
};
```

---

## 6. 关键组件清单

| 组件 | 路径 | 职责 |
|------|------|------|
| `ChatPanel` | `app/components/ChatPanel.tsx` | 消息历史 + 输入框 + 文件上传 |
| `MessageBubble` | `app/components/MessageBubble.tsx` | 单条消息气泡（System/User/Error/HITL） |
| `GraphPanel` | `app/components/GraphPanel.tsx` | ReactFlow 画布容器 |
| `GraphNode` | `app/components/GraphNode.tsx` | 自定义节点（状态颜色 + 展开按钮） |
| `GraphEdge` | `app/components/GraphEdge.tsx` | 自定义边（流动动画 + 条件标签） |
| `SubgraphViewer` | `app/components/SubgraphViewer.tsx` | 子图独立画布（面包屑导航） |
| `NodeDetailDrawer` | `app/components/NodeDetailDrawer.tsx` | 节点详情滑出面板 |
| `HitlPanel` | `app/components/HitlPanel.tsx` | 人工审核决策面板 |
| `LogStream` | `app/components/LogStream.tsx` | 底部状态日志流 |
| `StatusBadge` | `app/components/StatusBadge.tsx` | 状态标签（completed/running/error） |
| `useSessionStore` | `app/store/session.ts` | Zustand 全局状态管理 |

---

## 7. 状态管理（Zustand）

```typescript
// app/store/session.ts
interface SessionState {
  sessionId: string | null;
  status: string;
  messages: Message[];
  graphState: Record<string, any>;      // 后端返回的完整状态
  activeNode: string | null;            // 当前正在执行的节点 ID
  hitlRequired: boolean;
  hitlPayload: any;
  logs: LogEntry[];
  
  // Actions
  setSessionId: (id: string) => void;
  updateState: (state: any) => void;
  setActiveNode: (nodeId: string) => void;
  setHitlRequired: (required: boolean) => void;
  addLog: (entry: LogEntry) => void;
}
```

---

## 8. 响应式设计

| 断点 | 布局 |
|------|------|
| >= 1280px | 左右分栏（Chat 35% + Graph 65%），HITL 右侧滑出 |
| 768px ~ 1279px | 上下分栏（Chat 40% + Graph 60%），HITL 底部浮层 |
| < 768px | 单栏，Chat 为主，Graph 可折叠为底部抽屉 |

---

## 9. 与后端的 API 映射

| 前端功能 | 后端 API | 说明 |
|----------|----------|------|
| 上传 CSV | `POST /v1/sessions` | multipart/form-data |
| 轮询状态 | `GET /v1/sessions/{id}` | 2s 间隔 |
| 获取审核包 | `GET /v1/sessions/{id}/review-package` | HITL 时调用 |
| 提交决策 | `POST /v1/sessions/{id}/human-decision` | form-urlencoded |
| 获取 Trace | `GET /v1/sessions/{id}/trace` | 图面板历史回放 |
| WebSocket | `WS /v1/ws/human-review` | Socket.io 协议 |
| 健康检查 | `GET /v1/health` | 启动时探测 |

---

## 10. 交付 checklist

- [ ] 左侧 Chat Panel 支持文本输入 + CSV 拖拽上传
- [ ] 右侧 Graph Panel 使用 ReactFlow 渲染父图 7 节点 + 条件边
- [ ] 点击父图节点可切换至对应子图画布（面包屑导航）
- [ ] 节点状态实时同步：running 脉冲动画、completed 绿色、error 红色、interrupted 橙色慢闪
- [ ] 激活边显示流动虚线动画
- [ ] HITL 面板在 `pending_human` 时自动滑出，展示诊断+方案+校验结果
- [ ] HITL 面板支持批准/驳回/升级 + 审核意见输入
- [ ] 底部 Log Stream 实时追加执行日志
- [ ] 节点详情抽屉展示输入/输出/私有状态/执行指标
- [ ] 响应式适配：大屏左右分栏，小屏上下分栏或单栏
- [ ] 所有 API 调用通过 Next.js API Route 代理（避免 CORS）