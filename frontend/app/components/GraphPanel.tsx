"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  MarkerType,
  ReactFlowProvider,
} from "@xyflow/react";
import dagre from "dagre";
import {
  ArrowDown,
  GripVertical,
  RotateCcw,
  Save,
  Sparkles,
} from "lucide-react";
import "@xyflow/react/dist/style.css";

import { OptiNode } from "./GraphNode";
import { OptiEdge } from "./GraphEdge";
import { SubgraphBreadcrumbs } from "./SubgraphViewer";
import { NodeDetailDrawer } from "./NodeDetailDrawer";
import { useSessionStore } from "../store/session";
import type { NodeStatus } from "../lib/types";

// ── Static graph definitions ─────────────────────────────────────────────────

const PARENT_NODES = [
  { id: "perception", label: "感知", labelEn: "perception", subgraph: "perception" },
  { id: "diagnosis", label: "诊断", labelEn: "diagnosis", subgraph: "diagnosis" },
  { id: "diagnosis_validation", label: "诊断校验", labelEn: "diagnosis_validation", subgraph: null },
  { id: "planning", label: "方案", labelEn: "planning", subgraph: "planning" },
  { id: "solution_validation", label: "方案校验", labelEn: "solution_validation", subgraph: null },
  { id: "human_review", label: "人工审核", labelEn: "human_review", subgraph: null },
  { id: "closure", label: "回收", labelEn: "closure", subgraph: "closure" },
];

const PARENT_EDGES = [
  { id: "e-perc-dx", source: "perception", target: "diagnosis" },
  { id: "e-dx-dxv", source: "diagnosis", target: "diagnosis_validation" },
  {
    id: "e-dxv-plan",
    source: "diagnosis_validation",
    target: "planning",
    label: "proceed",
    isConditional: true,
  },
  {
    id: "e-dxv-dx",
    source: "diagnosis_validation",
    target: "diagnosis",
    label: "retry",
    isConditional: true,
    isDashed: true,
  },
  {
    id: "e-dxv-hr",
    source: "diagnosis_validation",
    target: "human_review",
    label: "needs_human",
    isConditional: true,
  },
  { id: "e-plan-sv", source: "planning", target: "solution_validation" },
  {
    id: "e-sv-plan",
    source: "solution_validation",
    target: "planning",
    label: "replan",
    isConditional: true,
    isDashed: true,
  },
  {
    id: "e-sv-hr",
    source: "solution_validation",
    target: "human_review",
    isConditional: true,
  },
  { id: "e-hr-closure", source: "human_review", target: "closure" },
  {
    id: "e-hr-plan",
    source: "human_review",
    target: "planning",
    label: "rejected",
    isConditional: true,
    isDashed: true,
  },
];

const SUBGRAPH_DEFS: Record<
  string,
  { nodes: { id: string; label: string; labelEn: string }[]; edges: { id: string; source: string; target: string }[] }
> = {
  perception: {
    nodes: [
      { id: "detect_input_type", label: "输入类型检测", labelEn: "detect_input_type" },
      { id: "detect_encoding", label: "编码检测", labelEn: "detect_encoding" },
      { id: "parse_csv", label: "CSV解析", labelEn: "parse_csv" },
      { id: "extract_ocr", label: "OCR提取", labelEn: "extract_ocr" },
      { id: "summarize", label: "感知汇总", labelEn: "summarize" },
    ],
    edges: [
      { id: "s-perc-1", source: "detect_input_type", target: "detect_encoding" },
      { id: "s-perc-2", source: "detect_encoding", target: "parse_csv" },
      { id: "s-perc-3", source: "detect_input_type", target: "extract_ocr" },
      { id: "s-perc-4", source: "parse_csv", target: "summarize" },
      { id: "s-perc-5", source: "extract_ocr", target: "summarize" },
    ],
  },
  diagnosis: {
    nodes: [
      { id: "build_query", label: "构建查询", labelEn: "build_query" },
      { id: "retrieve_rag", label: "RAG检索", labelEn: "retrieve_rag" },
      { id: "retrieve_kg", label: "图谱查询", labelEn: "retrieve_kg" },
      { id: "analyze", label: "LLM分析", labelEn: "analyze" },
      { id: "finalize", label: "提炼结果", labelEn: "finalize" },
    ],
    edges: [
      { id: "s-dx-1", source: "build_query", target: "retrieve_rag" },
      { id: "s-dx-2", source: "build_query", target: "retrieve_kg" },
      { id: "s-dx-3", source: "retrieve_rag", target: "analyze" },
      { id: "s-dx-4", source: "retrieve_kg", target: "analyze" },
      { id: "s-dx-5", source: "analyze", target: "finalize" },
    ],
  },
  planning: {
    nodes: [
      { id: "retrieve_sops", label: "SOP检索", labelEn: "retrieve_sops" },
      { id: "generate_candidates", label: "生成候选方案", labelEn: "generate_candidates" },
      { id: "finalize_plan", label: "确定方案", labelEn: "finalize_plan" },
    ],
    edges: [
      { id: "s-pl-1", source: "retrieve_sops", target: "generate_candidates" },
      { id: "s-pl-2", source: "generate_candidates", target: "finalize_plan" },
    ],
  },
  closure: {
    nodes: [
      { id: "extract_knowledge", label: "抽取知识", labelEn: "extract_knowledge" },
      { id: "store_vector", label: "存入向量库", labelEn: "store_vector" },
      { id: "store_graph", label: "存入图谱", labelEn: "store_graph" },
      { id: "summarize", label: "生成闭环摘要", labelEn: "summarize" },
    ],
    edges: [
      { id: "s-cl-1", source: "extract_knowledge", target: "store_vector" },
      { id: "s-cl-2", source: "extract_knowledge", target: "store_graph" },
      { id: "s-cl-3", source: "store_vector", target: "summarize" },
      { id: "s-cl-4", source: "store_graph", target: "summarize" },
    ],
  },
};

