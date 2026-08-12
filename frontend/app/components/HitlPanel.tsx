"use client";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle, XCircle, ArrowUpCircle, X } from "lucide-react";
import { clsx } from "clsx";
import { useSessionStore } from "../store/session";
import { fetchReviewPackage, submitHumanDecision } from "../lib/api";

export function HitlPanel() {
  const { sessionId, hitlPayload, hitlRequired, setHitlRequired, setHitlPayload, addMessage } =
    useSessionStore();

  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);

  // Load review package when HITL required
  useEffect(() => {
    if (!hitlRequired || !sessionId) return;
    fetchReviewPackage(sessionId)
      .then((pkg) => setHitlPayload(pkg))
      .catch(() => {});
  }, [hitlRequired, sessionId, setHitlPayload]);

  // Countdown timer
  useEffect(() => {
    if (!hitlPayload?.timeout_seconds) return;
    setCountdown(hitlPayload.timeout_seconds);
    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c === null || c <= 1) {
          clearInterval(timer);
          return 0;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [hitlPayload]);

  const handleDecision = useCallback(
    async (
      decision: "approved" | "rejected" | "escalated",
    ) => {
      if (!sessionId || submitting) return;
      setSubmitting(true);
      try {
        const result = await submitHumanDecision(sessionId, decision, notes);
        addMessage({
          role: "hitl",
          content: `人工决策: ${decision} — ${notes || "(无备注)"}`,
        });
        setHitlRequired(false);
        setHitlPayload(null);
        setNotes("");
      } catch (err) {
        addMessage({
          role: "error",
          content: `决策提交失败: ${err instanceof Error ? err.message : String(err)}`,
        });
      } finally {
        setSubmitting(false);
      }
    },
    [sessionId, notes, submitting, addMessage, setHitlRequired, setHitlPayload],
  );

  if (!hitlRequired || !hitlPayload) return null;

  const { diagnosis, planning, diagnosis_validation, solution_validation } = hitlPayload;

  return (
    <div className="fixed right-0 top-0 z-50 h-full w-[400px] bg-card border-l border-border shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-4 border-b border-border bg-orange-50">
        <AlertTriangle className="w-5 h-5 text-orange-600" />
        <div className="flex-1">
          <h3 className="text-sm font-bold text-orange-800">人工审核待决策</h3>
          <p className="text-xs text-orange-600 font-mono">
            {sessionId?.slice(0, 12)}…
          </p>
        </div>
        <button
          onClick={() => { setHitlRequired(false); }}
          className="text-orange-400 hover:text-orange-700 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">

        {/* Diagnosis */}
        <section className="rounded-lg border border-border p-3 space-y-1">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1">
            📋 诊断结论
          </h4>
          <p className="text-sm font-medium">
            根因: <span className="text-red-600">{diagnosis?.root_cause ?? "—"}</span>
          </p>
          <p className="text-sm text-muted-foreground">
            置信度: {diagnosis?.confidence != null ? `${(diagnosis.confidence * 100).toFixed(0)}%` : "—"}
          </p>
          {diagnosis?.evidence?.length ? (
            <p className="text-xs text-muted-foreground">
              证据: {diagnosis.evidence.join(", ")}
            </p>
          ) : null}
        </section>

        {/* Planning */}
        <section className="rounded-lg border border-border p-3 space-y-1">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1">
            📋 修复方案
          </h4>
          {planning?.final_plan?.steps?.map((step, i) => (
            <p key={i} className="text-sm">
              {i + 1}. {step}
            </p>
          )) ?? <p className="text-sm text-muted-foreground">—</p>}
          {planning?.rollback_procedure && (
            <p className="text-xs text-muted-foreground mt-1">
              回滚: {planning.rollback_procedure}
            </p>
          )}
        </section>

        {/* Validation */}
        <section className="rounded-lg border border-border p-3 space-y-1">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1">
            📋 校验结果
          </h4>
          <p className="text-sm flex items-center gap-2">
            诊断校验:
            {diagnosis_validation?.validation_passed ? (
              <span className="flex items-center gap-1 text-green-600">
                <CheckCircle className="w-3.5 h-3.5" /> 通过
              </span>
            ) : (
              <span className="flex items-center gap-1 text-red-600">
                <XCircle className="w-3.5 h-3.5" /> 未通过
              </span>
            )}
          </p>
          <p className="text-sm flex items-center gap-2">
            方案校验:
            {solution_validation?.solution_valid ? (
              <span className="flex items-center gap-1 text-green-600">
                <CheckCircle className="w-3.5 h-3.5" /> 通过
              </span>
            ) : (
              <span className="flex items-center gap-1 text-red-600">
                <XCircle className="w-3.5 h-3.5" /> 未通过
              </span>
            )}
            {solution_validation?.risk_level && (
              <span
                className={clsx("text-xs rounded px-1.5 py-0.5", {
                  "bg-green-100 text-green-700": solution_validation.risk_level === "low",
                  "bg-yellow-100 text-yellow-700": solution_validation.risk_level === "medium",
                  "bg-red-100 text-red-700": solution_validation.risk_level === "high",
                })}
              >
                {solution_validation.risk_level === "low"
                  ? "低风险"
                  : solution_validation.risk_level === "medium"
                  ? "中风险"
                  : "高风险"}
              </span>
            )}
          </p>
        </section>

        {/* Notes */}
        <section className="space-y-1">
          <label className="text-xs font-semibold text-muted-foreground uppercase">
            审核意见 (可选)
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="输入审核意见或备注…"
            rows={3}
            className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </section>

        {/* Countdown */}
        {countdown !== null && (
          <p className="text-xs text-center text-muted-foreground">
            剩余时间: {Math.floor(countdown / 60)}:{String(countdown % 60).padStart(2, "0")}
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="px-4 py-4 border-t border-border space-y-2">
        <button
          onClick={() => handleDecision("approved")}
          disabled={submitting}
          className={clsx(
            "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors",
            "bg-green-600 text-white hover:bg-green-700",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          <CheckCircle className="w-4 h-4" />
          批准执行
        </button>

        <button
          onClick={() => handleDecision("rejected")}
          disabled={submitting}
          className={clsx(
            "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors",
            "bg-red-600 text-white hover:bg-red-700",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          <XCircle className="w-4 h-4" />
          驳回重制
        </button>

        <button
          onClick={() => handleDecision("escalated")}
          disabled={submitting}
          className={clsx(
            "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors",
            "bg-orange-500 text-white hover:bg-orange-600",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          <ArrowUpCircle className="w-4 h-4" />
          升级上报
        </button>
      </div>
    </div>
  );
}
