import { useState, useCallback } from "react";
import { Play, Pencil, Loader2, CheckCircle2, AlertCircle, Download, ExternalLink, FolderOpen } from "lucide-react";
import { MiniFlowChart } from "./MiniFlowChart";
import { useStore } from "../store";
import type { WorkflowJSON } from "../types";

interface OutputFile {
  name: string;
  path: string;
  size: number;
  ext: string;
}

interface Props {
  workflow: WorkflowJSON;
  workflowId?: string;
}

export function ChatWorkflowPreview({ workflow, workflowId }: Props) {
  const loadWorkflowJSON = useStore((s) => s.loadWorkflowJSON);
  const setMode = useStore((s) => s.setMode);
  const addChatMessage = useStore((s) => s.addChatMessage);

  const [runState, setRunState] = useState<"idle" | "running" | "done" | "error">("idle");
  const [outputFiles, setOutputFiles] = useState<OutputFile[]>([]);

  const handleOpen = () => {
    loadWorkflowJSON(workflow);
    setMode("design");
  };

  const handleRun = useCallback(async () => {
    setRunState("running");
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(workflow),
      });
      const data = await res.json();
      setRunState(data.success ? "done" : "error");

      // 출력 파일 저장
      const files: OutputFile[] = data.output_files || [];
      if (files.length === 0) {
        // fallback: outputs에서 파일 경로 추출
        Object.entries(data.outputs || {}).forEach(([_, ports]: [string, any]) => {
          Object.entries(ports).forEach(([_, v]: [string, any]) => {
            if (/\.(hwpx?|docx?|xlsx?|pdf|txt|csv|png|jpg|zip)$/i.test(String(v))) {
              files.push({
                name: String(v).split(/[/\\]/).pop() || "",
                path: String(v),
                size: 0,
                ext: "." + String(v).split(".").pop()?.toLowerCase(),
              });
            }
          });
        });
      }
      setOutputFiles(files);

      if (data.success) {
        if (files.length > 0) {
          const fileNames = files.map((f) => f.name).join(", ");
          addChatMessage({ role: "assistant", content: `실행 완료! 파일이 자동으로 열립니다.\n📄 ${fileNames}` });
        } else {
          const outSummary = Object.entries(data.outputs || {})
            .flatMap(([_, ports]: [string, any]) =>
              Object.entries(ports).map(([_, val]: [string, any]) => {
                const s = String(val);
                return s.length > 200 ? s.slice(0, 200) + "..." : s;
              })
            ).join("\n\n");
          if (outSummary) {
            addChatMessage({ role: "assistant", content: `실행 완료:\n\n${outSummary}` });
          }
        }
      } else {
        addChatMessage({ role: "assistant", content: `실행 오류: ${(data.errors || []).join(", ")}` });
      }
    } catch {
      setRunState("error");
      addChatMessage({ role: "assistant", content: "서버 연결 실패" });
    }
  }, [workflow, addChatMessage]);

  const openFile = useCallback((path: string) => {
    fetch("/api/files/open", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).catch(() => {});
  }, []);

  const openFolder = useCallback((path: string) => {
    fetch("/api/files/open-folder", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).catch(() => {});
  }, []);

  const downloadFile = useCallback((path: string) => {
    const url = `/api/files/download-path?path=${encodeURIComponent(path)}`;
    window.open(url, "_blank");
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "";
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const miniNodes = workflow.nodes.map((n) => ({
    id: n.id, type: n.type,
    x: n.position?.x ?? 0, y: n.position?.y ?? 0,
  }));
  const miniEdges = workflow.edges.map((e) => ({ from: e.from, to: e.to }));

  return (
    <div className="mt-2 bg-white/80 rounded-lg border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 border-b border-gray-100 flex justify-center py-2 px-3">
        <MiniFlowChart nodes={miniNodes} edges={miniEdges} width={260} height={90} />
      </div>

      <div className="px-3 py-2">
        <div className="flex flex-wrap gap-1 mb-2">
          {workflow.nodes.slice(0, 6).map((n) => (
            <span key={n.id} className="text-[10px] px-1.5 py-0.5 bg-gray-100 rounded text-gray-600">
              {n.type.replace(/_/g, " ")}
            </span>
          ))}
          {workflow.nodes.length > 6 && (
            <span className="text-[10px] text-gray-400">+{workflow.nodes.length - 6}</span>
          )}
        </div>

        <div className="flex gap-2">
          <button onClick={handleRun} disabled={runState === "running"}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[12px] font-semibold
              rounded-lg transition-colors ${
                runState === "done" ? "bg-emerald-500 text-white" :
                runState === "error" ? "bg-red-500 text-white" :
                "bg-amber-500 text-white hover:bg-amber-600"
              } disabled:opacity-60`}>
            {runState === "running" ? <><Loader2 size={12} className="animate-spin" /> 실행 중...</> :
             runState === "done" ? <><CheckCircle2 size={12} /> 완료</> :
             runState === "error" ? <><AlertCircle size={12} /> 오류</> :
             <><Play size={12} /> 바로 실행</>}
          </button>
          <button onClick={handleOpen}
            className="px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-100
              rounded-lg hover:bg-gray-200 transition-colors">
            <Pencil size={12} />
          </button>
        </div>

        {/* 출력 파일 목록 */}
        {outputFiles.length > 0 && (
          <div className="mt-2 space-y-1.5">
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
              출력 파일
            </div>
            {outputFiles.map((f, i) => (
              <div key={i} className="flex items-center gap-1.5 px-2.5 py-2 bg-emerald-50 border border-emerald-200
                rounded-lg text-[11px]">
                <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-emerald-800 font-medium truncate">{f.name}</div>
                  {f.size > 0 && <div className="text-emerald-500 text-[9px]">{formatSize(f.size)}</div>}
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  <button onClick={() => openFile(f.path)} title="열기"
                    className="p-1 rounded hover:bg-emerald-100 text-emerald-600">
                    <ExternalLink size={12} />
                  </button>
                  <button onClick={() => downloadFile(f.path)} title="다운로드"
                    className="p-1 rounded hover:bg-emerald-100 text-emerald-600">
                    <Download size={12} />
                  </button>
                  <button onClick={() => openFolder(f.path)} title="폴더 열기"
                    className="p-1 rounded hover:bg-emerald-100 text-emerald-600">
                    <FolderOpen size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
