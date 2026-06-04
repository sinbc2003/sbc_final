import { useState, useCallback, useRef, useEffect } from "react";
import {
  ArrowLeft, Upload, Play, Loader2, CheckCircle2, AlertCircle,
  FileText, FolderOpen, X, File, ChevronDown, Eye,
} from "lucide-react";

interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  available?: boolean;
}

type RunStatus = "idle" | "running" | "done" | "error";
type TemplateStatus = "idle" | "opening" | "open" | "error";

interface UploadedFile {
  file: globalThis.File;
  name: string;
}

function isFilePath(val: string): boolean {
  return /^[A-Za-z]:[/\\]/.test(val) || /\.(pdf|hwpx?|docx?|xlsx?|csv|txt)$/i.test(val);
}

export function FormAssist({ onBack }: { onBack: () => void }) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [instruction, setInstruction] = useState("");
  const [outputIdx, setOutputIdx] = useState(-1); // -1 = 자동
  const [pageRange, setPageRange] = useState("");
  const [selectedModel, setSelectedModel] = useState("auto");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [resultText, setResultText] = useState("");
  const [resultFile, setResultFile] = useState("");
  const [error, setError] = useState("");
  const [templateStatus, setTemplateStatus] = useState<TemplateStatus>("idle");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 모델 목록 로드
  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: ModelInfo[]) => {
        // local 제외, API 모델만
        setModels(data.filter((m) => m.provider !== "local"));
      })
      .catch(() => {});
  }, []);

  // 파일 추가
  const addFiles = useCallback((newFiles: FileList | globalThis.File[]) => {
    const arr = Array.from(newFiles).map((f) => ({ file: f, name: f.name }));
    setFiles((prev) => [...prev, ...arr]);
  }, []);

  // 드래그&드롭
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  }, [addFiles]);

  // 파일 제거
  const removeFile = useCallback((idx: number) => {
    setFiles((prev) => {
      const next = prev.filter((_, i) => i !== idx);
      if (outputIdx === idx) setOutputIdx(-1);
      else if (outputIdx > idx) setOutputIdx(outputIdx - 1);
      return next;
    });
  }, [outputIdx]);

  // 양식 파일 자동 감지
  const formExts = [".xlsx", ".xls", ".hwpx", ".hwp"];
  const hwpExts = [".hwp", ".hwpx"];
  const formFiles = files.map((f, i) => ({ ...f, idx: i })).filter((f) =>
    formExts.some((ext) => f.name.toLowerCase().endsWith(ext))
  );

  // 양식 드롭다운 선택 → HWP면 즉시 한/글에서 열기
  const handleOutputSelect = useCallback(async (idx: number) => {
    setOutputIdx(idx);
    setTemplateStatus("idle");

    if (idx < 0) return;
    const f = files[idx];
    if (!f || !hwpExts.some((ext) => f.name.toLowerCase().endsWith(ext))) return;

    setTemplateStatus("opening");
    try {
      const fd = new FormData();
      fd.append("file", f.file, f.name);
      const res = await fetch("/api/form-open-template", {
        method: "POST",
        body: fd,
      });
      if (res.ok) {
        setTemplateStatus("open");
      } else {
        setTemplateStatus("error");
      }
    } catch {
      setTemplateStatus("error");
    }
  }, [files]);

  // 실행
  const run = async () => {
    if (files.length === 0 || status === "running") return;
    setStatus("running");
    setLogs([]);
    setResultText("");
    setResultFile("");
    setError("");

    console.log("[FormAssist] 실행 시작, 파일:", files.map(f => f.name));

    const formData = new FormData();
    for (const f of files) formData.append("files", f.file, f.name);
    formData.append("instruction", instruction);
    formData.append("output_idx", String(outputIdx));
    formData.append("page_range", pageRange);
    // "auto" 또는 "provider/model" 형식 분리
    if (selectedModel === "auto") {
      formData.append("provider", "auto");
      formData.append("model", "");
    } else {
      const slashIdx = selectedModel.indexOf("/");
      formData.append("provider", slashIdx > 0 ? selectedModel.slice(0, slashIdx) : "auto");
      formData.append("model", selectedModel);
    }

    try {
      console.log("[FormAssist] fetch 시작");
      const res = await fetch("/api/form-assist", {
        method: "POST",
        body: formData,
      });
      console.log("[FormAssist] fetch 응답:", res.status);
      const data = await res.json();
      console.log("[FormAssist] 결과:", data.logs?.length, "logs, file:", !!data.file);

      if (data.logs) setLogs(data.logs);
      if (data.text) setResultText(data.text);
      if (data.file) {
        setResultFile(data.file);
        // 서버에서 자동 열기하지만, 실패 대비 프론트에서도 시도
      }
      setStatus(data.file || data.text ? "done" : "error");
      if (!data.file && !data.text) setError("결과가 생성되지 않았습니다.");
    } catch (e: any) {
      console.error("[FormAssist] 에러:", e);
      setStatus("error");
      setError(e?.message || "서버 연결 실패");
    }
  };

  // 파일 열기
  const openFile = useCallback((path: string) => {
    fetch("/api/files/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).catch(() => {});
  }, []);

  return (
    <div className="flex-1 bg-tf-bg overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* 헤더 */}
        <div className="flex items-center gap-3 mb-8">
          <button onClick={onBack}
            className="p-2 rounded-lg hover:bg-white hover:shadow-sm text-gray-500 hover:text-gray-700 transition-all">
            <ArrowLeft size={18} />
          </button>
          <div>
            <h2 className="text-lg font-bold text-gray-800">공문 양식 자동 채우기</h2>
            <p className="text-[12px] text-gray-500 mt-0.5">
              공문·참고자료·양식을 한번에 넣으면 AI가 알아서 채웁니다.
            </p>
          </div>
        </div>

        {/* 파일 업로드 */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-4">
          <label className="block text-[13px] font-semibold text-gray-700 mb-3">
            파일 (공문, 참고자료, 양식 등 한번에)
          </label>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors
              ${files.length > 0 ? "border-gray-200 bg-gray-50/30" : "border-gray-200 hover:border-amber-300 bg-gray-50/50"}`}
          >
            {files.length > 0 ? (
              <div className="space-y-2">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 bg-white rounded-lg px-3 py-2 border border-gray-100">
                    <File size={14} className={formExts.some((e) => f.name.toLowerCase().endsWith(e)) ? "text-amber-500" : "text-blue-500"} />
                    <span className="text-[13px] text-gray-700 flex-1 truncate">{f.name}</span>
                    {formExts.some((e) => f.name.toLowerCase().endsWith(e)) && (
                      <span className="text-[10px] bg-amber-50 text-amber-600 px-1.5 py-0.5 rounded font-medium">양식</span>
                    )}
                    <button onClick={() => removeFile(i)} className="p-0.5 hover:bg-gray-100 rounded text-gray-400">
                      <X size={14} />
                    </button>
                  </div>
                ))}
                <label className="inline-block text-[12px] text-amber-600 cursor-pointer hover:underline mt-1">
                  + 파일 더 추가
                  <input ref={fileInputRef} type="file" multiple className="hidden"
                    onChange={(e) => { if (e.target.files) addFiles(e.target.files); }} />
                </label>
              </div>
            ) : (
              <>
                <Upload size={28} className="text-gray-300 mx-auto mb-2" />
                <p className="text-[13px] text-gray-500 mb-1">파일을 여기에 드래그하거나</p>
                <label className="inline-block text-[13px] text-amber-600 font-medium cursor-pointer hover:underline">
                  파일 선택
                  <input ref={fileInputRef} type="file" multiple className="hidden"
                    onChange={(e) => { if (e.target.files) addFiles(e.target.files); }} />
                </label>
                <p className="text-[11px] text-gray-400 mt-2">PDF, HWP, HWPX, DOCX, XLSX, ODT, TXT 등</p>
              </>
            )}
          </div>
        </div>

        {/* 지시사항 */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-4">
          <label className="block text-[13px] font-semibold text-gray-700 mb-2">
            지시사항 <span className="font-normal text-gray-400">(선택)</span>
          </label>
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={3}
            placeholder="예: 양식.xlsx의 2~3페이지만 작성해줘 / 우리 학교 정보: 경기과학고, 신병철 교사"
            className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-[13px] text-gray-700
              focus:outline-none focus:ring-2 focus:ring-amber-200 focus:border-amber-300
              resize-y placeholder:text-gray-400"
          />
        </div>

        {/* 출력 양식 선택 */}
        {formFiles.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
            <label className="block text-[13px] font-semibold text-gray-700 mb-2">
              출력 양식 <span className="font-normal text-gray-400">(채워서 반환할 파일)</span>
            </label>
            <div className="flex gap-3 items-center">
              <div className="relative flex-1">
                <select
                  value={outputIdx}
                  onChange={(e) => handleOutputSelect(Number(e.target.value))}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-[13px] text-gray-700
                    focus:outline-none focus:ring-2 focus:ring-amber-200 appearance-none bg-white pr-8"
                >
                  <option value={-1}>자동 감지</option>
                  {formFiles.map((f) => (
                    <option key={f.idx} value={f.idx}>{f.name}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="absolute right-2.5 top-2.5 text-gray-400 pointer-events-none" />
              </div>
              <input
                value={pageRange}
                onChange={(e) => setPageRange(e.target.value)}
                placeholder="페이지/시트 (전체)"
                className="w-36 border border-gray-200 rounded-lg px-3 py-2 text-[13px] text-gray-700
                  focus:outline-none focus:ring-2 focus:ring-amber-200 placeholder:text-gray-400"
              />
            </div>
            {/* HWP 열기 상태 표시 */}
            {templateStatus === "opening" && (
              <div className="flex items-center gap-2 mt-2.5 text-[12px] text-amber-600">
                <Loader2 size={13} className="animate-spin" /> 한/글에서 양식 여는 중...
              </div>
            )}
            {templateStatus === "open" && (
              <div className="flex items-center gap-2 mt-2.5 text-[12px] text-emerald-600">
                <Eye size={13} /> 한/글에서 양식이 열렸습니다 — 실행하면 실시간으로 채워집니다
              </div>
            )}
            {templateStatus === "error" && (
              <div className="flex items-center gap-2 mt-2.5 text-[12px] text-red-500">
                <AlertCircle size={13} /> 한/글 열기 실패 — 한/글이 실행 중인지 확인하세요
              </div>
            )}
          </div>
        )}

        {/* 모델 선택 */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <label className="block text-[13px] font-semibold text-gray-700 mb-2">
            AI 모델
          </label>
          <div className="relative">
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-[13px] text-gray-700
                focus:outline-none focus:ring-2 focus:ring-amber-200 appearance-none bg-white pr-8"
            >
              <option value="auto">자동 (사용 가능한 모델)</option>
              {(["openai", "claude", "gemini"] as const).map((prov) => {
                const group = models.filter((m) => m.provider === prov);
                if (group.length === 0) return null;
                const label = prov === "openai" ? "OpenAI" : prov === "claude" ? "Anthropic" : "Google";
                const avail = group[0]?.available !== false;
                return (
                  <optgroup key={prov} label={`${label}${avail ? "" : " (키 없음)"}`}>
                    {group.map((m) => (
                      <option key={m.id} value={m.id} disabled={m.available === false}>
                        {m.name}
                      </option>
                    ))}
                  </optgroup>
                );
              })}
            </select>
            <ChevronDown size={14} className="absolute right-2.5 top-2.5 text-gray-400 pointer-events-none" />
          </div>
        </div>

        {/* 실행 */}
        <div className="flex justify-center mb-8">
          <button onClick={run} disabled={files.length === 0 || status === "running"}
            className={`flex items-center gap-2 px-8 py-3 rounded-xl text-[14px] font-semibold transition-all shadow-sm
              ${status === "running" ? "bg-amber-50 text-amber-600 cursor-wait"
                : status === "done" ? "bg-emerald-500 text-white hover:bg-emerald-600 active:scale-[0.98]"
                : files.length > 0 ? "bg-amber-500 text-white hover:bg-amber-600 active:scale-[0.98]"
                : "bg-gray-100 text-gray-400 cursor-not-allowed"}`}
          >
            {status === "running" ? <><Loader2 size={16} className="animate-spin" /> AI가 채우는 중...</>
              : status === "done" ? <><CheckCircle2 size={16} /> 다시 실행</>
              : templateStatus === "open" ? <><Play size={16} /> 실행 (한/글에서 실시간 채우기)</>
              : <><Play size={16} /> 실행</>}
          </button>
        </div>

        {/* 로그 */}
        {logs.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 mb-4 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <span className="text-[12px] font-semibold text-gray-600">진행 상황</span>
            </div>
            <div className="max-h-40 overflow-y-auto px-4 py-2 space-y-0.5">
              {logs.map((l, i) => (
                <div key={i} className="text-[12px] text-gray-600">{l}</div>
              ))}
            </div>
          </div>
        )}

        {/* 에러 */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 mb-4 flex items-start gap-2">
            <AlertCircle size={16} className="text-red-400 flex-shrink-0 mt-0.5" />
            <span className="text-[13px] text-red-700">{error}</span>
          </div>
        )}

        {/* 결과: 파일 */}
        {resultFile && (
          <div className="bg-emerald-50 rounded-xl border-2 border-emerald-300 mb-4 overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-3">
              <CheckCircle2 size={20} className="text-emerald-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-semibold text-emerald-800">
                  {templateStatus === "open" ? "한/글에서 실시간 채우기 완료!" : "완성 파일이 생성되었습니다"}
                </div>
                <div className="text-[12px] text-emerald-600 truncate mt-0.5">
                  {resultFile.split(/[/\\]/).pop()}
                </div>
              </div>
              <button onClick={() => openFile(resultFile)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500
                  text-[13px] text-white font-semibold hover:bg-emerald-600 transition-colors shadow-sm flex-shrink-0">
                <FolderOpen size={14} /> 파일 열기
              </button>
            </div>
            <div className="px-4 pb-2.5 text-[11px] text-emerald-500">
              한/글 창을 확인하세요 — 완성 파일이 저장되었습니다
            </div>
          </div>
        )}

        {/* 결과: 텍스트 */}
        {resultText && !resultFile && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <span className="text-[12px] font-semibold text-gray-600">AI 응답</span>
            </div>
            <pre className="px-4 py-3 text-[12px] text-gray-700 whitespace-pre-wrap max-h-64 overflow-y-auto">
              {resultText}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
