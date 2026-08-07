import { useEffect } from "react";
import { AlertTriangle, Info, XCircle, X } from "lucide-react";
import { useStore } from "../store";

/** 짧은 피드백 배너 — 연결 실패 사유처럼 '무음으로 사라지던' 동작을 설명한다. */
const STYLES = {
  info: { bg: "bg-gray-800", icon: Info },
  warn: { bg: "bg-amber-600", icon: AlertTriangle },
  error: { bg: "bg-red-600", icon: XCircle },
} as const;

const AUTO_DISMISS_MS = 4500;

export function Toast() {
  const toast = useStore((s) => s.toast);
  const dismiss = useStore((s) => s.dismissToast);

  // id가 바뀔 때마다 타이머 재시작 — 같은 문구가 연달아 떠도 표시 시간이 보장된다
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(dismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [toast?.id, dismiss]);

  if (!toast) return null;
  const { bg, icon: Icon } = STYLES[toast.kind];

  return (
    <div className="fixed bottom-12 left-1/2 -translate-x-1/2 z-[100] pointer-events-none">
      <div
        className={`${bg} text-white rounded-lg shadow-lg px-4 py-2.5 flex items-start gap-2
          max-w-[560px] pointer-events-auto`}
        role="status"
      >
        <Icon size={15} className="flex-shrink-0 mt-0.5" />
        <span className="text-[12px] leading-relaxed">{toast.message}</span>
        <button onClick={dismiss} className="ml-1 flex-shrink-0 opacity-70 hover:opacity-100">
          <X size={13} />
        </button>
      </div>
    </div>
  );
}