// ── Layout helper ─────────────────────────────────────────────────────────────

// Sizing for the auto-layout pass. The user can later drag nodes to any
// position they like; their custom positions override this baseline.
const NODE_W = 220;
const NODE_H = 88;
const RANK_SEP = 110; // vertical gap between ranks
const NODE_SEP = 36;  // horizontal gap between sibling nodes

function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  rankdir: "TB" | "LR" = "TB",
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir,
    ranker: "tight-tree",
    ranksep: RANK_SEP,
    nodesep: NODE_SEP,
    marginx: 40,
    marginy: 40,
  });

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  const layouted = nodes.map((n) => {
    const { x, y } = g.node(n.id);
    return { ...n, position: { x: x - NODE_W / 2, y: y - NODE_H / 2 } };
  });

  return { nodes: layouted, edges };
}

// ── Status mapping ────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, string> = {
  init: "perception",
  perceived: "diagnosis",
  diagnosed: "diagnosis_validation",
  diagnosis_validated: "planning",
  planned: "solution_validation",
  solution_validated: "human_review",
  human_reviewed: "closure",
  closed: "closure",
};

function deriveNodeStatus(
  nodeId: string,
  activeNode: string | null,
  completedNodes: string[],
  hitlRequired: boolean,
  status: string,
): NodeStatus {
  if (status === "closed") return "completed";
  if (status === "error") return "error";
  if (activeNode === nodeId) return "running";
  if (nodeId === "human_review" && hitlRequired) return "interrupted";
  if (completedNodes.includes(nodeId)) return "completed";
  return "pending";
}

// ── Local-storage helpers for persisted user layouts ──────────────────────────

const LAYOUT_KEY = (view: string) => `optirc:layout:${view}`;

type PositionMap = Record<string, { x: number; y: number }>;

function loadSavedPositions(view: string): PositionMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(LAYOUT_KEY(view));
    return raw ? (JSON.parse(raw) as PositionMap) : {};
  } catch {
    return {};
  }
}

function saveSavedPositions(view: string, positions: PositionMap) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LAYOUT_KEY(view), JSON.stringify(positions));
  } catch {
    // ignore quota errors — non-critical
  }
}

function clearSavedPositions(view: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(LAYOUT_KEY(view));
  } catch {
    /* noop */
  }
}

// ── GraphPanel ───────────────────────────────────────────────────────────────

const nodeTypes = { opti: OptiNode };
const edgeTypes = { opti: OptiEdge };

export function GraphPanel() {
  return (
    <ReactFlowProvider>
      <GraphPanelInner />
    </ReactFlowProvider>
  );
}

