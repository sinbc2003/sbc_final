import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Search, Clock, Copy, Trash2, Star, FileJson,
  ChevronRight, AlertCircle, CheckCircle2,
  MoreHorizontal, Edit3, Download, Plus, ArrowUpDown,
  Play, FolderOpen,
} from "lucide-react";
import { useStore } from "../store";
import { MiniFlowChart } from "./MiniFlowChart";

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
  thumbnail_data?: { nodes: { id: string; type: string; x: number; y: number }[]; edges: { from: string; to: string }[] };
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

type Tab = "workflows" | "history" | "presets";
type SortKey = "updated" | "name" | "nodes";

/* ── 시간 포맷 ────────────────────────────────────── */
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  const days = Math.floor(hrs / 24);
  return `${days}일 전`;
}

/* ── 메인 페이지 ──────────────────────────────────── */
export function WorkflowManagerPage() {
  const setMode = useStore((s) => s.setMode);
  const loadWorkflowJSON = useStore((s) => s.loadWorkflowJSON);
  const newWorkflow = useStore((s) => s.newWorkflow);

  const [tab, setTab] = useState<Tab>("workflows");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("updated");
  const [workflows, setWorkflows] = useState<WorkflowMeta[]>([]);
  const [history, setHistory] = useState<HistoryRecord[]>([]);
  const [presets, setPresets] = useState<WorkflowMeta[]>([]);
  const [loading, setLoading] = useState(true);

  // 데이터 로드
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [wfRes, histRes, preRes] = await Promise.all([
        fetch("/api/workflows"), fetch("/api/history"), fetch("/api/presets"),
      ]);
      if (wfRes.ok) setWorkflows(await wfRes.json());
      if (histRes.ok) setHistory(await histRes.json());
      if (preRes.ok) setPresets(await preRes.json());
    } catch { /* 서버 미연결 */ }
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // 워크플로우 열기
  const handleOpen = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/workflows/${id}`);
      if (res.ok) {
        const data = await res.json();
        loadWorkflowJSON(data);
        setMode("design");
      }
    } catch { alert("불러오기 실패"); }
  }, [loadWorkflowJSON, setMode]);

  // 삭제
  const handleDelete = useCallback(async (id: string, name: string) => {
    if (!confirm(`"${name}" 삭제?`)) return;
    await fetch(`/api/workflows/${id}`, { method: "DELETE" });
    refresh();
  }, [refresh]);

  // 복제
  const handleDuplicate = useCallback(async (id: string) => {
    await fetch(`/api/workflows/${id}/duplicate`, { method: "POST" });
    refresh();
  }, [refresh]);

  // 정렬 + 워크플로우 탭에 프리셋도 포함
  const sortedWorkflows = useMemo(() => {
    let list: (WorkflowMeta & { isPreset?: boolean })[];
    if (tab === "presets") {
      list = presets.map((p) => ({ ...p, isPreset: true }));
    } else if (tab === "workflows") {
      // 사용자 워크플로우 + 프리셋 합침 (프리셋은 하단에)
      list = [
        ...workflows.map((w) => ({ ...w, isPreset: false })),
        ...presets.map((p) => ({ ...p, isPreset: true })),
      ];
    } else {
      list = [];
    }
    const filtered = search.trim()
      ? list.filter((w) => w.name.includes(search) || w.description?.includes(search))
      : list;
    return [...filtered].sort((a, b) => {
      // 프리셋은 항상 아래로
      if (a.isPreset !== b.isPreset) return a.isPreset ? 1 : -1;
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "nodes") return b.node_count - a.node_count;
      return new Date(b.updated_at || "").getTime() - new Date(a.updated_at || "").getTime();
    });
  }, [tab, workflows, presets, search, sort]);

  return (
    <div className="flex-1 bg-gray-50 flex flex-col overflow-hidden">
      {/* 헤더 */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1 className="text-[18px] font-bold text-gray-800">워크플로우 관리</h1>
            <p className="text-[12px] text-gray-500">{workflows.length}개 워크플로우 · {history.length}개 실행 기록</p>
          </div>
          <button
            onClick={() => { newWorkflow(); setMode("design"); }}
            className="flex items-center gap-1.5 px-4 py-2 bg-amber-500 text-white text-[13px] font-semibold
              rounded-lg hover:bg-amber-600 transition-colors shadow-sm">
            <Plus size={15} /> 새 워크플로우
          </button>
        </div>

        {/* 탭 + 검색 + 정렬 */}
        <div className="flex items-center gap-3">
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            {(["workflows", "history", "presets"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors ${
                  tab === t ? "bg-white text-gray-800 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}>
                {t === "workflows" ? `워크플로우 (${workflows.length})` :
                  t === "history" ? `실행 기록 (${history.length})` :
                  `프리셋 (${presets.length})`}
              </button>
            ))}
          </div>

          {tab !== "history" && (
            <>
              <div className="relative flex-1 max-w-[280px]">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input type="text" placeholder="검색..." value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-[12px] rounded-lg border border-gray-200 bg-white
                    focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400/30" />
              </div>
              <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}
                className="text-[12px] px-2 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-600">
                <option value="updated">최신순</option>
                <option value="name">이름순</option>
                <option value="nodes">노드수순</option>
              </select>
            </>
          )}
        </div>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="text-center py-20 text-gray-400 text-[13px]">불러오는 중...</div>
        ) : tab === "history" ? (
          /* 히스토리 */
          <div className="space-y-2 max-w-[800px]">
            {history.length === 0 ? (
              <p className="text-center py-12 text-gray-400 text-[13px]">실행 기록 없음</p>
            ) : history.map((rec) => (
              <div key={rec.id} className="bg-white rounded-lg border border-gray-200 px-4 py-3 flex items-center gap-4">
                {rec.success
                  ? <CheckCircle2 size={16} className="text-emerald-500 flex-shrink-0" />
                  : <AlertCircle size={16} className="text-red-500 flex-shrink-0" />}
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-medium text-gray-800 truncate">{rec.workflow_name}</p>
                  <p className="text-[11px] text-gray-500">{rec.started_at?.slice(0, 16)} · {rec.elapsed_seconds}초</p>
                </div>
                {rec.errors.length > 0 && (
                  <span className="text-[10px] text-red-500 bg-red-50 px-2 py-0.5 rounded">{rec.errors.length}개 오류</span>
                )}
              </div>
            ))}
          </div>
        ) : (
          /* 워크플로우 / 프리셋 카드 그리드 */
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            {sortedWorkflows.length === 0 ? (
              <p className="col-span-full text-center py-12 text-gray-400 text-[13px]">
                {search ? "검색 결과 없음" : "워크플로우 없음"}
              </p>
            ) : sortedWorkflows.map((wf) => (
              <WorkflowCard key={wf.id} wf={wf}
                isPreset={(wf as any).isPreset}
                onOpen={() => handleOpen(wf.id)}
                onDelete={() => handleDelete(wf.id, wf.name)}
                onDuplicate={() => handleDuplicate(wf.id)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── 워크플로우 카드 ──────────────────────────────── */
function WorkflowCard({ wf, onOpen, onDelete, onDuplicate, isPreset }: {
  wf: WorkflowMeta; onOpen: () => void; onDelete: () => void; onDuplicate: () => void; isPreset?: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const td = wf.thumbnail_data;

  return (
    <div
      onClick={onOpen}
      className="bg-white rounded-xl border border-gray-200 hover:border-amber-300 hover:shadow-md
        transition-all cursor-pointer group overflow-hidden"
    >
      {/* 미니 플로우차트 */}
      <div className="bg-gray-50 border-b border-gray-100 flex items-center justify-center py-3 px-4">
        {td && td.nodes.length > 0 ? (
          <MiniFlowChart
            nodes={td.nodes.map((n) => ({ id: n.id, type: n.type, x: n.x, y: n.y }))}
            edges={td.edges.map((e) => ({ from: e.from, to: e.to }))}
            width={220} height={70}
          />
        ) : (
          <div className="flex gap-1">
            {wf.thumbnail_nodes.slice(0, 5).map((t, i) => (
              <div key={i} className="w-3 h-3 rounded-full bg-gray-300" title={t} />
            ))}
            {wf.thumbnail_nodes.length > 5 && (
              <span className="text-[9px] text-gray-400">+{wf.thumbnail_nodes.length - 5}</span>
            )}
          </div>
        )}
      </div>

      {/* 정보 */}
      <div className="px-4 py-3">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <h3 className="text-[13px] font-semibold text-gray-800 truncate">{wf.name}</h3>
            {wf.description && (
              <p className="text-[11px] text-gray-500 truncate mt-0.5">{wf.description}</p>
            )}
          </div>
          <div className="relative flex-shrink-0 ml-2">
            <button onClick={(e) => { e.stopPropagation(); setMenuOpen(!menuOpen); }}
              className="p-1 rounded hover:bg-gray-100 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
              <MoreHorizontal size={14} />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); setMenuOpen(false); }} />
                <div className="absolute right-0 top-6 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-32">
                  <button onClick={(e) => { e.stopPropagation(); onDuplicate(); setMenuOpen(false); }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-gray-600 hover:bg-gray-50">
                    <Copy size={11} /> 복제
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); onDelete(); setMenuOpen(false); }}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-red-600 hover:bg-red-50">
                    <Trash2 size={11} /> 삭제
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {/* 메타 */}
        <div className="flex items-center gap-2 mt-2 text-[10px] text-gray-400">
          {isPreset && (
            <span className="px-1.5 py-0.5 rounded bg-violet-50 text-violet-600 font-medium">예시</span>
          )}
          {wf.edge_count > wf.node_count - 1 && (
            <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-600 font-medium">분기</span>
          )}
          <span>노드 {wf.node_count}</span>
          <span>연결 {wf.edge_count}</span>
          <span className="flex-1" />
          <span>{wf.updated_at ? timeAgo(wf.updated_at) : ""}</span>
        </div>
      </div>
    </div>
  );
}
