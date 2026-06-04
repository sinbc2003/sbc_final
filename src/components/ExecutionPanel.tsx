import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import {
  ChevronDown, ChevronUp, X, CheckCircle2, AlertCircle, Loader2,
  Copy, Check, FolderOpen, FileText, ExternalLink, ChevronRight,
} from "lucide-react";
import { useStore } from "../store";
import { getCategoryColor } from "../constants";

/* ── 시간 포맷 ───────────────────────────────────── */
function fmtTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString("ko-KR", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* ── 노드 이름 맵 ─────────────────────────────────── */
function useNodeNameMap(): Map<string, string> {
  const nodes = useStore((s) => s.nodes);
  return useMemo(() => {
    const map = new Map<string, string>();
    for (const n of nodes) {
      map.set(n.id, (n.data.label as string) || n.id);
    }
    return map;
  }, [nodes]);
}

function useNodeCategoryMap(): Map<string, string> {
  const nodes = useStore((s) => s.nodes);
  return useMemo(() => {
    const map = new Map<string, string>();
    for (const n of nodes) {
      map.set(n.id, n.data.category as string);
    }
    return map;
  }, [nodes]);
}

/* ── 파일 경로 판별 ───────────────────────────────── */
function isFilePath(val: string): boolean {
  return /^[A-Za-z]:[/\\]/.test(val) || val.startsWith("/tmp/") || val.startsWith("/var/") ||
    /\.(pdf|hwpx?|docx?|xlsx?|csv|txt|png|jpg|json|zip)$/i.test(val);
}

/* ── 복사 버튼 ────────────────────────────────────── */
function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [text]);
  return (
    <button onClick={handleCopy} title="복사"
      className="p-1 rounded hover:bg-[#444] text-gray-500 hover:text-gray-300 transition-colors">
      {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
    </button>
  );
}

/* ── 출력 항목 카드 ───────────────────────────────── */
function OutputCard({ nodeId, nodeName, portName, value, catColor }: {
  nodeId: string; nodeName: string; portName: string; value: string; catColor: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const file = isFilePath(value);
  const displayName = file ? value.split(/[/\\]/).pop() ?? value : "";
  const isLong = value.length > 300;

  const openFile = useCallback(() => {
    fetch("/api/files/open", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: value }),
    }).catch(() => {});
  }, [value]);

  const openFolder = useCallback(() => {
    fetch("/api/files/open-folder", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: value }),
    }).catch(() => {});
  }, [value]);

  return (
    <div className="bg-[#2a2a2a] rounded-lg border border-[#3a3a3a] overflow-hidden">
      {/* 헤더 */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#252525]"
        onClick={() => setExpanded(!expanded)}
        style={{ cursor: isLong || file ? "pointer" : "default" }}>
        <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: catColor }} />
        <span className="text-[11px] font-semibold text-gray-300 truncate">{nodeName}</span>
        <span className="text-[10px] text-gray-500">·</span>
        <span className="text-[10px] text-amber-400">{portName}</span>
        <div className="flex-1" />
        <CopyBtn text={value} />
        {(isLong || file) && (
          <ChevronRight size={12} className={`text-gray-500 transition-transform ${expanded ? "rotate-90" : ""}`} />
        )}
      </div>

      {/* 본문 */}
      <div className="px-3 py-2">
        {file ? (
          /* 파일 출력 */
          <div className="flex items-center gap-2 flex-wrap">
            <FileText size={14} className="text-amber-400 flex-shrink-0" />
            <span className="text-[12px] text-gray-200 font-medium truncate flex-1" title={value}>
              {displayName}
            </span>
            <button onClick={openFile} title="파일 열기"
              className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded
                bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 transition-colors">
              <ExternalLink size={10} /> 열기
            </button>
            <button onClick={openFolder} title="폴더 열기"
              className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium rounded
                bg-gray-600/30 text-gray-400 hover:bg-gray-600/50 transition-colors">
              <FolderOpen size={10} /> 폴더
            </button>
          </div>
        ) : (
          /* 텍스트 출력 */
          <>
            <pre className={`text-[11px] text-gray-300 whitespace-pre-wrap break-words font-mono leading-relaxed
              ${!expanded && isLong ? "max-h-[80px] overflow-hidden" : ""}`}>
              {expanded || !isLong ? value : value.slice(0, 300)}
            </pre>
            {isLong && !expanded && (
              <button onClick={() => setExpanded(true)}
                className="text-[10px] text-amber-400 hover:text-amber-300 mt-1">
                ... 전체 보기 ({value.length.toLocaleString()}자)
              </button>
            )}
          </>
        )}

        {/* 파일 전체 경로 (펼침 시) */}
        {file && expanded && (
          <p className="text-[10px] text-gray-500 mt-1.5 font-mono break-all">{value}</p>
        )}
      </div>
    </div>
  );
}