function GraphPanelInner() {
  const { status, activeNode, completedNodes, hitlRequired, sessionState, setActiveNode } =
    useSessionStore();

  const [currentSubgraph, setCurrentSubgraph] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const viewKey = currentSubgraph ?? "parent";

  // Pulled-back state from the underlying React Flow instance so the user can
  // re-run "auto layout" or "reset" without losing their custom arrangement.
  const [userPositions, setUserPositions] = useState<PositionMap>({});
  const [hasUserLayout, setHasUserLayout] = useState(false);
  const [, forceTick] = useState(0);
  const rerender = useCallback(() => forceTick((n) => n + 1), []);

  // Load saved positions whenever the view changes
  useEffect(() => {
    const saved = loadSavedPositions(viewKey);
    setUserPositions(saved);
    setHasUserLayout(Object.keys(saved).length > 0);
  }, [viewKey]);

  const activeParentId = STATUS_MAP[status] || null;
  const subgraphDef = currentSubgraph ? SUBGRAPH_DEFS[currentSubgraph] : null;

  // Compute the auto-laid-out baseline once per view
  const baseLayout = useMemo(() => {
    if (subgraphDef) {
      const layouted = getLayoutedElements(
        subgraphDef.nodes.map((n) => ({
          id: n.id,
          type: "opti",
          data: {
            ...n,
            status: "pending" as NodeStatus,
            onExpand: undefined,
            onSelect: (id: string) => setSelectedNode(id),
          },
          position: { x: 0, y: 0 },
        })),
        subgraphDef.edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          type: "opti",
          data: {},
        })),
        "TB",
      );
      return { nodes: layouted.nodes, edges: layouted.edges };
    }

    const { nodes: n } = getLayoutedElements(
      PARENT_NODES.map((n) => ({
        id: n.id,
        type: "opti",
        data: {
          ...n,
          status: deriveNodeStatus(n.id, activeParentId, completedNodes, hitlRequired, status),
          onExpand: n.subgraph ? (id: string) => setCurrentSubgraph(id) : undefined,
          onSelect: (id: string) => setSelectedNode(id),
        },
        position: { x: 0, y: 0 },
      })),
      [],
      "TB",
    );
    return { nodes: n, edges: [] as Edge[] };
  }, [currentSubgraph, subgraphDef, activeParentId, completedNodes, hitlRequired, status]);

  // Overlay the user's saved/dragged positions on top of the baseline
  const nodes = useMemo<Node[]>(() => {
    if (!hasUserLayout) return baseLayout.nodes;
    return baseLayout.nodes.map((n) => {
      const override = userPositions[n.id];
      return override ? { ...n, position: override } : n;
    });
  }, [baseLayout, userPositions, hasUserLayout]);

  const edges = useMemo<Edge[]>(() => {
    if (subgraphDef) {
      return subgraphDef.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "opti",
        data: { isActive: false },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#94a3b8" },
      }));
    }

    return PARENT_EDGES.map((e) => {
      const isActive =
        activeParentId !== null &&
        (e.source === activeParentId || e.target === activeParentId);

      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: "opti",
        data: {
          label: e.label,
          isActive,
          isConditional: e.isConditional,
        },
        style: e.isDashed ? { strokeDasharray: "5,5" } : undefined,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isActive ? "#3b82f6" : "#94a3b8",
        },
      };
    });
  }, [subgraphDef, activeParentId]);

  // Capture the final resting position of every drag
  const onNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setUserPositions((prev) => {
        const next = { ...prev, [node.id]: { x: node.position.x, y: node.position.y } };
        saveSavedPositions(viewKey, next);
        return next;
      });
      setHasUserLayout(true);
    },
    [viewKey],
  );

  // Continuous tracking of position while dragging (also persists partial
  // movement so the user sees their own updates reflected immediately)
  const onNodeDrag = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setUserPositions((prev) => ({ ...prev, [node.id]: { x: node.position.x, y: node.position.y } }));
    },
    [],
  );

  const handleAutoLayout = useCallback(() => {
    setUserPositions({});
    setHasUserLayout(false);
    clearSavedPositions(viewKey);
    // Re-fit the view a tick later so ReactFlow has fresh positions
    requestAnimationFrame(() => rerender());
  }, [viewKey, rerender]);

  const handleResetAll = useCallback(() => {
    setUserPositions({});
    setHasUserLayout(false);
    clearSavedPositions(viewKey);
    rerender();
  }, [viewKey, rerender]);

  const handleSaveLayout = useCallback(() => {
    saveSavedPositions(viewKey, userPositions);
  }, [viewKey, userPositions]);

  const handleExpand = useCallback((nodeId: string) => {
    setCurrentSubgraph(nodeId);
  }, []);

  const selectedNodeData = selectedNode
    ? (currentSubgraph
      ? subgraphDef?.nodes.find((n) => n.id === selectedNode)
      : PARENT_NODES.find((n) => n.id === selectedNode))
    : null;

  const selectedDetail = selectedNode && sessionState
    ? deriveDetail(selectedNode, sessionState)
    : null;

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-gradient-to-b from-background to-muted/30">
        <SubgraphBreadcrumbs
          currentSubgraph={currentSubgraph}
          onNavigate={setCurrentSubgraph}
        />

        <div className="ml-auto flex items-center gap-2">
          {/* Status pill */}
          <div className="hidden md:flex items-center gap-1.5 text-xs text-muted-foreground mr-2">
            <ArrowDown className="w-3.5 h-3.5" />
            <span>纵向链路 · 可拖拽</span>
            {hasUserLayout && (
              <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5 text-[10px] font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                已自定义布局
              </span>
            )}
          </div>

          <button
            onClick={handleAutoLayout}
            className="inline-flex items-center gap-1 text-xs border border-border rounded-lg px-2.5 py-1 bg-background hover:bg-muted transition-colors"
            title="重新整理为默认纵向布局"
          >
            <Sparkles className="w-3.5 h-3.5" />
            自动布局
          </button>

          <button
            onClick={handleSaveLayout}
            className="inline-flex items-center gap-1 text-xs border border-border rounded-lg px-2.5 py-1 bg-background hover:bg-muted transition-colors"
            title="保存当前节点位置"
          >
            <Save className="w-3.5 h-3.5" />
            保存
          </button>

          <button
            onClick={handleResetAll}
            className="inline-flex items-center gap-1 text-xs border border-border rounded-lg px-2.5 py-1 bg-background hover:bg-muted transition-colors"
            title="清除自定义位置"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            重置
          </button>

          <div className="w-px h-5 bg-border mx-1" />

          <select
            value={currentSubgraph ?? "parent"}
            onChange={(e) => setCurrentSubgraph(e.target.value === "parent" ? null : e.target.value)}
            className="text-xs border border-border rounded-lg px-2 py-1 bg-background"
          >
            <option value="parent">OptiGraph (父图)</option>
            <option value="perception">感知子图</option>
            <option value="diagnosis">诊断子图</option>
            <option value="planning">方案子图</option>
            <option value="closure">回收子图</option>
          </select>
        </div>
      </div>

      {/* ReactFlow Canvas */}
      <div className="flex-1 relative">
        <DragHint />

        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          // Vertical flow, top → bottom
          defaultEdgeOptions={{ type: "smoothstep" }}
          fitView
          fitViewOptions={{ padding: 0.25, includeHiddenNodes: false }}
          minZoom={0.25}
          maxZoom={2}
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          panOnDrag
          zoomOnScroll
          onNodeClick={(_, node) => {
            setSelectedNode(node.id);
            setActiveNode(node.id);
          }}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1.4} color="#e2e8f0" />
          <Controls
            className="!bottom-4 !left-4"
            showInteractive={false}
          />
          <MiniMap
            className="!bottom-4 !right-4"
            pannable
            zoomable
            nodeColor={(n) => {
              const s = n.data?.status as NodeStatus;
              if (s === "completed") return "#10b981";
              if (s === "running") return "#3b82f6";
              if (s === "error") return "#ef4444";
              if (s === "interrupted") return "#f59e0b";
              return "#cbd5e1";
            }}
            maskColor="rgba(148, 163, 184, 0.12)"
          />
        </ReactFlow>
      </div>

      {/* Node Detail Drawer */}
      {selectedNode && selectedNodeData && (
        <NodeDetailDrawer
          nodeId={selectedNode}
          label={selectedNodeData.label}
          detail={selectedDetail}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  );
}

