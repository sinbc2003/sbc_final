import { useState, useEffect, useRef, useCallback } from "react";
import {
  ArrowLeft, Upload, Play, Loader2, CheckCircle2, AlertCircle,
  FileText, Copy, Check, FolderOpen, X, File,
} from "lucide-react";

/* ── 타입 ── */
interface PresetFull {
  id: string;
  name: string;
  description: string;
  nodes: { id: string; type: string; params: Record<string, any>; position: { x: number; y: number } }[];
  edges: any[];
  user_inputs?: any[];
  _meta?: { name: string; description: string; tags: string[] };
}

interface UserInput {
  nodeId: string;
  nodeType: string;
  label: string;
  kind: "file" | "text";
  accept?: string[];
  value: string;
}

type RunStatus = "idle" | "running" | "done" | "error";

interface LogEntry {
  nodeName: string;
  message: string;
  timestamp: number;
}

/* ── 프리셋에서 사용자 입력 추출 ── */
function extractUserInputs(preset: PresetFull): UserInput[] {
  const inputs: UserInput[] = [];
  for (const node of preset.nodes) {
    if (node.type === "file_input") {
      inputs.push({
        nodeId: node.id,
        nodeType: node.type,
        label: `파일 입력${inputs.filter((i) => i.kind === "file").length > 0 ? ` ${inputs.filter((i) => i.kind === "file").length + 1}` : ""}`,
        kind: "file",
        value: "",
      });
    } else if (node.type === "text_input") {
      inputs.push({
        nodeId: node.id,
        nodeType: node.type,
        label: `텍스트 입력${inputs.filter((i) => i.kind === "text").length > 0 ? ` ${inputs.filter((i) => i.kind === "text").length + 1}` : ""}`,
        kind: "text",
        value: node.params.content || "",
      });
    }
  }
  return inputs;
}

/* ── 파일 경로 판별 ── */
function isFilePath(val: string): boolean {
  return (
    /^[A-Za-z]:[/\\]/.test(val) ||
    val.startsWith("/tmp/") ||
    /\.(pdf|hwpx?|docx?|xlsx?|csv|txt|png|jpg|json|zip)$/i.test(val)
  );
}

