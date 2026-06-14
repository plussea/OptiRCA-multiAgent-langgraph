"use client";
import { useCallback, useRef, useState } from "react";
import { Upload, SendHorizonal, FileText, Sparkles, X } from "lucide-react";
import { clsx } from "clsx";
import { MessageBubble } from "./MessageBubble";
import { useSessionStore } from "../store/session";
import { createSession, fetchSessionState } from "../lib/api";
import { DEMO_CSV, DEMO_FILE_NAME, DEMO_MANIFEST } from "../lib/demoData";

type DemoManifest = typeof DEMO_MANIFEST;

export function ChatPanel() {
  const { messages, sessionId, status, addMessage, setSessionId, updateState, setPollInterval } =
    useSessionStore();

  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // Demo manifest is bundled into the JS module (see lib/demoData.ts) so it's
  // available synchronously — no fetch, no 404, works under next start too.
  const [demo] = useState<DemoManifest>(DEMO_MANIFEST);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const isRunning = !["init", "closed", "error"].includes(status);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const startPolling = useCallback(
    (sid: string) => {
      const interval = setInterval(async () => {
        try {
          const state = await fetchSessionState(sid);
          updateState(state);
          // Stop polling on terminal states OR while waiting for human input.
          // We also stop when the backend hasn't returned a status (defensive —
          // means the session was lost).
          const terminal = !state.status || state.status === "closed" || state.status === "error";
          if (terminal || state.pending_human) {
            clearInterval(interval);
            setPollInterval(null);
          }
        } catch {
          clearInterval(interval);
          setPollInterval(null);
        }
      }, 2000);
      setPollInterval(interval);
    },
    [updateState, setPollInterval],
  );

  const handleUpload = useCallback(
    async (f: File) => {
      // Backend (FastAPI) currently only accepts CSV. Reject other types
      // early with a clear message rather than letting the server 500.
      if (!f.name.toLowerCase().endsWith(".csv")) {
        addMessage({
          role: "error",
          content: `不支持的文件类型: ${f.name}。当前仅支持: .csv`,
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
        // axios errors have a more useful message in err.response; surface it.
        const ax = err as { response?: { data?: { detail?: string }; status?: number }; message?: string };
        const detail =
          ax?.response?.data?.detail ||
          ax?.response?.status
            ? `HTTP ${ax.response!.status}: ${ax.response!.data?.detail || "请求失败"}`
            : ax?.message || String(err);
        addMessage({
          role: "error",
          content: `上传失败: ${detail}`,
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
    // The current backend only takes a file — there's no separate "send
    // message with notes" endpoint. The chat's text input is reserved for
    // future use (e.g. asking the LLM follow-up questions). For now we
    // just attach the note to the chat as a user message and clear the
    // input; uploading + sending are the same action handled by
    // handleUpload. The button is disabled unless a file is already chosen
    // AND not yet submitted, so the most common path is "drop CSV →
    // wait". Keeping this stub means the UI stays consistent if we add
    // the endpoint later.
    if (!text.trim()) return;
    addMessage({ role: "user", content: text.trim() });
    setText("");
  }, [text, addMessage]);

  // Build the demo File from the inlined CSV string and feed it through
  // the same upload path that a real file drop would. This keeps the rest
  // of the pipeline (createSession → poll → graph) identical to the
  // manual flow, and it works under any Next.js runtime (dev, prod,
  // standalone) because we never touch static files at all.
  const handleUseDemo = useCallback(async () => {
    if (uploading || isRunning) return;
    try {
      // Use a real Blob with explicit UTF-8 bytes so the file's reported
      // size matches the on-disk CSV (some browsers compute size from
      // chars not bytes when given a string).
      const bytes = new TextEncoder().encode(DEMO_CSV);
      const demoFile = new File([bytes], DEMO_FILE_NAME, { type: "text/csv" });
      addMessage({
        role: "system",
        content: `✨ 已加载默认演示: ${demo.name} (${demo.rowCount} 条告警)`,
      });
      await handleUpload(demoFile);
    } catch (err) {
      addMessage({
        role: "error",
        content: `演示数据加载失败: ${err instanceof Error ? err.message : String(err)}`,
      });
    }
  }, [uploading, isRunning, demo, addMessage, handleUpload]);

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
            <p className="text-xs mt-1">支持: .csv（其他格式暂不支持）</p>
            <p className="text-xs mt-1">或拖拽文件到此处</p>

            {/* Default demo input — uses the inlined CSV from
                lib/demoData.ts and feeds it through the same upload
                pipeline as a real file. */}
            <button
              onClick={handleUseDemo}
              disabled={uploading || isRunning}
              className={clsx(
                "mt-5 group inline-flex flex-col items-start gap-1.5 rounded-xl border-2 border-dashed",
                "border-blue-300 bg-blue-50/60 hover:bg-blue-50 hover:border-blue-400",
                "px-4 py-3 text-left max-w-[280px] transition-colors",
                "disabled:opacity-50 disabled:cursor-not-allowed",
              )}
            >
              <span className="flex items-center gap-1.5 text-xs font-semibold text-blue-700">
                <Sparkles className="w-3.5 h-3.5" />
                试用默认演示数据
              </span>
              <span className="text-[11px] text-blue-900/70 leading-snug">
                {demo.description}
              </span>
              {demo && (
                <span className="flex flex-wrap gap-1 mt-1">
                  {demo.tags.slice(0, 3).map((t) => (
                    <span
                      key={t}
                      className="text-[10px] rounded-full bg-white/70 text-blue-700 px-1.5 py-0.5 border border-blue-200"
                    >
                      {t}
                    </span>
                  ))}
                </span>
              )}
            </button>
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
            accept=".csv"
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
