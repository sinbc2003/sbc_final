import { useEffect } from "react";
import { Layout } from "./components/Layout";
import { useStore } from "./store";
import { DEFAULT_NODE_DEFINITIONS } from "./defaultNodes";
import type { NodeDefinition } from "./types";
import { apiUrl } from "./apiBase";

/* ── 초기 노드 정의 로드 ─────────────────────────── */
async function loadNodeDefinitions(): Promise<NodeDefinition[]> {
  let engineNodes: NodeDefinition[] = [];
  try {
    const resp = await fetch(apiUrl("/api/nodes"));
    if (resp.ok) engineNodes = await resp.json();
  } catch {}

  // 엔진이 붙어 있으면 **엔진 카탈로그만** 쓴다.
  // 예전엔 default 전용 노드를 팔레트에 섞었는데, 엔진에 없는 노드는 실행하면
  // 반드시 실패한다(§14 감사 지적). defaultNodes.ts는 엔진 미연결 시 폴백 전용.
  if (engineNodes.length > 0) return engineNodes;
  return DEFAULT_NODE_DEFINITIONS;
}

export default function App() {
  const setNodeDefinitions = useStore((s) => s.setNodeDefinitions);

  useEffect(() => {
    loadNodeDefinitions().then(setNodeDefinitions);
  }, [setNodeDefinitions]);

  // 미저장 변경 상태에서 탭/새로고침 시 경고 — 자동저장(30초) 사이의 유실 방지.
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      const s = useStore.getState();
      if (s.dirty && s.nodes.length > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  return <Layout />;
}