// ── Floating hint that explains the new interaction model ────────────────────

function DragHint() {
  return (
    <div className="pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 z-10">
      <div className="flex items-center gap-1.5 rounded-full border border-border bg-background/80 backdrop-blur px-3 py-1 text-[11px] text-muted-foreground shadow-sm">
        <GripVertical className="w-3 h-3" />
        拖动顶部手柄可自由摆放节点
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function deriveDetail(
  nodeId: string,
  state: Record<string, unknown>,
): Record<string, unknown> | null {
  switch (nodeId) {
    case "perception":
      return (state.perception ?? state.perception_result) as Record<string, unknown> | null;
    case "diagnosis":
      return (state.diagnosis ?? state.diagnosis_result) as Record<string, unknown> | null;
    case "diagnosis_validation":
      return (state.diagnosis_validation ?? state.diagnosis_validation_result) as Record<string, unknown> | null;
    case "planning":
      return (state.planning ?? state.planning_result) as Record<string, unknown> | null;
    case "solution_validation":
      return (state.solution_validation ?? state.solution_validation_result) as Record<string, unknown> | null;
    case "human_review":
      return (state.human_review ?? state.human_review_result) as Record<string, unknown> | null;
    case "closure":
      return (state.closure ?? state.closure_result) as Record<string, unknown> | null;
    default:
      return null;
  }
}
