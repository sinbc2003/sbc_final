import { useMemo } from "react";
import { getCategoryColor } from "../constants";

interface MiniNode {
  id: string;
  type: string;
  x: number;
  y: number;
}

interface MiniEdge {
  from: string;
  to: string;
}

interface Props {
  nodes: MiniNode[];
  edges: MiniEdge[];
  width?: number;
  height?: number;
  className?: string;
}

/** 노드 타입 → 카테고리 추정 (정의 없이 빠르게) */
const TYPE_TO_CAT: Record<string, string> = {
  pdf_to_md: "변환", hwpx_to_md: "변환", hwp_to_md: "변환", docx_to_md: "변환",
  xlsx_to_md: "변환", pptx_to_md: "변환", image_to_text: "변환", url_to_md: "변환",
  table_extract: "전처리", data_merge: "전처리", column_mapping: "전처리",
  text_split: "전처리", image_extract: "전처리",
  llm_generate: "LLM", llm_summarize: "LLM", llm_classify: "LLM",
  llm_translate: "LLM", llm_extract: "LLM", rag_query: "LLM",
  md_to_hwpx: "출력", md_to_docx: "출력", save_xlsx: "출력", hwpx_fill: "출력",
  file_input: "유틸", text_input: "유틸", text_template: "유틸", rag_ingest: "유틸",
};

export function MiniFlowChart({ nodes, edges, width = 180, height = 80, className = "" }: Props) {
  const { scaledNodes, scaledEdges } = useMemo(() => {
    if (nodes.length === 0) return { scaledNodes: [], scaledEdges: [] };

    // 노드 위치를 SVG 크기에 맞게 정규화
    const pad = 10;
    const r = 5;
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;

    const nodeMap = new Map<string, { cx: number; cy: number; color: string }>();
    const sn = nodes.map((n) => {
      const cx = pad + ((n.x - minX) / rangeX) * (width - 2 * pad);
      const cy = pad + ((n.y - minY) / rangeY) * (height - 2 * pad);
      const cat = TYPE_TO_CAT[n.type] ?? "유틸";
      const color = getCategoryColor(cat);
      nodeMap.set(n.id, { cx, cy, color });
      return { id: n.id, cx, cy, color, r };
    });

    const se = edges
      .map((e) => {
        const from = nodeMap.get(e.from);
        const to = nodeMap.get(e.to);
        if (!from || !to) return null;
        return { x1: from.cx, y1: from.cy, x2: to.cx, y2: to.cy };
      })
      .filter(Boolean) as { x1: number; y1: number; x2: number; y2: number }[];

    return { scaledNodes: sn, scaledEdges: se };
  }, [nodes, edges, width, height]);

  if (nodes.length === 0) {
    return (
      <svg width={width} height={height} className={className}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fill="#ccc" fontSize={10}>
          빈 워크플로우
        </text>
      </svg>
    );
  }

  return (
    <svg width={width} height={height} className={className}>
      <defs>
        <marker id="mfc-arrow" viewBox="0 0 10 10" refX="8" refY="5"
          markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#bbb" />
        </marker>
      </defs>
      {/* 엣지 (화살표) */}
      {scaledEdges.map((e, i) => (
        <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
          stroke="#bbb" strokeWidth={1.5} markerEnd="url(#mfc-arrow)" />
      ))}
      {/* 노드 */}
      {scaledNodes.map((n) => (
        <g key={n.id}>
          <circle cx={n.cx} cy={n.cy} r={n.r + 1} fill="white" />
          <circle cx={n.cx} cy={n.cy} r={n.r}
            fill={n.color} opacity={0.9} />
        </g>
      ))}
    </svg>
  );
}
