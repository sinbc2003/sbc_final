import { useState, useEffect, useCallback } from "react";
import {
  X, Search, FolderOpen, Clock, Copy, Trash2, Tag, Star,
  FileJson, ChevronRight, ChevronDown, AlertCircle, CheckCircle2,
  MoreHorizontal, Edit3, Download, Plus,
} from "lucide-react";
import { useStore } from "../store";
import { getCategoryColor } from "../constants";

/* ── 타입 ─────────────────────────────────────────── */
interface WorkflowMeta {
  id: string;
  name: string;
  description: string;
  tags: string[];
  node_count: number;
  edge_count: number;
  created_at: string;
  updated_at: string;
  thumbnail_nodes: string[];
}

interface HistoryRecord {
  id: string;
  workflow_id: string;
  workflow_name: string;
  started_at: string;
  finished_at: string;
  success: boolean;
  elapsed_seconds: number;
  errors: string[];
}

interface HistoryDetail extends HistoryRecord {
  node_timings?: { node_id: string; node_name: string; elapsed: number }[];
  outputs?: Record<string, Record<string, string>>;
}

type Tab = "workflows" | "history" | "presets";

/* ── 유틸 ─────────────────────────────────────────── */
function timeAgo(isoStr: string): string {
  if (!isoStr) return "";
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  const days = Math.floor(hrs / 24);
  return `${days}일 전`;
}

/* ── 노드 타입 미리보기 뱃지 ─────────────────────── */
function NodeBadges({ types }: { types: string[] }) {
  if (!types.length) return null;
  const catMap: Record<string, string> = {
    pdf_to_md: "변환", hwp_to_md: "변환", hwpx_to_md: "변환", xlsx_to_md: "변환",
    llm_generate: "LLM", llm_summarize: "LLM",
    md_to_hwpx: "출력", save_xlsx: "출력", hwpx_fill: "출력",
    table_extract: "전처리", data_merge: "전처리", column_mapping: "전처리",
  };
  const unique = [...new Set(types)];
  return (
    <div className="flex gap-1 flex-wrap mt-1.5">
      {unique.slice(0, 5).map((t) => {
        const cat = catMap[t] ?? "유틸";
        const color = getCategoryColor(cat);
        return (
          <span key={t} className="text-[9px] font-medium px-1.5 py-[1px] rounded"
            style={{ background: color + "15", color }}>
            {t.replace(/_/g, " ")}
          </span>
        );
      })}
      {unique.length > 5 && (
        <span className="text-[9px] text-gray-400">+{unique.length - 5}</span>
      )}
    </div>
  );
}

