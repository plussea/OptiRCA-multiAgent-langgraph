"use client";
import { ChevronRight } from "lucide-react";
import { useSessionStore } from "../store/session";

interface SubgraphViewerProps {
  currentSubgraph: string | null;
  onNavigate: (subgraph: string | null) => void;
}

const SUBGRAPH_LABELS: Record<string, string> = {
  perception: "感知子图",
  diagnosis: "诊断子图",
  diagnosis_validation: "诊断校验子图",
  planning: "方案子图",
  solution_validation: "方案校验子图",
  human_review: "人工审核子图",
  closure: "回收子图",
};

export function SubgraphBreadcrumbs({ currentSubgraph, onNavigate }: SubgraphViewerProps) {
  if (!currentSubgraph) return null;

  return (
    <div className="flex items-center gap-1 text-sm text-muted-foreground">
      <button
        onClick={() => onNavigate(null)}
        className="hover:text-foreground transition-colors"
      >
        OptiGraph
      </button>
      <ChevronRight className="w-3 h-3" />
      <span className="text-foreground font-medium">
        {SUBGRAPH_LABELS[currentSubgraph] || currentSubgraph}
      </span>
    </div>
  );
}
