"use client";
import { X, Clock, Cpu, Layers } from "lucide-react";
import { clsx } from "clsx";

interface NodeDetailDrawerProps {
  nodeId: string;
  label: string;
  detail: Record<string, unknown> | null;
  onClose: () => void;
}

export function NodeDetailDrawer({ nodeId, label, detail, onClose }: NodeDetailDrawerProps) {
  return (
    <div className="fixed right-0 top-0 z-50 h-full w-80 bg-card border-l border-border shadow-xl flex flex-col animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold">{label}</h3>
          <p className="text-xs text-muted-foreground font-mono">{nodeId}</p>
        </div>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {detail ? (
          <>
            {/* Output section */}
            <section>
              <h4 className="text-xs font-semibold text-muted-foreground uppercase mb-2 flex items-center gap-1">
                <Layers className="w-3 h-3" /> 输出结果
              </h4>
              <div className="rounded-lg border border-border bg-muted/50 p-3">
                <pre className="text-xs overflow-x-auto whitespace-pre-wrap">
                  {JSON.stringify(detail, null, 2)}
                </pre>
              </div>
            </section>
          </>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-8">
            暂无节点详情
          </p>
        )}
      </div>
    </div>
  );
}
