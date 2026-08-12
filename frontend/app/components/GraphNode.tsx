"use client";
import { memo } from "react";
import { Handle, NodeResizer, Position, type NodeProps } from "@xyflow/react";
import { clsx } from "clsx";
import { ChevronDown, GripVertical } from "lucide-react";
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

const statusStyles: Record<
  NodeStatus,
  { border: string; bg: string; ring: string; anim: string; accent: string; handle: string }
> = {
  pending: {
    border: "border-slate-300",
    bg: "bg-white",
    ring: "",
    anim: "",
    accent: "bg-slate-400",
    handle: "!bg-slate-400",
  },
  running: {
    border: "border-blue-500",
    bg: "bg-gradient-to-br from-blue-50 via-white to-blue-50",
    ring: "ring-2 ring-blue-400/60 shadow-[0_8px_24px_-8px_rgba(59,130,246,0.5)]",
    anim: "animate-pulse-ring",
    accent: "bg-blue-500",
    handle: "!bg-blue-500",
  },
  completed: {
    border: "border-emerald-500",
    bg: "bg-gradient-to-br from-emerald-50 via-white to-emerald-50",
    ring: "",
    anim: "",
    accent: "bg-emerald-500",
    handle: "!bg-emerald-500",
  },
  error: {
    border: "border-red-500",
    bg: "bg-gradient-to-br from-red-50 via-white to-red-50",
    ring: "",
    anim: "animate-shake",
    accent: "bg-red-500",
    handle: "!bg-red-500",
  },
  interrupted: {
    border: "border-amber-400",
    bg: "bg-gradient-to-br from-amber-50 via-white to-amber-50",
    ring: "",
    anim: "animate-slow-blink",
    accent: "bg-amber-400",
    handle: "!bg-amber-400",
  },
};

function OptiNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as OptiNodeData;
  const s = statusStyles[nodeData.status];
  const isExpandable = !!nodeData.subgraph;

  return (
    <div
      className={clsx(
        "group relative w-[220px] rounded-xl border-2 px-4 py-3 transition-all cursor-pointer",
        "backdrop-blur-sm",
        s.border,
        s.bg,
        s.ring,
        s.anim,
        selected && "ring-2 ring-primary",
      )}
      onClick={() => nodeData.onSelect?.(nodeData.labelEn)}
    >
      {/* Top drag handle — only this region moves the node */}
      <div
        className="drag-handle absolute inset-x-0 top-0 h-5 rounded-t-[10px] cursor-grab active:cursor-grabbing
                   bg-gradient-to-b from-black/[0.04] to-transparent
                   opacity-0 group-hover:opacity-100 transition-opacity
                   flex items-center justify-center"
      >
        <GripVertical className="w-3 h-3 text-muted-foreground/70" />
      </div>

      {/* Status accent stripe down the left */}
      <div
        className={clsx(
          "absolute left-0 top-2 bottom-2 w-[3px] rounded-full",
          s.accent,
          nodeData.status === "running" && "animate-pulse",
        )}
      />

      {/* Label */}
      <div className="flex items-center gap-2 mb-1.5 pl-1.5">
        <span className="text-sm font-semibold text-foreground">{nodeData.label}</span>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/80">
          {nodeData.labelEn}
        </span>
      </div>

      {/* Status indicator */}
      <div className="flex items-center gap-2 pl-1.5">
        <span
          className={clsx("h-2 w-2 rounded-full ring-2 ring-white shadow-sm", {
            "bg-slate-400": nodeData.status === "pending",
            "bg-blue-500": nodeData.status === "running",
            "bg-emerald-500": nodeData.status === "completed",
            "bg-red-500": nodeData.status === "error",
            "bg-amber-400": nodeData.status === "interrupted",
          })}
        />
        <span className="text-[11px] text-muted-foreground capitalize">{nodeData.status}</span>
        {nodeData.duration && (
          <span className="text-[11px] text-muted-foreground ml-auto tabular-nums">
            {nodeData.duration}
          </span>
        )}
      </div>

      {/* Expand button */}
      {isExpandable && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            nodeData.onExpand?.(nodeData.labelEn);
          }}
          className="mt-2 ml-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:text-blue-800 transition-colors"
        >
          <ChevronDown className="w-3 h-3" />
          展开子图
        </button>
      )}

      {/* Resizer so users can resize the card after dragging */}
      <NodeResizer
        minWidth={180}
        minHeight={70}
        isVisible={selected}
        lineClassName="!border-blue-400"
        handleClassName="!bg-white !border-blue-400 !w-2 !h-2"
      />

      {/* Vertical-flow handles: top = incoming, bottom = outgoing */}
      <Handle
        type="target"
        position={Position.Top}
        className={clsx("!w-2.5 !h-2.5 !border-2 !border-white", s.handle)}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className={clsx("!w-2.5 !h-2.5 !border-2 !border-white", s.handle)}
      />
    </div>
  );
}

export const OptiNode = memo(OptiNodeComponent);
