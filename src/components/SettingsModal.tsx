import { useState, useEffect, useCallback } from "react";
import {
  X, Key, Brain, Database, Package, RefreshCw, Check,
  AlertCircle, Loader2, Eye, EyeOff, Download,
} from "lucide-react";

/* ── 타입 ────────────────────────────────────────── */

interface Settings {
  general: {
    language: string;
    theme: string;
    auto_save_interval: number;
    check_updates: boolean;
    update_channel: string;
    output_dir: string;
  };
  llm: {
    default_provider: string;
    local_model: string;
    local_context_size: number;
    default_temperature: number;
    default_max_tokens: number;
  };
  rag: {
    enabled: boolean;
    collection_name: string;
    embedding_model: string;
    chunk_size: number;
    chunk_overlap: number;
    sync_enabled: boolean;
    sync_url: string;
  };
  nodes: {
    marketplace_url: string;
    auto_update_nodes: boolean;
    installed_extra: string[];
  };
  api_keys: Record<string, string>;
}

type Tab = "api_keys" | "llm" | "rag" | "nodes" | "general";

const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: "api_keys", label: "API 키", icon: Key },
  { id: "llm", label: "LLM 모델", icon: Brain },
  { id: "rag", label: "RAG / 임베딩", icon: Database },
  { id: "nodes", label: "도구 업데이트", icon: Package },
  { id: "general", label: "일반", icon: RefreshCw },
];

