import { useMemo, useRef, useState, useCallback, useEffect } from "react";
import { Settings2, Info, X, ChevronRight, Upload, FileText, Loader2 } from "lucide-react";
import { useStore } from "../store";
import { getCategoryColor, getCategoryBg } from "../constants";
import type { FlowNodeData, ParamDef } from "../types";

/* ── 파일 선택 필드 ──────────────────────────────── */

function FileField({ value, onChange, accept }: {
  value: string;
  onChange: (v: string) => void;
  accept?: string[];
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState("");

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setFileName(file.name);

    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/files/upload", { method: "POST", body: form });
      if (res.ok) {
        const data = await res.json();
        onChange(data.path);
        setFileName(data.name);
      }
    } catch {
      setFileName("업로드 실패");
    } finally {
      setUploading(false);
    }
  }, [onChange]);

  const acceptStr = accept?.length ? accept.join(",") : undefined;
  const displayName = fileName || (value ? value.split(/[/\\]/).pop() : "");

  return (
    <div className="space-y-1.5">
      <div className="flex gap-1.5">
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium rounded-lg
            border border-dashed border-gray-300 bg-gray-50 hover:bg-white hover:border-amber-400
            transition-all flex-1 justify-center disabled:opacity-50"
        >
          {uploading
            ? <><Loader2 size={13} className="animate-spin" /> 업로드 중...</>
            : <><Upload size={13} /> 파일 선택</>}
        </button>
        <input ref={inputRef} type="file" accept={acceptStr} onChange={handleFileSelect} className="hidden" />
      </div>
      {displayName && (
        <div className="flex items-center gap-1.5 px-2 py-1.5 bg-amber-50 rounded-lg border border-amber-200">
          <FileText size={12} className="text-amber-600 flex-shrink-0" />
          <span className="text-[11px] text-amber-800 truncate flex-1" title={value}>{displayName}</span>
          <button onClick={() => { onChange(""); setFileName(""); }}
            className="text-amber-400 hover:text-amber-600 flex-shrink-0">
            <X size={11} />
          </button>
        </div>
      )}
      {value && !fileName && (
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
          className="w-full text-[10px] px-2 py-1 rounded bg-gray-50 border border-gray-200 text-gray-500
            focus:outline-none focus:border-tf-accent" placeholder="또는 경로 직접 입력" />
      )}
    </div>
  );
}

/* ── LLM 모델 선택기 ─────────────────────────────── */

interface ModelInfo { id: string; name: string; provider: string; size_mb?: string }

function ModelSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (loaded) return;
    fetch("/api/models").then(r => r.ok ? r.json() : []).then((data: ModelInfo[]) => {
      setModels(data);
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, [loaded]);

  const base = "w-full text-[12px] rounded bg-gray-50 border border-gray-200 text-gray-700 " +
    "focus:outline-none focus:border-tf-accent focus:ring-1 focus:ring-tf-accent/30 transition-all";

  // provider 값에서 현재 선택 판별
  const currentProvider = value || "auto";

  // 프로바이더별 그룹
  const localModels = models.filter(m => m.provider === "local");
  const apiModels = models.filter(m => m.provider !== "local");

  return (
    <div className="space-y-1.5">
      <select value={currentProvider} onChange={(e) => onChange(e.target.value)} className={`${base} px-2 py-1.5`}>
        <option value="auto">자동 선택</option>
        {localModels.length > 0 && (
          <optgroup label="로컬 모델">
            {localModels.map(m => (
              <option key={m.id} value={m.id}>
                {m.name} {m.size_mb ? `(${m.size_mb}MB)` : ""}
              </option>
            ))}
          </optgroup>
        )}
        {apiModels.length > 0 && (
          <optgroup label="API 모델">
            {apiModels.map(m => (
              <option key={m.id} value={m.id}>{m.name} ({m.provider})</option>
            ))}
          </optgroup>
        )}
        <optgroup label="프로바이더 직접 지정">
          <option value="local">로컬 (자동 모델)</option>
          <option value="claude">Claude</option>
          <option value="openai">OpenAI</option>
          <option value="gemini">Gemini</option>
        </optgroup>
      </select>
      {!loaded && <p className="text-[10px] text-gray-400">모델 목록 로딩...</p>}
      {loaded && models.length === 0 && (
        <p className="text-[10px] text-amber-500">사용 가능한 모델 없음 — 설정에서 API 키를 등록하거나 로컬 모델을 설치하세요</p>
      )}
    </div>
  );
}

