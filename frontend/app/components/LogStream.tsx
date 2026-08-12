"use client";
import { useEffect, useRef } from "react";
import { format } from "date-fns";
import { useSessionStore } from "../store/session";

export function LogStream() {
  const { logs } = useSessionStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className="h-20 border-t border-border bg-muted/30 overflow-y-auto px-3 py-2">
      <div className="text-xs font-mono space-y-0.5">
        {logs.length === 0 && (
          <p className="text-muted-foreground">等待执行…</p>
        )}
        {logs.map((entry) => {
          const timeStr = format(entry.timestamp, "HH:mm:ss.SSS");
          return (
            <p key={entry.id} className="flex gap-2">
              <span className="text-muted-foreground shrink-0">[{timeStr}]</span>
              <span
                className={
                  entry.status === "error"
                    ? "text-red-600"
                    : entry.status === "complete"
                    ? "text-green-600"
                    : "text-blue-600"
                }
              >
                [{entry.node}]
              </span>
              <span className={entry.status === "error" ? "text-red-500" : "text-foreground"}>
                {entry.detail}
              </span>
            </p>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