/* ── 탭 ──────────────────────────────────────────── */
type PanelTab = "logs" | "outputs";

/* ── 메인 패널 ───────────────────────────────────── */
export function ExecutionPanel() {
  const executionStatus = useStore((s) => s.executionStatus);
  const logs = useStore((s) => s.executionLogs);
  const outputs = useStore((s) => s.executionOutputs);
  const panelOpen = useStore((s) => s.executionPanelOpen);
  const togglePanel = useStore((s) => s.toggleExecutionPanel);
  const catMap = useNodeCategoryMap();
  const nameMap = useNodeNameMap();
  const [tab, setTab] = useState<PanelTab>("logs");

  const scrollRef = useRef<HTMLDivElement>(null);
  const isRunning = executionStatus === "running";
  const isDone = executionStatus === "done";
  const isError = executionStatus === "error";
  const hasRun = logs.length > 0 || isRunning || isDone || isError;

  // 실행 중 자동 스크롤
  useEffect(() => {
    if (isRunning && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs.length, isRunning]);

  // 완료 시 출력 탭으로 자동 전환
  useEffect(() => {
    if ((isDone || isError) && Object.keys(outputs).length > 0) {
      setTab("outputs");
    }
    if (isRunning) setTab("logs");
  }, [isDone, isError, isRunning, outputs]);

  const elapsed = useMemo(() => {
    if (logs.length === 0) return 0;
    const first = logs[0].timestamp;
    const last = logs[logs.length - 1].timestamp;
    return ((last - first) / 1000).toFixed(1);
  }, [logs]);

  const outputEntries = useMemo(() => {
    const entries: { nodeId: string; nodeName: string; portName: string; value: string; catColor: string }[] = [];
    for (const [nodeId, ports] of Object.entries(outputs)) {
      for (const [portName, val] of Object.entries(ports)) {
        const str = typeof val === "string" ? val : JSON.stringify(val);
        entries.push({
          nodeId,
          nodeName: nameMap.get(nodeId) || nodeId,
          portName,
          value: str,
          catColor: getCategoryColor(catMap.get(nodeId) ?? ""),
        });
      }
    }
    return entries;
  }, [outputs, nameMap, catMap]);

  if (!hasRun) return null;

  const statusLabel = isRunning ? "실행 중..." : isDone ? "완료" : isError ? "오류" : "";
  const StatusIcon = isRunning ? Loader2 : isDone ? CheckCircle2 : isError ? AlertCircle : null;
  const statusColor = isRunning ? "#e8a028" : isDone ? "#10b981" : isError ? "#ef4444" : "#999";

  return (
    <div className="execution-panel border-t border-gray-200 bg-[#1e1e1e] flex flex-col"
      style={{ minHeight: panelOpen ? 220 : 32, maxHeight: panelOpen ? 400 : 32 }}>
      {/* ── 헤더 ── */}
      <div className="flex items-center justify-between px-3 py-1 select-none flex-shrink-0
                       bg-[#252526] border-b border-[#333]">
        <div className="flex items-center gap-1">
          <button onClick={togglePanel} className="p-0.5 mr-1 text-gray-400 hover:text-gray-200">
            {panelOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          </button>

          {/* 탭 */}
          <button onClick={() => { setTab("logs"); if (!panelOpen) togglePanel(); }}
            className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
              tab === "logs" ? "bg-[#333] text-gray-200" : "text-gray-500 hover:text-gray-300"}`}>
            로그 {logs.length > 0 && <span className="text-gray-500 ml-1">{logs.length}</span>}
          </button>
          <button onClick={() => { setTab("outputs"); if (!panelOpen) togglePanel(); }}
            className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
              tab === "outputs" ? "bg-[#333] text-gray-200" : "text-gray-500 hover:text-gray-300"}`}>
            출력 {outputEntries.length > 0 && (
              <span className={`ml-1 ${tab !== "outputs" ? "text-amber-500" : "text-gray-500"}`}>
                {outputEntries.length}
              </span>
            )}
          </button>
        </div>

        <div className="flex items-center gap-3">
          {elapsed !== 0 && <span className="text-[11px] text-gray-400">{elapsed}초</span>}
          <div className="flex items-center gap-1" style={{ color: statusColor }}>
            {StatusIcon && <StatusIcon size={13} className={isRunning ? "animate-spin" : ""} />}
            <span className="text-[11px] font-medium">{statusLabel}</span>
          </div>
          <button onClick={(e) => { e.stopPropagation(); useStore.getState().toggleExecutionPanel(); }}
            className="p-0.5 rounded hover:bg-[#333] text-gray-500 hover:text-gray-300">
            <X size={13} />
          </button>
        </div>
      </div>

      {/* ── 본문 ── */}
      {panelOpen && (
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {tab === "logs" ? (
            /* 로그 탭 — 비개발자 친화적 단계별 표시 */
            <div className="px-3 py-2 space-y-1">
              {logs.map((log, i) => {
                const cat = catMap.get(log.nodeId) ?? "";
                const color = log.nodeId === "SYSTEM" ? "#ef4444" : getCategoryColor(cat);
                const isError = log.message.startsWith("[오류]") || log.message.startsWith("[치명적 오류]") || log.message.startsWith("[ERROR]");
                const isWarn = log.message.startsWith("[WARN]");
                const isComplete = log.message.startsWith("완료") || log.message.includes("완료");
                const isSave = log.message.startsWith("저장:");

                // 메시지 친화적 변환
                let friendlyMsg = log.message
                  .replace("[ERROR] ", "")
                  .replace("[WARN] ", "")
                  .replace("pymupdf로 변환", "문서 읽는 중")
                  .replace("ZIP+XML 파싱으로 변환", "문서 읽는 중")
                  .replace("pypandoc-hwpx로 변환 완료", "한글 파일 생성 완료");

                return (
                  <div key={i} className={`flex items-center gap-2 py-1 px-2 rounded-md text-[11px]
                    ${isError ? "bg-red-900/20" : isWarn ? "bg-yellow-900/10" : isSave ? "bg-emerald-900/10" : isComplete ? "bg-emerald-900/10" : "bg-transparent"}`}>
                    {/* 상태 아이콘 */}
                    <div className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      style={{ background: isError ? "#ef4444" : isComplete || isSave ? "#10b981" : isWarn ? "#f59e0b" : color }} />
                    {/* 노드명 */}
                    <span className="text-[10px] font-medium flex-shrink-0 text-gray-400 w-[80px] truncate"
                      title={log.nodeName}>
                      {log.nodeName}
                    </span>
                    {/* 메시지 */}
                    <span className={`flex-1 ${isError ? "text-red-400 font-medium" : isComplete || isSave ? "text-emerald-400" : "text-gray-300"}`}>
                      {friendlyMsg}
                    </span>
                    {/* 시간 */}
                    <span className="text-[9px] text-gray-600 flex-shrink-0">{fmtTime(log.timestamp)}</span>
                  </div>
                );
              })}
              {isRunning && <div className="h-2" />}
            </div>
          ) : (
            /* 출력 탭 */
            <div className="p-3 space-y-2">
              {outputEntries.length === 0 ? (
                <p className="text-[12px] text-gray-500 text-center py-6">
                  {isRunning ? "실행 중..." : "출력 없음"}
                </p>
              ) : (
                outputEntries.map((entry, i) => (
                  <OutputCard key={i} {...entry} />
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
