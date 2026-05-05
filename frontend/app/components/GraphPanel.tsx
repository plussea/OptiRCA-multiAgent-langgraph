"use client";
import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  MarkerType,
} from "@xyflow/react";
import dagre from "dagre";
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

function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  rankdir: "TB" | "LR" = "TB",
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir, ranker: "tight-tree" });

  nodes.forEach((n) => g.setNode(n.id, { width: 180, height: 70 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  const layouted = nodes.map((n) => {
    const { x, y } = g.node(n.id);
    return { ...n, position: { x, y } };
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

// ── GraphPanel ───────────────────────────────────────────────────────────────

const nodeTypes = { opti: OptiNode };
const edgeTypes = { opti: OptiEdge };

export function GraphPanel() {
  const { status, activeNode, completedNodes, hitlRequired, sessionState, setActiveNode } =
    useSessionStore();

  const [currentSubgraph, setCurrentSubgraph] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const activeParentId = STATUS_MAP[status] || null;

  const subgraphDef = currentSubgraph ? SUBGRAPH_DEFS[currentSubgraph] : null;

  // Build nodes for current view
  const nodes = useMemo((): Node[] => {
    if (subgraphDef) {
      const { nodes: n, edges: e } = getLayoutedElements(
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
      return n;
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
    return n;
  }, [currentSubgraph, subgraphDef, activeParentId, completedNodes, hitlRequired, status]);

  // Build edges for parent view
  const edges = useMemo((): Edge[] => {
    if (subgraphDef) {
      return subgraphDef.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: "opti",
        data: { isActive: false },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#d1d5db" },
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
          color: isActive ? "#3b82f6" : "#d1d5db",
        },
      };
    });
  }, [currentSubgraph, subgraphDef, activeParentId]);

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
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border">
        <SubgraphBreadcrumbs
          currentSubgraph={currentSubgraph}
          onNavigate={setCurrentSubgraph}
        />

        <div className="ml-auto flex items-center gap-2">
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
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.3}
          maxZoom={2}
          onNodeClick={(_, node) => {
            setSelectedNode(node.id);
            setActiveNode(node.id);
          }}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls className="!bottom-4 !left-4" />
          <MiniMap
            className="!bottom-4 !right-4"
            nodeColor={(n) => {
              const s = n.data?.status as NodeStatus;
              if (s === "completed") return "#10b981";
              if (s === "running") return "#3b82f6";
              if (s === "error") return "#ef4444";
              if (s === "interrupted") return "#f59e0b";
              return "#d1d5db";
            }}
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
