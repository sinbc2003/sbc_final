import { useState, useEffect } from "react";
import {
  FileText, Files, Tag, Database, Table2,
  Plus, MessageSquare, ArrowRight, Wand2, Sparkles,
  RefreshCw,
} from "lucide-react";
import { useStore } from "../store";
import { TaskRunner } from "./TaskRunner";
import { FormAssist } from "./FormAssist";

/* ── 프리셋 메타 (서버 응답) ── */
interface PresetMeta {
  id: string;
  name: string;
  description: string;
  tags: string[];
  node_count: number;
  edge_count: number;
}

/* ── 아이콘 매핑 ── */
const TAG_ICON_MAP: [string, typeof FileText][] = [
  ["PDF", FileText],
  ["요약", Sparkles],
  ["번역", FileText],
  ["병합", Files],
  ["분류", Tag],
  ["RAG", Database],
  ["검색", Database],
  ["성적", Table2],
];

function pickIcon(name: string, tags: string[]) {
  const haystack = [name, ...tags].join(" ");
  for (const [keyword, Icon] of TAG_ICON_MAP) {
    if (haystack.includes(keyword)) return Icon;
  }
  return Wand2;
}

/* ── 카테고리 색상 (카드 악센트) ── */
const CARD_COLORS = [
  { bg: "bg-amber-50", hover: "hover:border-amber-300", icon: "text-amber-600", iconBg: "bg-amber-50 group-hover:bg-amber-100" },
  { bg: "bg-blue-50", hover: "hover:border-blue-300", icon: "text-blue-600", iconBg: "bg-blue-50 group-hover:bg-blue-100" },
  { bg: "bg-emerald-50", hover: "hover:border-emerald-300", icon: "text-emerald-600", iconBg: "bg-emerald-50 group-hover:bg-emerald-100" },
  { bg: "bg-violet-50", hover: "hover:border-violet-300", icon: "text-violet-600", iconBg: "bg-violet-50 group-hover:bg-violet-100" },
  { bg: "bg-rose-50", hover: "hover:border-rose-300", icon: "text-rose-600", iconBg: "bg-rose-50 group-hover:bg-rose-100" },
];

export function HomeScreen() {
  const setMode = useStore((s) => s.setMode);
  const [presets, setPresets] = useState<PresetMeta[]>([]);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [showFormAssist, setShowFormAssist] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchPresets = () => {
    setLoading(true);
    fetch("/api/presets")
      .then((r) => r.json())
      .then((data) => setPresets(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchPresets(); }, []);

  /* FormAssist */
  if (showFormAssist) {
    return <FormAssist onBack={() => setShowFormAssist(false)} />;
  }

  /* TaskRunner */
  if (activePresetId) {
    return <TaskRunner presetId={activePresetId} onBack={() => setActivePresetId(null)} />;
  }

  return (
    <div className="flex-1 bg-tf-bg overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-16">
        {/* ── 헤더 ── */}
        <div className="text-center mb-12">
          <h1 className="text-2xl font-bold text-gray-800 mb-2">
            오늘 뭘 하시겠어요?
          </h1>
          <p className="text-sm text-gray-500">
            업무를 선택하면 파일만 넣고 바로 실행됩니다.
          </p>
        </div>

        {/* ── 프리셋 카드 ── */}
        {loading ? (
          <div className="flex justify-center py-16">
            <RefreshCw size={20} className="animate-spin text-gray-400" />
          </div>
        ) : presets.length === 0 ? (
          <div className="text-center py-16 text-sm text-gray-400">
            등록된 업무가 없습니다. 설계 모드에서 워크플로우를 만들고 프리셋으로 저장하세요.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-12">
            {presets.map((preset, idx) => {
              const Icon = pickIcon(preset.name, preset.tags || []);
              const color = CARD_COLORS[idx % CARD_COLORS.length];
              return (
                <button
                  key={preset.id}
                  onClick={() => preset.id === "preset_form_fill" ? setShowFormAssist(true) : setActivePresetId(preset.id)}
                  className={`group bg-white rounded-xl border border-gray-200 p-5 text-left
                    ${color.hover} hover:shadow-md transition-all duration-150`}
                >
                  <div className="flex items-start gap-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center
                      flex-shrink-0 transition-colors ${color.iconBg}`}>
                      <Icon size={20} className={color.icon} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="text-[14px] font-semibold text-gray-800 mb-1">
                        {preset.name}
                      </h3>
                      <p className="text-[12px] text-gray-500 line-clamp-2 leading-relaxed">
                        {preset.description}
                      </p>
                    </div>
                    <ArrowRight
                      size={16}
                      className="text-gray-300 group-hover:text-gray-500 transition-colors mt-1 flex-shrink-0"
                    />
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {/* ── 하단 액션 ── */}
        <div className="flex justify-center gap-3 pt-4 border-t border-gray-200">
          <button
            onClick={() => setMode("design")}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-gray-200
              text-[13px] text-gray-600 hover:bg-white hover:border-gray-300 transition-all"
          >
            <Plus size={15} />
            직접 만들기
          </button>
          <button
            onClick={() => setMode("chat")}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-gray-200
              text-[13px] text-gray-600 hover:bg-white hover:border-gray-300 transition-all"
          >
            <MessageSquare size={15} />
            채팅으로 만들기
          </button>
        </div>
      </div>
    </div>
  );
}