/* ── 시간 포맷 ── */
function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("ko-KR", {
    hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/* ── 복사 버튼 ── */
function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
      title="복사"
    >
      {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
    </button>
  );
}

/* ════════════════════════════════════════════════════ */
/*  TaskRunner                                         */
/* ════════════════════════════════════════════════════ */

export function TaskRunner({ presetId, onBack }: { presetId: string; onBack: () => void }) {
  const [preset, setPreset] = useState<PresetFull | null>(null);
  const [userInputs, setUserInputs] = useState<UserInput[]>([]);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [outputs, setOutputs] = useState<Record<string, Record<string, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  /* 프리셋 로드 */
  useEffect(() => {
    fetch(`/api/workflows/${presetId}`)
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then((data: PresetFull) => {
        setPreset(data);
        setUserInputs(extractUserInputs(data));
      })
      .catch(() => setLoadError(true));
  }, [presetId]);

  /* 로그 자동 스크롤 */
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  /* 입력값 업데이트 */
  const updateInput = useCallback((idx: number, value: string) => {
    setUserInputs((prev) => prev.map((inp, i) => (i === idx ? { ...inp, value } : inp)));
  }, []);

  /* 파일 업로드 핸들러 */
  const handleFileUpload = useCallback(async (idx: number, file: globalThis.File) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/files/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (data.path) {
        updateInput(idx, data.path);
      }
    } catch {
      // fallback: 파일 이름만 표시
      updateInput(idx, file.name);
    }
  }, [updateInput]);

  /* 드래그&드롭 */
  const handleDrop = useCallback((idx: number, e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(idx, file);
  }, [handleFileUpload]);

  /* 실행 가능 여부 */
  const canRun =
    preset &&
    status !== "running" &&
    userInputs.every((inp) => inp.kind === "text" || inp.value);

  /* ── 실행 ── */
  const runTask = useCallback(async () => {
    if (!preset || !canRun) return;
    setStatus("running");
    setLogs([]);
    setOutputs({});
    setError(null);

    // 프리셋에 사용자 입력 주입
    const wf = JSON.parse(JSON.stringify(preset));
    for (const inp of userInputs) {
      const node = wf.nodes.find((n: any) => n.id === inp.nodeId);
      if (!node) continue;
      if (inp.kind === "file") node.params.path = inp.value;
      if (inp.kind === "text") node.params.content = inp.value;
    }

    // 워크플로우 메타 추가
    wf.version = wf.version || "1.0.0";
    wf.created_at = wf.created_at || new Date().toISOString();
    wf.user_inputs = wf.user_inputs || [];

    try {
      const resp = await fetch("/api/run-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(wf),
      });

      if (!resp.body) { setStatus("error"); setError("서버 응답 없음"); return; }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const match = line.match(/^data:\s*(.+)/);
          if (!match) continue;
          let evt: any;
          try { evt = JSON.parse(match[1]); } catch { continue; }

          if (evt.event === "node_log") {
            setLogs((prev) => [...prev, {
              nodeName: evt.node_name || evt.node_id,
              message: evt.message,
              timestamp: Date.now(),
            }]);
          }
          if (evt.event === "done") {
            setOutputs(evt.outputs || {});
            setStatus(evt.success ? "done" : "error");
            // 엔진의 구체적 한국어 오류를 그대로 노출(범용 문구로 뭉개지 않음).
            if (!evt.success) {
              const errs = (evt.errors || []) as string[];
              setError(errs.length ? errs.join("\n") : "일부 노드에서 오류가 발생했습니다.");
            }
          }
          if (evt.event === "error") {
            setStatus("error");
            setError(evt.message || "실행 중 오류 발생");
          }
        }
      }
    } catch {
      setStatus("error");
      setError("서버 연결 실패 — 엔진이 실행 중인지 확인하세요.");
    }
  }, [preset, canRun, userInputs]);

  /* 파일 열기 */
  const openFile = useCallback((path: string) => {
    fetch("/api/files/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).catch(() => {});
  }, []);

  /* ── 로딩/에러 ── */
  if (loadError) {
    return (
      <div className="flex-1 flex items-center justify-center bg-tf-bg">
        <div className="text-center">
          <AlertCircle size={32} className="text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-500 mb-4">프리셋을 불러올 수 없습니다.</p>
          <button onClick={onBack} className="text-sm text-amber-600 hover:underline">돌아가기</button>
        </div>
      </div>
    );
  }

  if (!preset) {
    return (
      <div className="flex-1 flex items-center justify-center bg-tf-bg">
        <Loader2 size={20} className="animate-spin text-gray-400" />
      </div>
    );
  }

  /* ── 결과 출력 파싱 ── */
  const outputEntries: { nodeId: string; portName: string; value: string }[] = [];
  for (const [nodeId, ports] of Object.entries(outputs)) {
    for (const [portName, value] of Object.entries(ports)) {
      if (value) outputEntries.push({ nodeId, portName, value });
    }
  }
  const outputFiles = outputEntries.filter((o) => isFilePath(o.value));
  const outputTexts = outputEntries.filter((o) => !isFilePath(o.value));

  /* ════════════════════════════════════════════════ */
  /*  렌더                                            */
  /* ════════════════════════════════════════════════ */
  return (
    <div className="flex-1 bg-tf-bg overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* ── 헤더 ── */}
        <div className="flex items-center gap-3 mb-8">
          <button
            onClick={onBack}
            className="p-2 rounded-lg hover:bg-white hover:shadow-sm text-gray-500 hover:text-gray-700 transition-all"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h2 className="text-lg font-bold text-gray-800">
              {preset._meta?.name || preset.name}
            </h2>
            <p className="text-[12px] text-gray-500 mt-0.5">
              {preset._meta?.description || preset.description}
            </p>
          </div>
        </div>

        {/* ── 입력 폼 ── */}
        <div className="space-y-4 mb-6">
          {userInputs.map((inp, idx) => (
            <div key={inp.nodeId} className="bg-white rounded-xl border border-gray-200 p-5">
              <label className="block text-[13px] font-semibold text-gray-700 mb-3">
                {inp.label}
              </label>

              {inp.kind === "file" ? (
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => handleDrop(idx, e)}
                  className={`relative border-2 border-dashed rounded-lg p-6 text-center transition-colors
                    ${inp.value
                      ? "border-emerald-300 bg-emerald-50/50"
                      : "border-gray-200 hover:border-amber-300 bg-gray-50/50"
                    }`}
                >
                  {inp.value ? (
                    <div className="flex items-center justify-center gap-2">
                      <File size={16} className="text-emerald-600" />
                      <span className="text-[13px] text-emerald-700 font-medium truncate max-w-sm">
                        {inp.value.split(/[/\\]/).pop()}
                      </span>
                      <button
                        onClick={() => updateInput(idx, "")}
                        className="p-0.5 rounded hover:bg-emerald-100 text-emerald-400"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ) : (
                    <>
                      <Upload size={24} className="text-gray-300 mx-auto mb-2" />
                      <p className="text-[13px] text-gray-500 mb-1">
                        파일을 여기에 드래그하거나
                      </p>
                      <label className="inline-block text-[13px] text-amber-600 font-medium cursor-pointer hover:underline">
                        파일 선택
                        <input
                          type="file"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) handleFileUpload(idx, f);
                          }}
                        />
                      </label>
                    </>
                  )}
                </div>
              ) : (
                <textarea
                  value={inp.value}
                  onChange={(e) => updateInput(idx, e.target.value)}
                  rows={4}
                  placeholder="내용을 입력하세요..."
                  className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-[13px]
                    text-gray-700 focus:outline-none focus:ring-2 focus:ring-amber-200 focus:border-amber-300
                    resize-y placeholder:text-gray-400"
                />
              )}
            </div>
          ))}

          {userInputs.length === 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-5 text-center">
              <p className="text-[13px] text-gray-500">
                이 업무는 추가 입력 없이 바로 실행됩니다.
              </p>
            </div>
          )}
        </div>

        {/* ── 실행 버튼 ── */}
        <div className="flex justify-center mb-8">
          <button
            onClick={runTask}
            disabled={!canRun}
            className={`flex items-center gap-2 px-8 py-3 rounded-xl text-[14px] font-semibold
              transition-all shadow-sm
              ${status === "running"
                ? "bg-amber-50 text-amber-600 cursor-wait"
                : status === "done"
                ? "bg-emerald-500 text-white hover:bg-emerald-600 active:scale-[0.98]"
                : status === "error"
                ? "bg-red-50 text-red-600 hover:bg-red-100"
                : canRun
                ? "bg-amber-500 text-white hover:bg-amber-600 active:scale-[0.98]"
                : "bg-gray-100 text-gray-400 cursor-not-allowed"
              }`}
          >
            {status === "running" ? (
              <><Loader2 size={16} className="animate-spin" /> 실행 중...</>
            ) : status === "done" ? (
              <><CheckCircle2 size={16} /> 다시 실행</>
            ) : status === "error" ? (
              <><AlertCircle size={16} /> 재시도</>
            ) : (
              <><Play size={16} /> 실행</>
            )}
          </button>
        </div>

        {/* ── 로그 ── */}
        {logs.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 mb-6 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
              <span className="text-[12px] font-semibold text-gray-600">진행 상황</span>
              {status === "running" && <Loader2 size={12} className="animate-spin text-amber-500" />}
            </div>
            <div className="max-h-48 overflow-y-auto px-4 py-2 space-y-1">
              {logs.map((log, i) => (
                <div key={i} className="flex items-start gap-2 text-[12px]">
                  <span className="text-gray-400 flex-shrink-0 font-mono">{fmtTime(log.timestamp)}</span>
                  <span className="text-amber-600 flex-shrink-0 font-medium">{log.nodeName}</span>
                  <span className="text-gray-600">{log.message}</span>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </div>
        )}

        {/* ── 에러 ── */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 mb-6 flex items-start gap-2">
            <AlertCircle size={16} className="text-red-400 flex-shrink-0 mt-0.5" />
            <span className="text-[13px] text-red-700">{error}</span>
          </div>
        )}

        {/* ── 결과: 파일 ── */}
        {outputFiles.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 mb-6 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <span className="text-[12px] font-semibold text-gray-600">생성된 파일</span>
            </div>
            <div className="divide-y divide-gray-50">
              {outputFiles.map((o, i) => {
                const fileName = o.value.split(/[/\\]/).pop() || o.value;
                return (
                  <div key={i} className="px-4 py-3 flex items-center gap-3">
                    <FileText size={16} className="text-blue-500 flex-shrink-0" />
                    <span className="text-[13px] text-gray-700 truncate flex-1">{fileName}</span>
                    <button
                      onClick={() => openFile(o.value)}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-amber-50
                        text-[12px] text-amber-700 font-medium hover:bg-amber-100 transition-colors"
                    >
                      <FolderOpen size={13} /> 열기
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── 결과: 텍스트 ── */}
        {outputTexts.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
              <span className="text-[12px] font-semibold text-gray-600">출력 텍스트</span>
            </div>
            <div className="divide-y divide-gray-50">
              {outputTexts.map((o, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[11px] text-gray-400">{o.portName}</span>
                    <CopyBtn text={o.value} />
                  </div>
                  <pre className="text-[12px] text-gray-700 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto">
                    {o.value}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
