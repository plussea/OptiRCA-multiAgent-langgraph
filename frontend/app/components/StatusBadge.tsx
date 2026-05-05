"use client";
import { clsx } from "clsx";
import type { NodeStatus } from "../lib/types";

interface StatusBadgeProps {
  status: NodeStatus;
  className?: string;
}

const labels: Record<NodeStatus, string> = {
  pending: "等待中",
  running: "执行中",
  completed: "已完成",
  error: "错误",
  interrupted: "已中断",
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        {
          "bg-gray-100 text-gray-500": status === "pending",
          "bg-blue-100 text-blue-700": status === "running",
          "bg-green-100 text-green-700": status === "completed",
          "bg-red-100 text-red-700": status === "error",
          "bg-orange-100 text-orange-700": status === "interrupted",
        },
        className,
      )}
    >
      {status === "running" && (
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse" />
      )}
      {status === "completed" && (
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-green-500" />
      )}
      {status === "error" && (
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-red-500" />
      )}
      {status === "interrupted" && (
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-orange-500 animate-slow-blink" />
      )}
      {labels[status]}
    </span>
  );
}
