import { memo, useState } from "react";
import { BaseEdge, getBezierPath, type EdgeProps } from "@xyflow/react";
import { useStore } from "../../store";
import { getPortColor } from "../../constants";
import type { FlowNodeData } from "../../types";

function CustomEdgeComponent({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition,
  sourceHandleId, source, selected,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const nodes = useStore((s) => s.nodes);
  const sourceNode = nodes.find((n) => n.id === source);
  const sourceData = sourceNode?.data as FlowNodeData | undefined;

  let color = "#b0b0b0";
  if (sourceData && sourceHandleId) {
    const port = sourceData.outputs.find((p) => p.name === sourceHandleId);
    if (port) color = getPortColor(port.type);
  }

  const isRunning = sourceData?.status === "running";
  const active = selected || hovered;

  const [edgePath] = getBezierPath({
    sourceX, sourceY, targetX, targetY,
    sourcePosition, targetPosition,
  });

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* 투명한 넓은 히트 영역 (클릭/호버 감지용) */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={24}
        style={{ cursor: "pointer" }}
      />
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: color,
          strokeWidth: active ? 3 : 2,
          strokeOpacity: active ? 1 : 0.55,
          fill: "none",
          strokeDasharray: isRunning ? "6 3" : "none",
          animation: isRunning ? "flow 1.5s linear infinite" : "none",
          transition: "stroke-width 0.15s, stroke-opacity 0.15s",
          cursor: "pointer",
        }}
      />
    </g>
  );
}

export const CustomEdge = memo(CustomEdgeComponent);