/* ── 파라미터 필드 ────────────────────────────────── */

function ParamField({ def, value, onChange, isFileNode, fileAccept, isLlmNode }: {
  def: ParamDef; value: any; onChange: (v: any) => void;
  isFileNode?: boolean; fileAccept?: string[]; isLlmNode?: boolean;
}) {
  const base =
    "w-full text-[12px] rounded bg-gray-50 border border-gray-200 text-gray-700 " +
    "focus:outline-none focus:border-tf-accent focus:ring-1 focus:ring-tf-accent/30 transition-all";

  // file_input 노드의 path 파라미터 → 파일 피커 표시
  if (isFileNode && def.id === "path") {
    return <FileField value={value ?? ""} onChange={onChange} accept={fileAccept} />;
  }

  // LLM 노드의 provider 파라미터 → 모델 선택기
  if (isLlmNode && def.id === "provider") {
    return <ModelSelector value={value ?? "auto"} onChange={onChange} />;
  }

  if (def.type === "select" && def.options) {
    return (
      <select value={value ?? def.default ?? ""} onChange={(e) => onChange(e.target.value)} className={`${base} px-2 py-1.5`}>
        {def.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  if (def.type === "boolean") {
    return (
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={Boolean(value ?? def.default)}
          onChange={(e) => onChange(e.target.checked)}
          className="rounded border-gray-300 text-tf-accent focus:ring-tf-accent/30" />
        <span className="text-[11px] text-gray-500">{def.description}</span>
      </label>
    );
  }
  if (def.type === "text") {
    return (
      <textarea value={value ?? def.default ?? ""} onChange={(e) => onChange(e.target.value)}
        rows={3} className={`${base} px-2 py-1.5 resize-y font-mono text-[11px]`} placeholder={def.description} />
    );
  }
  if (def.type === "integer" || def.type === "float") {
    return (
      <input type="number" value={value ?? def.default ?? ""}
        onChange={(e) => onChange(def.type === "integer" ? parseInt(e.target.value) : parseFloat(e.target.value))}
        step={def.type === "float" ? 0.1 : 1} className={`${base} px-2 py-1.5`} />
    );
  }
  return <input type="text" value={value ?? def.default ?? ""} onChange={(e) => onChange(e.target.value)}
    className={`${base} px-2 py-1.5`} placeholder={def.description} />;
}

export function PropertiesPanel() {
  const selectedNodeId = useStore((s) => s.selectedNodeId);
  const nodes = useStore((s) => s.nodes);
  const updateNodeParams = useStore((s) => s.updateNodeParams);
  const selectNode = useStore((s) => s.selectNode);
  const propertiesOpen = useStore((s) => s.propertiesOpen);

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId),
    [nodes, selectedNodeId]
  );

  const selectedCount = useMemo(
    () => nodes.filter((n) => n.selected).length,
    [nodes]
  );

  const deleteSelected = useStore((s) => s.deleteSelected);

  if (!propertiesOpen) return null;

  // 다중 선택 시 요약 표시
  if (selectedCount > 1) {
    const selectedNodes = nodes.filter((n) => n.selected);
    const categories = new Map<string, number>();
    for (const n of selectedNodes) {
      const cat = (n.data as FlowNodeData).category;
      categories.set(cat, (categories.get(cat) || 0) + 1);
    }
    return (
      <div className="w-[260px] flex-shrink-0 bg-white border-l border-tf-border flex flex-col">
        <div className="px-3 pt-3 pb-2">
          <h2 className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">다중 선택</h2>
        </div>
        <div className="px-3 py-4">
          <p className="text-[13px] font-semibold text-gray-800 mb-3">{selectedCount}개 노드 선택됨</p>
          <div className="space-y-1.5 mb-4">
            {Array.from(categories.entries()).map(([cat, count]) => (
              <div key={cat} className="flex items-center gap-2 text-[12px]">
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: getCategoryColor(cat) }} />
                <span className="text-gray-600">{cat}</span>
                <span className="text-gray-400 ml-auto">{count}</span>
              </div>
            ))}
          </div>
          <button onClick={deleteSelected}
            className="w-full px-3 py-2 text-[12px] font-medium text-red-600 bg-red-50 rounded-lg
              hover:bg-red-100 transition-colors">
            선택된 {selectedCount}개 삭제
          </button>
          <p className="text-[10px] text-gray-400 mt-2 text-center">Delete 키로도 삭제 가능</p>
        </div>
      </div>
    );
  }

  if (!selectedNode) {
    return (
      <div className="w-[260px] flex-shrink-0 bg-white border-l border-tf-border flex flex-col">
        <div className="px-3 pt-3 pb-2">
          <h2 className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">속성</h2>
        </div>
        <div className="flex-1 flex items-center justify-center px-6">
          <div className="text-center">
            <ChevronRight size={24} className="text-gray-300 mx-auto mb-2" />
            <p className="text-[12px] text-gray-400">노드를 선택하세요</p>
          </div>
        </div>
      </div>
    );
  }

  const data = selectedNode.data as FlowNodeData;
  const catColor = getCategoryColor(data.category);
  const catBg = getCategoryBg(data.category);

  return (
    <div className="w-[260px] flex-shrink-0 bg-white border-l border-tf-border flex flex-col">
      {/* 헤더 */}
      <div className="px-3 pt-3 pb-2 border-b border-gray-100">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">속성</h2>
          <button onClick={() => selectNode(null)}
            className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors">
            <X size={14} />
          </button>
        </div>
        <div className="flex items-center gap-2" style={{ background: catBg, padding: "6px 8px", borderRadius: 6 }}>
          <div className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0"
            style={{ background: catColor, color: "#fff" }}>
            <Settings2 size={11} />
          </div>
          <div className="min-w-0">
            <p className="text-[12px] font-semibold text-gray-800 truncate">{data.label}</p>
            <p className="text-[10px] text-gray-400">{data.definitionId}</p>
          </div>
        </div>
      </div>

      {/* 설명 */}
      <div className="px-3 py-2 border-b border-gray-100">
        <div className="flex items-start gap-1.5">
          <Info size={11} className="text-gray-400 mt-0.5 flex-shrink-0" />
          <p className="text-[11px] text-gray-500 leading-relaxed">{data.description}</p>
        </div>
      </div>

      {/* 파일 입력 (입력 포트가 file 타입이고 연결이 없는 경우) */}
      {data.inputs.some((p) => p.type === "file") && (
        <div className="px-3 py-2.5 border-b border-gray-100">
          <p className="text-[11px] font-medium text-gray-500 mb-1.5">파일 입력</p>
          {data.inputs.filter((p) => p.type === "file").map((port) => (
            <div key={port.name} className="mb-2">
              <label className="block text-[10px] text-gray-400 mb-1">{port.name}</label>
              <FileField
                value={data.paramValues[`__file_${port.name}`] ?? ""}
                onChange={(v) => updateNodeParams(selectedNode.id, { [`__file_${port.name}`]: v })}
                accept={port.accept}
              />
            </div>
          ))}
          <p className="text-[10px] text-gray-400 mt-1">또는 파일 입력 노드를 연결하세요</p>
        </div>
      )}

      {/* 파라미터 */}
      <div className="flex-1 overflow-y-auto px-3 py-2.5">
        {data.params.length > 0 ? (
          <div className="space-y-3">
            {data.params.map((p) => {
              const isFileNode = data.definitionId === "file_input";
              const fileAccept = isFileNode ? data.outputs.flatMap((o) => o.accept ?? []) : undefined;
              const isLlmNode = data.category === "LLM";
              return (
                <div key={p.id}>
                  <label className="block text-[11px] font-medium text-gray-500 mb-1">{p.label}</label>
                  <ParamField def={p} value={data.paramValues[p.id]}
                    onChange={(v) => updateNodeParams(selectedNode.id, { [p.id]: v })}
                    isFileNode={isFileNode} fileAccept={fileAccept} isLlmNode={isLlmNode} />
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-[11px] text-gray-400 text-center py-4">파라미터 없음</p>
        )}
      </div>
    </div>
  );
}