/* ── 메인 ────────────────────────────────────────── */

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("api_keys");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [engineOnline, setEngineOnline] = useState(false);

  // 설정 로드
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/settings");
        if (res.ok) {
          setSettings(await res.json());
          setEngineOnline(true);
        } else {
          setError("엔진 응답 오류");
        }
      } catch {
        setError("엔진 연결 실패 — python -m engine.server 실행 필요");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // 섹션 저장
  const saveSection = useCallback(async (section: string, values: Record<string, any>) => {
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const res = await fetch(`/api/settings/${section}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (res.ok) {
        setSettings(await res.json());
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      } else {
        setError("저장 실패");
      }
    } catch {
      setError("저장 실패 — 엔진 연결 확인");
    } finally {
      setSaving(false);
    }
  }, []);

  // ESC 닫기
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-[720px] h-[560px] flex flex-col overflow-hidden border border-gray-200">
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <h2 className="text-[15px] font-bold text-gray-800">설정</h2>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
              engineOnline ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-500"
            }`}>
              {engineOnline ? "엔진 연결됨" : "오프라인"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {saved && <span className="text-[11px] text-emerald-600 flex items-center gap-1"><Check size={12} />저장됨</span>}
            {saving && <Loader2 size={13} className="animate-spin text-gray-400" />}
            <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* 본문 */}
        <div className="flex flex-1 overflow-hidden">
          {/* 사이드바 탭 */}
          <div className="w-[160px] bg-gray-50/80 border-r border-gray-100 py-2 flex-shrink-0">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`w-full flex items-center gap-2 px-4 py-2 text-[12px] transition-colors ${
                  tab === id
                    ? "bg-white text-gray-800 font-semibold border-r-2 border-amber-500"
                    : "text-gray-500 hover:text-gray-700 hover:bg-white/50"
                }`}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          {/* 콘텐츠 */}
          <div className="flex-1 overflow-y-auto p-5">
            {loading ? (
              <div className="flex items-center justify-center h-40 text-gray-400">
                <Loader2 size={20} className="animate-spin" />
              </div>
            ) : error && !settings ? (
              <div className="flex flex-col items-center justify-center h-40 gap-2 text-gray-400">
                <AlertCircle size={24} />
                <p className="text-[12px]">{error}</p>
              </div>
            ) : settings ? (
              <>
                {tab === "api_keys" && <ApiKeysTab settings={settings} onSave={saveSection} />}
                {tab === "llm" && <LlmTab settings={settings} onSave={saveSection} />}
                {tab === "rag" && <RagTab settings={settings} onSave={saveSection} />}
                {tab === "nodes" && <NodesTab settings={settings} onSave={saveSection} />}
                {tab === "general" && <GeneralTab settings={settings} onSave={saveSection} />}
              </>
            ) : null}
            {error && settings && (
              <p className="text-[11px] text-red-500 mt-3">{error}</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── API 키 탭 ───────────────────────────────────── */

function ApiKeysTab({ settings, onSave }: { settings: Settings; onSave: (s: string, v: any) => void }) {
  const [keys, setKeys] = useState<Record<string, string>>({
    claude_api_key: "",
    openai_api_key: "",
    gemini_api_key: "",
    mathpix_app_id: "",
    mathpix_app_key: "",
  });
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});

  const KEY_META: { id: string; label: string; placeholder: string; desc: string }[] = [
    { id: "claude_api_key", label: "Claude (Anthropic)", placeholder: "sk-ant-...", desc: "Claude API 키" },
    { id: "openai_api_key", label: "OpenAI", placeholder: "sk-...", desc: "GPT 모델 사용" },
    { id: "gemini_api_key", label: "Gemini (Google)", placeholder: "AI...", desc: "Gemini 모델 사용" },
    { id: "mathpix_app_id", label: "Mathpix App ID", placeholder: "your_app_id", desc: "수식 OCR (선택)" },
    { id: "mathpix_app_key", label: "Mathpix App Key", placeholder: "your_app_key", desc: "수식 OCR (선택)" },
  ];

  const hasValue = (id: string) => !!settings.api_keys[id];

  return (
    <div className="space-y-4">
      <SectionHeader title="API 키 관리" desc="외부 AI 서비스 사용을 위한 API 키. 키는 로컬에만 저장됩니다." />

      {KEY_META.map(({ id, label, placeholder, desc }) => (
        <div key={id} className="space-y-1">
          <div className="flex items-center justify-between">
            <label className="text-[12px] font-medium text-gray-700">{label}</label>
            {hasValue(id) && (
              <span className="text-[10px] text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">설정됨</span>
            )}
          </div>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type={showKey[id] ? "text" : "password"}
                placeholder={hasValue(id) ? settings.api_keys[id] : placeholder}
                value={keys[id]}
                onChange={(e) => setKeys({ ...keys, [id]: e.target.value })}
                className="w-full px-3 py-2 text-[12px] rounded-lg border border-gray-200 bg-white
                  focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400/30 pr-8"
              />
              <button
                onClick={() => setShowKey({ ...showKey, [id]: !showKey[id] })}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showKey[id] ? <EyeOff size={13} /> : <Eye size={13} />}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">{desc}</p>
        </div>
      ))}

      <button
        onClick={() => {
          const toSave: Record<string, string> = {};
          for (const [k, v] of Object.entries(keys)) {
            if (v.trim()) toSave[k] = v.trim();
          }
          if (Object.keys(toSave).length > 0) onSave("api_keys", toSave);
        }}
        className="px-4 py-2 bg-amber-500 text-white text-[12px] font-semibold rounded-lg
          hover:bg-amber-600 transition-colors disabled:opacity-50"
        disabled={!Object.values(keys).some((v) => v.trim())}
      >
        키 저장
      </button>
    </div>
  );
}

/* ── LLM 탭 ──────────────────────────────────────── */

function LlmTab({ settings, onSave }: { settings: Settings; onSave: (s: string, v: any) => void }) {
  const [llm, setLlm] = useState(settings.llm);

  return (
    <div className="space-y-4">
      <SectionHeader title="LLM 설정" desc="텍스트 생성에 사용할 LLM 프로바이더와 파라미터." />

      <Field label="기본 프로바이더">
        <select
          value={llm.default_provider}
          onChange={(e) => setLlm({ ...llm, default_provider: e.target.value })}
          className="input-field"
        >
          <option value="auto">자동 (API 키 순서대로)</option>
          <option value="claude">Claude</option>
          <option value="openai">OpenAI</option>
          <option value="gemini">Gemini</option>
          <option value="local">로컬 (llama.cpp)</option>
        </select>
      </Field>

      <Field label="기본 온도" desc="0 = 정확, 1 = 창의적">
        <input
          type="range" min="0" max="1" step="0.1"
          value={llm.default_temperature}
          onChange={(e) => setLlm({ ...llm, default_temperature: parseFloat(e.target.value) })}
          className="w-full accent-amber-500"
        />
        <span className="text-[11px] text-gray-500 ml-2 tabular-nums">{llm.default_temperature}</span>
      </Field>

      <Field label="기본 최대 토큰">
        <input
          type="number" min="256" max="32768" step="256"
          value={llm.default_max_tokens}
          onChange={(e) => setLlm({ ...llm, default_max_tokens: parseInt(e.target.value) || 2048 })}
          className="input-field w-32"
        />
      </Field>

      <div className="border-t border-gray-100 pt-3">
        <p className="text-[11px] text-gray-500 font-medium mb-2">로컬 모델 (llama.cpp)</p>
        <Field label="모델 파일 (GGUF)" desc="비워두면 메모리 기반 자동 선택">
          <input
            type="text"
            placeholder="models/base/gemma-2b-q4.gguf"
            value={llm.local_model}
            onChange={(e) => setLlm({ ...llm, local_model: e.target.value })}
            className="input-field flex-1"
          />
        </Field>
        <Field label="컨텍스트 크기" desc="0 = 자동">
          <input
            type="number" min="0" max="32768" step="512"
            value={llm.local_context_size}
            onChange={(e) => setLlm({ ...llm, local_context_size: parseInt(e.target.value) || 0 })}
            className="input-field w-32"
          />
        </Field>
      </div>

      <button onClick={() => onSave("llm", llm)}
        className="px-4 py-2 bg-amber-500 text-white text-[12px] font-semibold rounded-lg hover:bg-amber-600 transition-colors">
        저장
      </button>
    </div>
  );
}

/* ── RAG 탭 ──────────────────────────────────────── */

function RagTab({ settings, onSave }: { settings: Settings; onSave: (s: string, v: any) => void }) {
  const [rag, setRag] = useState(settings.rag);

  return (
    <div className="space-y-4">
      <SectionHeader title="RAG / 임베딩 데이터" desc="ChromaDB 기반 벡터 검색. 문서를 임베딩하여 LLM에 맥락을 제공합니다." />

      <Field label="RAG 활성화">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={rag.enabled}
            onChange={(e) => setRag({ ...rag, enabled: e.target.checked })}
            className="accent-amber-500" />
          <span className="text-[12px] text-gray-600">벡터 데이터베이스 사용</span>
        </label>
      </Field>

      {rag.enabled && (
        <>
          <Field label="컬렉션 이름" desc="ChromaDB 컬렉션 ID">
            <input type="text" value={rag.collection_name}
              onChange={(e) => setRag({ ...rag, collection_name: e.target.value })}
              className="input-field flex-1" />
          </Field>

          <Field label="임베딩 모델">
            <select value={rag.embedding_model}
              onChange={(e) => setRag({ ...rag, embedding_model: e.target.value })}
              className="input-field">
              <option value="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2">multilingual-MiniLM (경량, 한국어)</option>
              <option value="sentence-transformers/all-MiniLM-L6-v2">all-MiniLM-L6 (영어 최적)</option>
              <option value="jhgan/ko-sroberta-multitask">ko-sroberta (한국어 특화)</option>
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="청크 크기 (자)">
              <input type="number" min="100" max="2000" step="50"
                value={rag.chunk_size}
                onChange={(e) => setRag({ ...rag, chunk_size: parseInt(e.target.value) || 500 })}
                className="input-field w-full" />
            </Field>
            <Field label="겹침 (자)">
              <input type="number" min="0" max="500" step="10"
                value={rag.chunk_overlap}
                onChange={(e) => setRag({ ...rag, chunk_overlap: parseInt(e.target.value) || 50 })}
                className="input-field w-full" />
            </Field>
          </div>

          <div className="border-t border-gray-100 pt-3">
            <p className="text-[11px] text-gray-500 font-medium mb-2">공유 임베딩 동기화</p>
            <Field label="동기화 활성화">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={rag.sync_enabled}
                  onChange={(e) => setRag({ ...rag, sync_enabled: e.target.checked })}
                  className="accent-amber-500" />
                <span className="text-[12px] text-gray-600">다른 사용자의 임베딩 데이터 수신</span>
              </label>
            </Field>
            {rag.sync_enabled && (
              <Field label="동기화 서버 URL">
                <input type="text" placeholder="https://rag.teacherflow.com/sync"
                  value={rag.sync_url}
                  onChange={(e) => setRag({ ...rag, sync_url: e.target.value })}
                  className="input-field flex-1" />
              </Field>
            )}
          </div>
        </>
      )}

      <button onClick={() => onSave("rag", rag)}
        className="px-4 py-2 bg-amber-500 text-white text-[12px] font-semibold rounded-lg hover:bg-amber-600 transition-colors">
        저장
      </button>
    </div>
  );
}

/* ── 노드 업데이트 탭 ────────────────────────────── */

function NodesTab({ settings, onSave }: { settings: Settings; onSave: (s: string, v: any) => void }) {
  const [nodes, setNodes] = useState(settings.nodes);
  const [checkStatus, setCheckStatus] = useState<"idle" | "checking" | "done" | "error">("idle");
  const [updateInfo, setUpdateInfo] = useState<{available: number; nodes: string[]} | null>(null);

  const checkUpdates = async () => {
    setCheckStatus("checking");
    try {
      const res = await fetch("/api/nodes/check-updates");
      if (res.ok) {
        const data = await res.json();
        setUpdateInfo(data);
        setCheckStatus("done");
      } else {
        setCheckStatus("error");
      }
    } catch {
      setCheckStatus("error");
    }
  };

  return (
    <div className="space-y-4">
      <SectionHeader title="도구 & 업데이트" desc="노드(도구) 업데이트와 마켓플레이스 설정." />

      <Field label="자동 업데이트">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={nodes.auto_update_nodes}
            onChange={(e) => setNodes({ ...nodes, auto_update_nodes: e.target.checked })}
            className="accent-amber-500" />
          <span className="text-[12px] text-gray-600">앱 시작 시 새 도구 자동 확인</span>
        </label>
      </Field>

      <div className="flex items-center gap-2">
        <button onClick={checkUpdates} disabled={checkStatus === "checking"}
          className="flex items-center gap-1.5 px-3 py-2 text-[12px] font-medium rounded-lg
            border border-gray-200 hover:bg-gray-50 transition-colors disabled:opacity-50">
          {checkStatus === "checking"
            ? <><Loader2 size={13} className="animate-spin" /> 확인 중...</>
            : <><Download size={13} /> 업데이트 확인</>}
        </button>
        {checkStatus === "done" && updateInfo && (
          <span className="text-[11px] text-emerald-600">
            {updateInfo.available > 0
              ? `${updateInfo.available}개 업데이트 가능`
              : "최신 상태"}
          </span>
        )}
        {checkStatus === "error" && (
          <span className="text-[11px] text-red-500">확인 실패 (오프라인?)</span>
        )}
      </div>

      {updateInfo && updateInfo.available > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="text-[11px] font-medium text-amber-800 mb-1">새 도구:</p>
          {updateInfo.nodes.map((n) => (
            <p key={n} className="text-[11px] text-amber-700">· {n}</p>
          ))}
        </div>
      )}

      <Field label="마켓플레이스 URL">
        <input type="text" value={nodes.marketplace_url}
          onChange={(e) => setNodes({ ...nodes, marketplace_url: e.target.value })}
          className="input-field flex-1" />
      </Field>

      <button onClick={() => onSave("nodes", nodes)}
        className="px-4 py-2 bg-amber-500 text-white text-[12px] font-semibold rounded-lg hover:bg-amber-600 transition-colors">
        저장
      </button>
    </div>
  );
}

