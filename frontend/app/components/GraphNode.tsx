"use client";
import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { clsx } from "clsx";
import { ChevronDown } from "lucide-react";
import type { NodeStatus } from "../lib/types";

interface OptiNodeData {
  label: string;
  labelEn: string;
  status: NodeStatus;
  duration?: string;
  detail?: Record<string, unknown>;
  onExpand?: (nodeId: string) => void;
  onSelect?: (nodeId: string) => void;
  subgraph?: string;
}

const statusStyles: Record<NodeStatus, { border: string; bg: string; ring: string; anim: string }> = {
  pending: {
    border: "border-gray-300",
    bg: "bg-white",
    ring: "",
    anim: "",
  },
  running: {
    border: "border-blue-500",
    bg: "bg-blue-50",
    ring: "ring-2 ring-blue-400",
    anim: "animate-pulse-ring",
  },
  completed: {
    border: "border-green-500",
    bg: "bg-green-50",
    ring: "",
    anim: "",
  },
  error: {
    border: "border-red-500",
    bg: "bg-red-50",
    ring: "",
    anim: "animate-shake",
  },
  interrupted: {
    border: "border-orange-400",
    bg: "bg-orange-50",
    ring: "",
    anim: "animate-slow-blink",
  },
};

function OptiNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as OptiNodeData;
  const s = statusStyles[nodeData.status];
  const isExpandable = !!nodeData.subgraph;

  return (
    <div
      className={clsx(
        "min-w-[160px] rounded-xl border-2 px-4 py-3 shadow-sm transition-all cursor-pointer",
        s.border,
        s.bg,
        s.ring,
        s.anim,
        selected && "ring-2 ring-primary",
      )}
      onClick={() => nodeData.onSelect?.(nodeData.labelEn)}
    >
      {/* Label */}
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-semibold text-foreground">{nodeData.label}</span>
        <span className="text-xs text-muted-foreground">{nodeData.labelEn}</span>
      </div>

      {/* Status indicator */}
      <div className="flex items-center gap-2 mb-1">
        <span
          className={clsx("h-2 w-2 rounded-full", {
            "bg-gray-400": nodeData.status === "pending",
            "bg-blue-500": nodeData.status === "running",
            "bg-green-500": nodeData.status === "completed",
            "bg-red-500": nodeData.status === "error",
            "bg-orange-400": nodeData.status === "interrupted",
          })}
        />
        <span className="text-xs text-muted-foreground capitalize">{nodeData.status}</span>
        {nodeData.duration && (
          <span className="text-xs text-muted-foreground ml-auto">{nodeData.duration}</span>
        )}
      </div>

      {/* Expand button */}
      {isExpandable && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            nodeData.onExpand?.(nodeData.labelEn);
          }}
          className="mt-2 flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
        >
          <ChevronDown className="w-3 h-3" />
          展开子图
        </button>
      )}

      {/* Handles */}
      <Handle type="target" position={Position.Top} className="!bg-gray-400 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400 !w-2 !h-2" />
    </div>
  );
}

export const OptiNode = memo(OptiNodeComponent);
