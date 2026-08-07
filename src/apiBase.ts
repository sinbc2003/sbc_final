/**
 * 엔진 API 베이스 URL 단일 진실.
 *
 * dev: ""(상대경로) — vite proxy(vite.config.ts)가 127.0.0.1 엔진으로 중계.
 * Tauri 프로덕션: 프론트가 tauri://localhost 정적 서빙이라 상대 /api가
 * asset 핸들러로 흘러 전부 404(§28 정찰) → 127.0.0.1 절대주소 필수.
 * 포트는 Rust setup이 initialization_script로 주입(window.__ENGINE_PORT__).
 */

declare global {
  interface Window {
    __ENGINE_PORT__?: number;
    __TAURI_INTERNALS__?: unknown;
  }
}

const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export const API_BASE: string =
  import.meta.env.DEV || !isTauri
    ? ""
    : `http://127.0.0.1:${window.__ENGINE_PORT__ ?? 8406}`;

/** fetch(apiUrl("/api/...")) 형태로 사용 — 모든 엔진 호출은 이 헬퍼를 거친다. */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}
