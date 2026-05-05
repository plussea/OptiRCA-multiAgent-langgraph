import { create } from "zustand";
import type {
  Message,
  LogEntry,
  HitlPayload,
  SessionState,
  SessionStatus,
} from "../lib/types";

interface SessionStore {
  // Session
  sessionId: string | null;
  status: SessionStatus;
  sessionState: Partial<SessionState>;

  // Chat
  messages: Message[];

  // Graph
  activeNode: string | null;
  completedNodes: string[];

  // HITL
  hitlRequired: boolean;
  hitlPayload: HitlPayload | null;

  // Logs
  logs: LogEntry[];

  // Polling
  pollInterval: ReturnType<typeof setInterval> | null;

  // Actions
  setSessionId: (id: string) => void;
  updateState: (state: SessionState) => void;
  setActiveNode: (nodeId: string) => void;
  markNodeCompleted: (nodeId: string) => void;
  setHitlRequired: (required: boolean) => void;
  setHitlPayload: (payload: HitlPayload | null) => void;
  addMessage: (msg: Omit<Message, "id" | "timestamp">) => void;
  addLog: (entry: Omit<LogEntry, "id" | "timestamp">) => void;
  setPollInterval: (interval: ReturnType<typeof setInterval> | null) => void;
  reset: () => void;
}

const initialState = {
  sessionId: null,
  status: "init" as SessionStatus,
  sessionState: {},
  messages: [],
  activeNode: null,
  completedNodes: [],
  hitlRequired: false,
  hitlPayload: null,
  logs: [],
  pollInterval: null,
};

export const useSessionStore = create<SessionStore>((set, get) => ({
  ...initialState,

  setSessionId: (id) => set({ sessionId: id }),

  updateState: (state) => {
    const prev = get().status;
    const next = state.status;

    const messages: Message[] = [];
    const logs: LogEntry[] = [];

    // Detect status transitions to add system messages and logs
    if (prev !== next) {
      const nodeMap: Record<string, string> = {
        init: "perception",
        perceived: "diagnosis",
        diagnosed: "diagnosis_validation",
        diagnosis_validated: "planning",
        planned: "solution_validation",
        solution_validated: "human_review",
        human_reviewed: "closure",
        closed: "closure",
        error: "closure",
      };

      const nodeId = nodeMap[next] || next;
      const completed = nodeMap[prev] || prev;

      if (prev === "init" && next !== "init") {
        messages.push({
          id: crypto.randomUUID(),
          role: "system",
          content: "感知完成，开始诊断分析",
          timestamp: new Date(),
        });
      }

      if (prev !== "init" && next !== prev) {
        const labelMap: Record<string, string> = {
          perceived: "感知",
          diagnosed: "诊断",
          diagnosis_validated: "诊断校验",
          planned: "方案生成",
          solution_validated: "方案校验",
          human_reviewed: "人工审核",
          closed: "流程完成",
          error: "发生错误",
        };
        messages.push({
          id: crypto.randomUUID(),
          role: "system",
          content: `阶段完成：${labelMap[next] || next}`,
          timestamp: new Date(),
        });
      }

      if (completed !== "init") {
        logs.push({
          id: crypto.randomUUID(),
          timestamp: new Date(),
          node: completed,
          status: next === "error" ? "error" : "complete",
          detail: next === "error" ? "执行出错" : "完成",
        });
      }
      if (next !== "closed" && next !== "error") {
        logs.push({
          id: crypto.randomUUID(),
          timestamp: new Date(),
          node: nodeId,
          status: "start",
          detail: "开始执行",
        });
      }

      set((s) => ({
        status: next,
        sessionState: state,
        activeNode: next !== "closed" && next !== "error" ? (next === "init" ? "perception" : next) : null,
        completedNodes: [...new Set([...s.completedNodes, nodeMap[prev] || prev])],
        hitlRequired: state.pending_human,
        messages: messages.length ? [...s.messages, ...messages] : s.messages,
        logs: logs.length ? [...s.logs, ...logs] : s.logs,
      }));
    } else {
      set((s) => ({
        sessionState: state,
        hitlRequired: state.pending_human,
      }));
    }
  },

  setActiveNode: (nodeId) => set({ activeNode: nodeId }),

  markNodeCompleted: (nodeId) =>
    set((s) => ({
      completedNodes: [...new Set([...s.completedNodes, nodeId])],
      activeNode: null,
    })),

  setHitlRequired: (required) => set({ hitlRequired: required }),

  setHitlPayload: (payload) => set({ hitlPayload: payload }),

  addMessage: (msg) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { ...msg, id: crypto.randomUUID(), timestamp: new Date() },
      ],
    })),

  addLog: (entry) =>
    set((s) => ({
      logs: [
        ...s.logs,
        { ...entry, id: crypto.randomUUID(), timestamp: new Date() },
      ],
    })),

  setPollInterval: (interval) => set({ pollInterval: interval }),

  reset: () => {
    const { pollInterval } = get();
    if (pollInterval) clearInterval(pollInterval);
    set({ ...initialState, pollInterval: null });
  },
}));
