"use client";
import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";
import { clsx } from "clsx";

interface OptiEdgeData {
  label?: string;
  isActive?: boolean;
  isConditional?: boolean;
}

function OptiEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  markerEnd,
}: EdgeProps) {
  const edgeData = data as unknown as OptiEdgeData | undefined;

  // Smoothstep path looks like a printed-circuit trace — a much better
  // match for a vertical top-to-bottom flow than the default bezier.
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 14,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        className={clsx(
          edgeData?.isActive ? "stroke-blue-500" : "stroke-slate-300",
          edgeData?.isActive ? "stroke-[2px]" : "stroke-[1.5px]",
        )}
        style={
          edgeData?.isActive
            ? { strokeDasharray: "6,4", animation: "dash-flow 0.6s linear infinite" }
            : undefined
        }
      />

      {/* Junction dot where the edge meets the source — a small visual
          indicator that makes the connection point readable. */}
      {edgeData?.isActive && (
        <circle
          cx={sourceX}
          cy={sourceY}
          r={4}
          fill="#3b82f6"
          className="animate-pulse"
        />
      )}

      {edgeData?.label && (
        <EdgeLabelRenderer>
          <div
            className={clsx(
              "absolute px-2 py-0.5 rounded-md text-[10px] font-semibold tracking-wide uppercase nodrag nopan pointer-events-auto",
              edgeData.isActive
                ? "bg-blue-500 text-white shadow-sm"
                : "bg-white text-slate-500 border border-slate-200",
              edgeData.isConditional && !edgeData.isActive && "border-dashed",
              selected && "ring-2 ring-primary",
            )}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}
          >
            {edgeData.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const OptiEdge = memo(OptiEdgeComponent);
