"use client";
import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
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
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        className={clsx(
          edgeData?.isActive ? "stroke-blue-500 stroke-[2px]" : "stroke-gray-300 stroke-[1px]",
          edgeData?.isConditional && "stroke-dasharray-4",
        )}
        style={
          edgeData?.isActive
            ? { strokeDasharray: "5,5", animation: "dash-flow 0.5s linear infinite" }
            : undefined
        }
      />
      {edgeData?.label && (
        <EdgeLabelRenderer>
          <div
            className={clsx(
              "absolute px-2 py-0.5 rounded text-xs font-medium nodrag nopan pointer-events-auto",
              edgeData.isConditional
                ? "bg-gray-100 text-gray-600 border border-gray-300"
                : "bg-transparent text-gray-400",
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
