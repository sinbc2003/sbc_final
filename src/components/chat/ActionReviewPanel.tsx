import { FileEdit } from "lucide-react";
import { describeAction } from "./describeAction";

interface Props {
  actions: Array<{ action: string; params: any; checked: boolean }>;
  sending: boolean;
  onToggle: (index: number) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onApply: () => void;
  onCancel: () => void;
  /** fill_cell 값 인라인 수정 — 수정값은 정답 라벨로 피드백 로그에 남는다 */
  onEditValue?: (index: number, value: string) => void;
}

export function ActionReviewPanel({ actions, sending, onToggle, onSelectAll, onDeselectAll, onApply, onCancel, onEditValue }: Props) {
  const checkedCount = actions.filter(a => a.checked).length;
  return (
    <div className="border-t border-blue-200 px-4 py-3 bg-blue-50/30">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[12px] font-bold text-blue-700 flex items-center gap-1.5">
            <FileEdit size={12} />
            수정 내역 검토 ({checkedCount}/{actions.length})
          </span>
          <div className="flex gap-1.5">
            <button onClick={onSelectAll} className="px-2 py-0.5 rounded text-[10px] text-blue-600 hover:bg-blue-100">전체선택</button>
            <button onClick={onDeselectAll} className="px-2 py-0.5 rounded text-[10px] text-gray-500 hover:bg-gray-100">전체해제</button>
            <button onClick={onApply} disabled={sending || checkedCount === 0}
              className="px-3 py-1 rounded text-[11px] font-medium bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 transition-colors">
              {sending ? "반영 중..." : "반영"}
            </button>
            <button onClick={onCancel}
              className="px-3 py-1 rounded text-[11px] font-medium bg-gray-200 text-gray-600 hover:bg-gray-300 transition-colors">
              취소
            </button>
          </div>
        </div>
        <div className="space-y-0.5 max-h-48 overflow-y-auto">
          {actions.map((act, i) => (
            <label key={i} className="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-blue-100/50 cursor-pointer">
              <input type="checkbox" checked={act.checked}
                onChange={() => onToggle(i)}
                className="rounded border-blue-300 text-blue-500 w-3.5 h-3.5" />
              {act.action === "fill_cell" && onEditValue ? (
                <span className="flex items-center gap-1.5 flex-1 min-w-0 text-[12px] text-gray-700">
                  <span className="truncate max-w-[45%]">{(act.params?.label || act.params?.id || "").split("—")[0].trim()}</span>
                  <span className="text-gray-400 flex-shrink-0">←</span>
                  <input
                    type="text"
                    value={act.params?.value ?? ""}
                    onChange={(e) => onEditValue(i, e.target.value)}
                    onClick={(e) => e.preventDefault()}
                    disabled={!act.checked}
                    className="flex-1 min-w-0 px-1.5 py-0.5 rounded border border-blue-200 bg-white
                      text-[12px] text-gray-800 focus:border-blue-400 focus:outline-none disabled:opacity-40"
                  />
                </span>
              ) : (
                <span className="text-[12px] text-gray-700">{describeAction(act)}</span>
              )}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
