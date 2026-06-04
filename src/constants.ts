/** 카테고리 → 색상 (Orange3 스타일) */
export const CATEGORY_META: Record<
  string,
  { color: string; bg: string; label: string }
> = {
  변환:   { color: "#e8a028", bg: "#fef6e7", label: "변환" },
  전처리: { color: "#6cc04a", bg: "#eef9e8", label: "전처리" },
  LLM:    { color: "#9b59b6", bg: "#f3eaf8", label: "LLM" },
  출력:   { color: "#3daee9", bg: "#ebf5fb", label: "출력" },
  유틸:   { color: "#95a5a6", bg: "#f0f2f2", label: "유틸" },
};

/** 포트 타입 → 색상 */
export const PORT_COLORS: Record<string, string> = {
  file: "#4a90d9",
  text: "#2ecc71",
  table: "#e8a028",
  image: "#e74c8b",
  list: "#1abc9c",
  any: "#95a5a6",
};

export const PORT_TYPE_LABELS: Record<string, string> = {
  file: "파일",
  text: "텍스트",
  table: "표",
  image: "이미지",
  list: "목록",
  any: "모든 타입",
};

export function getCategoryColor(category: string): string {
  return CATEGORY_META[category]?.color ?? CATEGORY_META["유틸"].color;
}

export function getCategoryBg(category: string): string {
  return CATEGORY_META[category]?.bg ?? CATEGORY_META["유틸"].bg;
}

export function getPortColor(type: string): string {
  return PORT_COLORS[type] ?? PORT_COLORS.any;
}

// ── 앱 상수 ──────────────────────────────────────
export const AUTO_SAVE_INTERVAL_MS = 30_000;
export const ENGINE_HEALTH_CHECK_INTERVAL_MS = 10_000;
export const FETCH_TIMEOUT_MS = 3000;
export const AUTOSAVE_KEY = "tf_autosave";
export const SYSTEM_NODE_ID = "SYSTEM";
export const FILE_PARAM_PREFIX = "__file_";

export const EXECUTION_PANEL_SIZE = {
  COLLAPSED: 32,
  MIN_EXPANDED: 220,
  MAX_EXPANDED: 400,
} as const;
