import { useState, useMemo } from "react";
import {
  Search, ChevronDown, ChevronRight, Box,
  ArrowRightLeft, Sparkles, Settings, MonitorDown, Wrench,
} from "lucide-react";
import { useStore } from "../store";
import { CATEGORY_META, getCategoryColor } from "../constants";
import { ICON_MAP } from "../iconMap";
import type { NodeDefinition } from "../types";

const CAT_ICON: Record<string, any> = {
  변환: ArrowRightLeft, 전처리: Settings, LLM: Sparkles,
  출력: MonitorDown, 유틸: Wrench,
};

/* ── 도구 타일 ─────────────────────────────────────── */
function ToolTile({ def }: { def: NodeDefinition }) {
  const color = getCategoryColor(def.category);
  const Icon = ICON_MAP[def.icon] ?? Box;

  const onDragStart = (e: React.DragEvent) => {
    e.dataTransfer.setData("application/teacherflow-node", def.id);
    e.dataTransfer.effectAllowed = "move";
  };

  return (
    <div
      draggable
      onDragStart={onDragStart}
      className="flex flex-col items-center gap-[4px] py-1.5 px-1 rounded-lg
                 cursor-grab active:cursor-grabbing
                 hover:bg-white hover:shadow-sm transition-all duration-100"
      title={def.description}
    >
      <div
        className="w-[36px] h-[36px] rounded-full flex items-center justify-center
                   transition-transform duration-100 hover:scale-110"
        style={{
          background: `radial-gradient(circle at 46% 44%, ${color}40, ${color}1a)`,
          border: `1.5px solid ${color}30`,
        }}
      >
        <Icon size={17} color="#555" strokeWidth={1.8} />
      </div>
      <span
        className="text-[9px] text-gray-500 text-center leading-tight w-full"
        style={{ maxWidth: 58, wordBreak: "keep-all", lineHeight: "1.2" }}
      >
        {def.name}
      </span>
    </div>
  );
}

/* ── 아코디언 카테고리 그룹 (Orange3 토글) ──────────── */
function CategoryGroup({
  category,
  nodes,
  open,
  onToggle,
}: {
  category: string;
  nodes: NodeDefinition[];
  open: boolean;
  onToggle: () => void;
}) {
  const color = getCategoryColor(category);
  const label = CATEGORY_META[category]?.label ?? category;
  const CatIcon = CAT_ICON[category] ?? Box;

  return (
    <div className="border-b border-gray-100 last:border-b-0">
      {/* 카테고리 헤더 (토글) */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-left
                   hover:bg-white/70 transition-colors"
      >
        {open
          ? <ChevronDown size={13} className="text-gray-400 flex-shrink-0" />
          : <ChevronRight size={13} className="text-gray-400 flex-shrink-0" />
        }
        <div
          className="w-[20px] h-[20px] rounded-md flex items-center justify-center flex-shrink-0"
          style={{ background: color }}
        >
          <CatIcon size={12} color="#fff" strokeWidth={2} />
        </div>
        <span className={`text-[12px] flex-1 ${open ? "font-bold text-gray-800" : "text-gray-600"}`}>
          {label}
        </span>
        <span className="text-[10px] text-gray-400 tabular-nums">{nodes.length}</span>
      </button>

      {/* 도구 그리드 (펼침 시) */}
      {open && (
        <div className="px-2 pb-2 pt-0.5">
          <div className="grid grid-cols-3 gap-0.5">
            {nodes.map((def) => (
              <ToolTile key={def.id} def={def} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 팔레트 본체 ───────────────────────────────────── */
export function NodePalette() {
  const [search, setSearch] = useState("");
  const [openCats, setOpenCats] = useState<Set<string>>(new Set(["변환"]));
  const definitions = useStore((s) => s.nodeDefinitions);
  const paletteOpen = useStore((s) => s.paletteOpen);

  const toggleCat = (cat: string) => {
    setOpenCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const categories = useMemo(() => {
    const order = ["변환", "전처리", "LLM", "출력", "유틸"];
    const groups: Record<string, NodeDefinition[]> = {};
    for (const cat of order) groups[cat] = [];
    for (const def of definitions) {
      const cat = order.includes(def.category) ? def.category : "유틸";
      groups[cat].push(def);
    }
    return order.map((cat) => ({ cat, nodes: groups[cat] })).filter((g) => g.nodes.length > 0);
  }, [definitions]);

  const searchResults = useMemo(() => {
    if (!search.trim()) return null;
    const q = search.toLowerCase();
    return definitions.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q) ||
        d.description?.toLowerCase().includes(q)
    );
  }, [definitions, search]);

  if (!paletteOpen) return null;

  return (
    <div className="w-[220px] flex-shrink-0 bg-gray-50/80 border-r border-gray-200 flex flex-col select-none">
      {/* 검색 */}
      <div className="px-3 pt-3 pb-2">
        <div className="relative">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="도구 검색..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-7 pr-2 py-[6px] text-[12px] rounded-lg
                       bg-white border border-gray-200 text-gray-700
                       placeholder-gray-400
                       focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400/30
                       transition-all"
          />
        </div>
      </div>

      {/* 카테고리 아코디언 or 검색 결과 */}
      <div className="flex-1 overflow-y-auto">
        {searchResults ? (
          <div className="px-2 pb-2">
            <p className="text-[10px] text-gray-400 px-1 mb-1">
              검색 결과 {searchResults.length}개
            </p>
            {searchResults.length > 0 ? (
              <div className="grid grid-cols-3 gap-0.5">
                {searchResults.map((def) => (
                  <ToolTile key={def.id} def={def} />
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-gray-400 text-center py-6">결과 없음</p>
            )}
          </div>
        ) : (
          categories.map(({ cat, nodes }) => (
            <CategoryGroup
              key={cat}
              category={cat}
              nodes={nodes}
              open={openCats.has(cat)}
              onToggle={() => toggleCat(cat)}
            />
          ))
        )}
      </div>

      {/* 하단 */}
      <div className="px-3 py-1.5 border-t border-gray-200 bg-white/50">
        <p className="text-[10px] text-gray-400">
          {definitions.length}개 도구 · 드래그하여 추가
        </p>
      </div>
    </div>
  );
}
