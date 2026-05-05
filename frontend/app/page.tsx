"use client";
import { useEffect } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { GraphPanel } from "./components/GraphPanel";
import { HitlPanel } from "./components/HitlPanel";
import { LogStream } from "./components/LogStream";
import { useSessionStore } from "./store/session";

export default function HomePage() {
  const { hitlRequired, logs } = useSessionStore();

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Left: Chat Panel (35%) */}
      <div className="w-[35%] min-w-[320px] max-w-[480px] flex flex-col h-full">
        <ChatPanel />
      </div>

      {/* Right: Graph Panel + LogStream (65%) */}
      <div className="flex-1 flex flex-col h-full min-w-0">
        <div className="flex-1 min-h-0">
          <GraphPanel />
        </div>
        {logs.length > 0 && (
          <div className="h-[160px] border-t border-border flex-shrink-0">
            <LogStream />
          </div>
        )}
      </div>

      {/* HITL Overlay (slides in from right, above everything) */}
      {hitlRequired && <HitlPanel />}
    </main>
  );
}