/* ── 일반 탭 ─────────────────────────────────────── */

function GeneralTab({ settings, onSave }: { settings: Settings; onSave: (s: string, v: any) => void }) {
  const [general, setGeneral] = useState(settings.general);

  return (
    <div className="space-y-4">
      <SectionHeader title="일반 설정" desc="앱 기본 동작 설정." />

      <Field label="출력 파일 저장 위치" desc="빈값 = 바탕화면에 자동 저장">
        <input type="text"
          placeholder="C:\Users\내이름\Desktop"
          value={general.output_dir ?? ""}
          onChange={(e) => setGeneral({ ...general, output_dir: e.target.value })}
          className="input-field flex-1" />
      </Field>

      <Field label="자동저장 간격 (초)">
        <input type="number" min="10" max="300" step="5"
          value={general.auto_save_interval}
          onChange={(e) => setGeneral({ ...general, auto_save_interval: parseInt(e.target.value) || 30 })}
          className="input-field w-32" />
      </Field>

      <Field label="업데이트 채널">
        <select value={general.update_channel}
          onChange={(e) => setGeneral({ ...general, update_channel: e.target.value })}
          className="input-field">
          <option value="stable">안정 (Stable)</option>
          <option value="beta">베타 (Beta)</option>
        </select>
      </Field>

      <Field label="앱 업데이트 자동 확인">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={general.check_updates}
            onChange={(e) => setGeneral({ ...general, check_updates: e.target.checked })}
            className="accent-amber-500" />
          <span className="text-[12px] text-gray-600">시작 시 새 버전 확인</span>
        </label>
      </Field>

      <button onClick={() => onSave("general", general)}
        className="px-4 py-2 bg-amber-500 text-white text-[12px] font-semibold rounded-lg hover:bg-amber-600 transition-colors">
        저장
      </button>
    </div>
  );
}

/* ── 공통 컴포넌트 ───────────────────────────────── */

function SectionHeader({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-[14px] font-bold text-gray-800">{title}</h3>
      <p className="text-[11px] text-gray-500 mt-0.5">{desc}</p>
    </div>
  );
}

function Field({ label, desc, children }: { label: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-[12px] font-medium text-gray-700">{label}</label>
      <div className="flex items-center gap-2">{children}</div>
      {desc && <p className="text-[10px] text-gray-400">{desc}</p>}
    </div>
  );
}