/* ── 워크플로우 카드 ─────────────────────────────── */
function WorkflowCard({
  wf, onOpen, onDuplicate, onDelete, onExport, onRename,
}: {
  wf: WorkflowMeta;
  onOpen: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onExport: () => void;
  onRename: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="group bg-white border border-gray-200 rounded-lg p-3 hover:border-amber-300
                    hover:shadow-sm transition-all cursor-pointer"
      onClick={onOpen}>
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] font-semibold text-gray-800 truncate">{wf.name}</h3>
          {wf.description && (
            <p className="text-[11px] text-gray-500 truncate mt-0.5">{wf.description}</p>
          )}
        </div>
        {/* 메뉴 */}
        <div className="relative">
          <button
            onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
            className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-gray-100
                       text-gray-400 hover:text-gray-600 transition-all">
            <MoreHorizontal size={14} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); setMenuOpen(false); }} />
              <div className="absolute right-0 top-7 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-36">
                <button onClick={(e) => { e.stopPropagation(); onRename(); setMenuOpen(false); }}
                  className="flex items-center gap-2 w-full px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-50">
                  <Edit3 size={12} /> 이름 변경
                </button>
                <button onClick={(e) => { e.stopPropagation(); onDuplicate(); setMenuOpen(false); }}
                  className="flex items-center gap-2 w-full px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-50">
                  <Copy size={12} /> 복제
                </button>
                <button onClick={(e) => { e.stopPropagation(); onExport(); setMenuOpen(false); }}
                  className="flex items-center gap-2 w-full px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-50">
                  <Download size={12} /> 내보내기
                </button>
                <div className="border-t border-gray-100 my-1" />
                <button onClick={(e) => { e.stopPropagation(); onDelete(); setMenuOpen(false); }}
                  className="flex items-center gap-2 w-full px-3 py-1.5 text-[12px] text-red-500 hover:bg-red-50">
                  <Trash2 size={12} /> 삭제
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <NodeBadges types={wf.thumbnail_nodes} />

      <div className="flex items-center gap-3 mt-2 text-[10px] text-gray-400">
        <span>노드 {wf.node_count} · 연결 {wf.edge_count}</span>
        <span>{timeAgo(wf.updated_at || wf.created_at)}</span>
      </div>

      {wf.tags.length > 0 && (
        <div className="flex gap-1 mt-1.5">
          {wf.tags.map((t) => (
            <span key={t} className="text-[9px] text-gray-400 bg-gray-100 px-1.5 py-[1px] rounded">
              #{t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── 히스토리 행 (클릭 시 상세 펼침) ─────────────── */
function HistoryRow({ rec }: { rec: HistoryRecord }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (!detail) {
      setLoading(true);
      try {
        const res = await fetch(`/api/history/${rec.id}`);
        const data = await res.json();
        setDetail(data);
      } catch {
        setDetail({ ...rec, node_timings: [], outputs: {} });
      }
      setLoading(false);
    }
  };

  const maxTiming = detail?.node_timings?.reduce((m, t) => Math.max(m, t.elapsed), 0.01) ?? 1;

  return (
    <div className="rounded transition-colors">
      {/* 헤더 행 */}
      <div className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer"
        onClick={handleClick}>
        {expanded
          ? <ChevronDown size={12} className="text-gray-400 flex-shrink-0" />
          : <ChevronRight size={12} className="text-gray-400 flex-shrink-0" />}
        {rec.success
          ? <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />
          : <AlertCircle size={14} className="text-red-500 flex-shrink-0" />}
        <div className="min-w-0 flex-1">
          <p className="text-[12px] text-gray-700 truncate">{rec.workflow_name}</p>
          <p className="text-[10px] text-gray-400">{timeAgo(rec.finished_at)} · {rec.elapsed_seconds.toFixed(1)}초</p>
        </div>
        {rec.errors.length > 0 && (
          <span className="text-[10px] text-red-400">오류 {rec.errors.length}건</span>
        )}
      </div>

      {/* 상세 영역 */}
      {expanded && (
        <div className="px-4 pb-3 ml-7 border-l-2 border-gray-100">
          {loading ? (
            <p className="text-[11px] text-gray-400 py-2">불러오는 중...</p>
          ) : detail ? (
            <>
              {/* 기본 정보 */}
              <div className="flex items-center gap-4 text-[10px] text-gray-500 mb-2 mt-1">
                <span>ID: {detail.id}</span>
                <span>시작: {new Date(detail.started_at).toLocaleString("ko-KR")}</span>
                <span>소요: {detail.elapsed_seconds.toFixed(1)}초</span>
              </div>

              {/* 노드별 타이밍 바 */}
              {detail.node_timings && detail.node_timings.length > 0 && (
                <div className="mb-2">
                  <p className="text-[10px] font-semibold text-gray-500 mb-1">노드별 실행 시간</p>
                  {detail.node_timings.map((t) => (
                    <div key={t.node_id} className="flex items-center gap-2 py-[2px]">
                      <span className="text-[10px] text-gray-600 w-[100px] truncate" title={t.node_name}>
                        {t.node_name}
                      </span>
                      <div className="flex-1 h-[10px] bg-gray-100 rounded overflow-hidden">
                        <div
                          className="h-full rounded transition-all"
                          style={{
                            width: `${Math.max((t.elapsed / maxTiming) * 100, 2)}%`,
                            background: t.elapsed > detail.elapsed_seconds * 0.5
                              ? "#e8a028" : "#6cc04a",
                          }}
                        />
                      </div>
                      <span className="text-[9px] text-gray-400 w-[40px] text-right">
                        {t.elapsed.toFixed(1)}초
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* 에러 목록 */}
              {detail.errors && detail.errors.length > 0 && (
                <div className="mb-2">
                  <p className="text-[10px] font-semibold text-red-500 mb-1">오류</p>
                  {detail.errors.map((err, i) => (
                    <p key={i} className="text-[10px] text-red-400 py-[1px] pl-2 border-l-2 border-red-200">
                      {err}
                    </p>
                  ))}
                </div>
              )}

              {/* 출력 미리보기 */}
              {detail.outputs && Object.keys(detail.outputs).length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-gray-500 mb-1">출력</p>
                  {Object.entries(detail.outputs).map(([nodeId, ports]) =>
                    Object.entries(ports).map(([portName, val]) => {
                      const str = typeof val === "string" ? val : JSON.stringify(val);
                      const preview = str.length > 150 ? str.slice(0, 150) + "..." : str;
                      return (
                        <div key={`${nodeId}-${portName}`} className="py-[2px]">
                          <span className="text-[10px] font-medium text-amber-600">
                            {nodeId}:{portName}
                          </span>
                          <p className="text-[10px] text-gray-500 pl-2 truncate" title={str}>
                            "{preview}" ({str.length}자)
                          </p>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

/* ── 메인 매니저 ─────────────────────────────────── */
export function WorkflowManager({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("workflows");
  const [search, setSearch] = useState("");
  const [workflows, setWorkflows] = useState<WorkflowMeta[]>([]);
  const [history, setHistory] = useState<HistoryRecord[]>([]);
  const [presets, setPresets] = useState<WorkflowMeta[]>([]);
  const [loading, setLoading] = useState(true);

  const loadWorkflowJSON = useStore((s) => s.loadWorkflowJSON);
  const nodeDefinitions = useStore((s) => s.nodeDefinitions);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [wfRes, histRes, preRes] = await Promise.all([
        fetch("/api/workflows"), fetch("/api/history"), fetch("/api/presets"),
      ]);
      setWorkflows(await wfRes.json());
      setHistory(await histRes.json());
      setPresets(await preRes.json());
    } catch { /* 서버 미실행 */ }
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleOpen = async (wfId: string) => {
    try {
      const res = await fetch(`/api/workflows/${wfId}`);
      const data = await res.json();
      loadWorkflowJSON(data);
      onClose();
    } catch { alert("불러오기 실패"); }
  };

  const handleDuplicate = async (wfId: string) => {
    await fetch(`/api/workflows/${wfId}/duplicate`, { method: "POST" });
    refresh();
  };

  const handleDelete = async (wfId: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    await fetch(`/api/workflows/${wfId}`, { method: "DELETE" });
    refresh();
  };

  const handleExport = async (wfId: string) => {
    const res = await fetch(`/api/workflows/${wfId}`);
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${data.name || wfId}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  const handleRename = async (wfId: string) => {
    const name = prompt("새 이름:");
    if (!name) return;
    await fetch(`/api/workflows/${wfId}/rename`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    refresh();
  };

  const handleImport = () => {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const text = await file.text();
      const data = JSON.parse(text);
      loadWorkflowJSON(data);
      onClose();
    };
    input.click();
  };

  const filtered = (tab === "workflows" ? workflows : presets).filter((w) =>
    !search || w.name.includes(search) || w.description?.includes(search) ||
    w.tags.some((t) => t.includes(search))
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-[680px] max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}>
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <FolderOpen size={18} className="text-amber-500" />
            <h2 className="text-[15px] font-bold text-gray-800">워크플로우 관리</h2>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400">
            <X size={18} />
          </button>
        </div>

        {/* 탭 + 검색 */}
        <div className="px-5 pt-3 pb-2 flex items-center gap-3">
          <div className="flex bg-gray-100 rounded p-0.5">
            {([["workflows", "워크플로우"], ["history", "실행 기록"], ["presets", "프리셋"]] as const).map(([key, label]) => (
              <button key={key} onClick={() => setTab(key)}
                className={`px-3 py-1 rounded text-[11px] font-semibold transition-all ${
                  tab === key ? "bg-white text-gray-800 shadow-sm" : "text-gray-500"}`}>
                {label}
              </button>
            ))}
          </div>
          {tab !== "history" && (
            <div className="relative flex-1">
              <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
              <input type="text" placeholder="검색..." value={search} onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-7 pr-2 py-1.5 text-[12px] rounded bg-gray-50 border border-gray-200
                  text-gray-700 placeholder-gray-400 focus:outline-none focus:border-amber-400
                  focus:ring-1 focus:ring-amber-200" />
            </div>
          )}
          {tab === "workflows" && (
            <button onClick={handleImport}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded text-[11px] font-semibold
                bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors">
              <Plus size={12} /> 가져오기
            </button>
          )}
        </div>

        {/* 본문 */}
        <div className="flex-1 overflow-y-auto px-5 pb-4">
          {loading ? (
            <p className="text-[12px] text-gray-400 text-center py-12">불러오는 중...</p>
          ) : tab === "history" ? (
            history.length === 0 ? (
              <div className="text-center py-12">
                <Clock size={28} className="text-gray-300 mx-auto mb-2" />
                <p className="text-[12px] text-gray-400">실행 기록이 없습니다</p>
              </div>
            ) : (
              <div className="space-y-0.5">
                {history.map((r) => <HistoryRow key={r.id} rec={r} />)}
              </div>
            )
          ) : filtered.length === 0 ? (
            <div className="text-center py-12">
              <FileJson size={28} className="text-gray-300 mx-auto mb-2" />
              <p className="text-[12px] text-gray-400">
                {search ? "검색 결과 없음" : tab === "presets" ? "프리셋이 없습니다" : "저장된 워크플로우가 없습니다"}
              </p>
              {!search && tab === "workflows" && (
                <p className="text-[11px] text-gray-400 mt-1">상단 저장 버튼으로 현재 워크플로우를 저장하세요</p>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {filtered.map((wf) => (
                <WorkflowCard key={wf.id} wf={wf}
                  onOpen={() => handleOpen(wf.id)}
                  onDuplicate={() => handleDuplicate(wf.id)}
                  onDelete={() => handleDelete(wf.id)}
                  onExport={() => handleExport(wf.id)}
                  onRename={() => handleRename(wf.id)} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
