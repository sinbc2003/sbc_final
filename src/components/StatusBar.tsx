import { useEffect, useState, useCallback } from "react";
import { GitBranch, Cpu, Wifi, WifiOff, Database, Monitor } from "lucide-react";
import { useStore } from "../store";

interface LiveApp { name: string; connected: boolean; doc_name: string }

export function StatusBar() {
  const nodes = useStore((s) => s.nodes);
  const edges = useStore((s) => s.edges);
  const executionStatus = useStore((s) => s.executionStatus);
  const mode = useStore((s) => s.mode);

  const [engineStatus, setEngineStatus] = useState<"checking" | "online" | "offline">("checking");
  const [engineNodes, setEngineNodes] = useState(0);
  const [ragCount, setRagCount] = useState(0);
  const [liveApps, setLiveApps] = useState<Record<string, LiveApp>>({});

  // 엔진 상태 주기적 확인 (10초)
  const checkEngine = useCallback(async () => {
    try {
      const res = await fetch("/api/health", { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        setEngineStatus("online");
        setEngineNodes(data.nodes ?? 0);
      } else {
        setEngineStatus("offline");
      }
    } catch {
      setEngineStatus("offline");
    }
    // RAG 상태
    try {
      const res = await fetch("/api/rag/stats", { signal: AbortSignal.timeout(2000) });
      if (res.ok) {
        const data = await res.json();
        setRagCount(data.count ?? 0);
      }
    } catch {}
    // 라이브 앱 감지
    try {
      const res = await fetch("/api/live/detect", { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        if (!data.error) setLiveApps(data);
      }
    } catch {}
  }, []);

  useEffect(() => {
    checkEngine();
    const timer = setInterval(checkEngine, 10_000);
    return () => clearInterval(timer);
  }, [checkEngine]);

  const statusLabel = { idle: "준비", running: "실행 중", done: "완료", error: "오류" }[executionStatus];
  const statusColor = { idle: "bg-gray-400", running: "bg-amber-400 animate-pulse", done: "bg-emerald-400", error: "bg-red-400" }[executionStatus];

  return (
    <div className="h-6 bg-white border-t border-tf-border flex items-center px-3 gap-4 text-[10px] text-gray-500 flex-shrink-0">
      <div className="flex items-center gap-1.5">
        <div className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
        <span>{statusLabel}</span>
      </div>
      <div className="w-px h-3 bg-gray-200" />
      <div className="flex items-center gap-1">
        <GitBranch size={10} />
        <span>노드 {nodes.length} · 연결 {edges.length}</span>
      </div>
      <div className="w-px h-3 bg-gray-200" />
      <span>{{ home: "홈", design: "설계 모드", chat: "채팅 모드", manager: "관리 모드" }[mode]}</span>
      <div className="flex-1" />
      {Object.entries(liveApps).some(([, a]) => a.connected || a.doc_name) && (
        <>
          <div className="flex items-center gap-1.5">
            <Monitor size={10} className="text-blue-500" />
            {Object.entries(liveApps).map(([key, app]) =>
              app.connected ? (
                <span key={key} className="text-blue-600 font-medium" title={app.doc_name}>
                  {app.name}
                </span>
              ) : app.doc_name ? (
                <span key={key} className="text-gray-500" title={`${app.name} ${app.doc_name}`}>
                  {app.name}
                </span>
              ) : null
            )}
          </div>
          <div className="w-px h-3 bg-gray-200" />
        </>
      )}
      {ragCount > 0 && (
        <div className="flex items-center gap-1 text-violet-500">
          <Database size={10} />
          <span>RAG {ragCount}</span>
        </div>
      )}
      <div className="flex items-center gap-1">
        <Cpu size={10} />
        <span className={engineStatus === "online" ? "text-emerald-600" : engineStatus === "offline" ? "text-red-500" : "text-gray-400"}>
          {engineStatus === "online" ? `엔진 (${engineNodes}도구)` : engineStatus === "offline" ? "엔진 오프라인" : "확인 중..."}
        </span>
      </div>
      <div className="flex items-center gap-1">
        {engineStatus === "online" ? <Wifi size={10} className="text-emerald-500" /> : <WifiOff size={10} className="text-red-400" />}
      </div>
    </div>
  );
}
