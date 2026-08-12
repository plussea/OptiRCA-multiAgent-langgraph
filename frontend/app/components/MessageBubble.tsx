"use client";
import { clsx } from "clsx";
import { format } from "date-fns";
import type { Message } from "../lib/types";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const timeStr = format(message.timestamp, "HH:mm:ss");

  return (
    <div
      className={clsx(
        "flex flex-col rounded-xl px-4 py-3 text-sm",
        "animate-in slide-in-from-bottom-2 duration-200",
        {
          // System — gray
          "self-start bg-muted text-foreground border border-border":
            message.role === "system",
          // User — blue
          "self-end bg-blue-50 text-blue-900 border border-blue-200":
            message.role === "user",
          // Error — red
          "self-start bg-red-50 text-red-800 border border-red-200":
            message.role === "error",
          // HITL — orange
          "self-start bg-orange-50 text-orange-800 border border-orange-300 ring-2 ring-orange-300":
            message.role === "hitl",
        },
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-semibold opacity-70">
          {message.role === "system"
            ? "🤖 System"
            : message.role === "user"
            ? "👤 User"
            : message.role === "error"
            ? "❌ Error"
            : "⚠️ HITL"}
        </span>
        <span className="text-xs opacity-50">{timeStr}</span>
      </div>
      <p className="leading-relaxed whitespace-pre-wrap">{message.content}</p>
    </div>
  );
}
