import { useEffect } from "react";
import { Layout } from "./components/Layout";
import { useStore } from "./store";
import { DEFAULT_NODE_DEFINITIONS } from "./defaultNodes";
import type { NodeDefinition } from "./types";

/* ── 초기 노드 정의 로드 ─────────────────────────── */
async function loadNodeDefinitions(): Promise<NodeDefinition[]> {
  // 엔진 노드가 있으면 가져와서 fallback과 병합 (엔진 우선)
  let engineNodes: NodeDefinition[] = [];
  try {
    const resp = await fetch("/api/nodes");
    if (resp.ok) engineNodes = await resp.json();
  } catch {}

  // 엔진 노드가 있으면 fallback과 병합 (엔진 노드가 우선)
  if (engineNodes.length === 0) return DEFAULT_NODE_DEFINITIONS;
  const engineIds = new Set(engineNodes.map((n) => n.id));
  const extras = DEFAULT_NODE_DEFINITIONS.filter((f) => !engineIds.has(f.id));
  return [...engineNodes, ...extras];
}

export default function App() {
  const setNodeDefinitions = useStore((s) => s.setNodeDefinitions);

  useEffect(() => {
    loadNodeDefinitions().then(setNodeDefinitions);
  }, [setNodeDefinitions]);

  return <Layout />;
}
