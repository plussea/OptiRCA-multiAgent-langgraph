"use client";
import { useCallback, useRef, useState } from "react";
import { Upload, SendHorizonal, FileText, X } from "lucide-react";
import { clsx } from "clsx";
import { MessageBubble } from "./MessageBubble";
import { useSessionStore } from "../store/session";
import { createSession, fetchSessionState } from "../lib/api";

export function ChatPanel() {
  const { messages, sessionId, status, addMessage, setSessionId, updateState, setPollInterval } =
    useSessionStore();

  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const startPolling = useCallback(
    (sid: string) => {
      const interval = setInterval(async () => {
        try {
          const state = await fetchSessionState(sid);
          updateState(state);
          if (state.pending_human || state.status === "closed" || state.status === "error") {
            clearInterval(interval);
          }
        } catch {
          clearInterval(interval);
        }
      }, 2000);
      setPollInterval(interval);
    },
    [updateState, setPollInterval],
  );

  const handleUpload = useCallback(
    async (f: File) => {
      if (!f.name.match(/\.(csv|xlsx?|png|jpg|jpeg)$/i)) {
        addMessage({
          role: "error",
          content: `不支持的文件类型: ${f.name}。支持: .csv, .xlsx, .png, .jpg`,
        });
        return;
      }

      setUploading(true);
      setFile(f);

      try {
        addMessage({
          role: "user",
          content: `上传文件: ${f.name} (${(f.size / 1024).toFixed(1)} KB)`,
        });

        const result = await createSession(f);
        setSessionId(result.session_id);

        addMessage({
          role: "system",
          content: `会话已创建: ${result.session_id}，开始处理...`,
        });

        startPolling(result.session_id);
      } catch (err) {
        addMessage({
          role: "error",
          content: `上传失败: ${err instanceof Error ? err.message : String(err)}`,
        });
        setFile(null);
      } finally {
        setUploading(false);
      }
    },
    [addMessage, setSessionId, startPolling],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleUpload(f);
    },
    [handleUpload],
  );

  const handleSend = useCallback(async () => {
    if (!text.trim() || !file) return;

    addMessage({ role: "user", content: text.trim() });
    setText("");
  }, [text, file, addMessage]);

  const isRunning = !["init", "closed", "error"].includes(status);

  return (
    <div className="flex flex-col h-full border-r border-border bg-card">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h2 className="text-sm font-semibold">会话</h2>
          {sessionId && (
            <p className="text-xs text-muted-foreground font-mono">{sessionId.slice(0, 8)}…</p>
          )}
        </div>
        {sessionId && (
          <button
            onClick={() => {
              useSessionStore.getState().reset();
              setFile(null);
              setText("");
            }}
            className="text-xs text-muted-foreground hover:text-destructive transition-colors"
          >
            新会话
          </button>
        )}
      </div>

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3"
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
            <Upload className="w-10 h-10 mb-3 opacity-30" />
            <p className="text-sm font-medium">上传告警文件开始诊断</p>
            <p className="text-xs mt-1">支持 CSV、XLSX、PNG、JPG</p>
            <p className="text-xs mt-1">或拖拽文件到此处</p>
          </div>
        )}

        {dragOver && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-blue-50/80 rounded-lg border-2 border-dashed border-blue-400">
            <p className="text-blue-600 font-medium">释放以上传文件</p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* File Card */}
      {file && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-2">
          <FileText className="w-4 h-4 text-blue-500 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium truncate">{file.name}</p>
            <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB</p>
          </div>
          {isRunning ? (
            <span className="text-xs text-green-600 font-medium">处理中…</span>
          ) : (
            <button
              onClick={() => { setFile(null); }}
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      )}

      {/* Input Area */}
      <div className="p-4 border-t border-border space-y-2">
        <div className="flex gap-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            className={clsx(
              "flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm transition-colors",
              "hover:bg-muted",
            )}
          >
            <Upload className="w-4 h-4" />
            <span className="hidden sm:inline">上传</span>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.png,.jpg,.jpeg"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUpload(f);
            }}
          />

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="输入备注信息（可选）…"
            rows={1}
            className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />

          <button
            onClick={handleSend}
            disabled={!file || !text.trim() || uploading || isRunning}
            className={clsx(
              "flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
              "bg-primary text-primary-foreground hover:bg-primary/90",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
          >
            {uploading ? (
              <span className="animate-spin">⟳</span>
            ) : (
              <SendHorizonal className="w-4 h-4" />
            )}
            <span className="hidden sm:inline">发送</span>
          </button>
        </div>
        <p className="text-xs text-center text-muted-foreground">
          {file ? "点击发送启动诊断流水线" : "请先上传告警文件"}
        </p>
      </div>
    </div>
  );
}
