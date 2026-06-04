import { memo, useMemo, useState, useRef, useCallback } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  Box, CheckCircle2, AlertCircle, Loader2,
} from "lucide-react";
import type { FlowNodeData } from "../../types";
import { getCategoryColor, getPortColor, PORT_TYPE_LABELS } from "../../constants";
import { ICON_MAP } from "../../iconMap";
import { useStore } from "../../store";

const NODE_SIZE = 72;
const TOOLTIP_DELAY = 500;

/* ── 호버 툴팁 ──────────────────────────────────── */
function NodeTooltip({ data, catColor }: { data: FlowNodeData; catColor: string }) {
  return (
    <div
      className="absolute z-50 pointer-events-none"
      style={{ top: -8, left: NODE_SIZE + 14, width: 220 }}
    >
      <div
        className="rounded-lg shadow-lg border border-gray-200 bg-white p-3"
        style={{ borderTop: `3px solid ${catColor}` }}
      >
        {/* 헤더 */}
        <p className="text-[12px] font-bold text-gray-800">{data.label}</p>
        <p className="text-[10px] text-gray-500 mt-0.5 leading-snug">{data.description}</p>

        {/* 입력 포트 */}
        {data.inputs.length > 0 && (
          <div className="mt-2">
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">입력</p>
            {data.inputs.map((p) => (
              <div key={p.name} className="flex items-center gap-1 py-[2px]">
                <span
                  className="w-[6px] h-[6px] rounded-full flex-shrink-0"
                  style={{ background: getPortColor(p.type) }}
                />
                <span className="text-[10px] text-gray-700">{p.name}</span>
                <span className="text-[9px] text-gray-400">
                  {PORT_TYPE_LABELS[p.type] ?? p.type}
                </span>
                {p.accept && (
                  <span className="text-[8px] text-gray-400">{p.accept.join(" ")}</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 출력 포트 */}
        {data.outputs.length > 0 && (
          <div className="mt-1.5">
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">출력</p>
            {data.outputs.map((p) => (
              <div key={p.name} className="flex items-center gap-1 py-[2px]">
                <span
                  className="w-[6px] h-[6px] rounded-full flex-shrink-0"
                  style={{ background: getPortColor(p.type) }}
                />
                <span className="text-[10px] text-gray-700">{p.name}</span>
                <span className="text-[9px] text-gray-400">
                  {PORT_TYPE_LABELS[p.type] ?? p.type}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* 파라미터 */}
        {data.params.length > 0 && (
          <div className="mt-1.5">
            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-wider mb-0.5">설정</p>
            {data.params.map((p) => (
              <div key={p.id} className="text-[10px] text-gray-600 py-[1px]">
                <span className="font-medium">{p.label}</span>
                {p.default !== undefined && p.default !== "" && (
                  <span className="text-gray-400 ml-1">= {String(p.default)}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Orange3 원형 노드 ─────────────────────────── */
function CustomNodeComponent({ data, selected, id }: NodeProps) {
  const nodeData = data as FlowNodeData;
  const selectNode = useStore((s) => s.selectNode);
  const catColor = useMemo(() => getCategoryColor(nodeData.category), [nodeData.category]);
  const Icon = ICON_MAP[nodeData.icon] ?? Box;

  const isRunning = nodeData.status === "running";
  const isDone = nodeData.status === "done";
  const isError = nodeData.status === "error";

  const inputs = nodeData.inputs;
  const outputs = nodeData.outputs;

  /* ── 툴팁 딜레이 ── */
  const [showTooltip, setShowTooltip] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onEnter = useCallback(() => {
    timerRef.current = setTimeout(() => setShowTooltip(true), TOOLTIP_DELAY);
  }, []);
  const onLeave = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setShowTooltip(false);
  }, []);

  return (
    <div
      className={`tf-node group relative ${isRunning ? "node-running" : ""}`}
      style={{ width: NODE_SIZE }}
      onClick={() => selectNode(id)}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      {/* ── Input 핸들 — 왼쪽 점선 호 ( ── */}
      {inputs.map((port, i) => {
        const top = NODE_SIZE / (inputs.length + 1) * (i + 1);
        return (
          <Handle
            key={`in-${port.name}`}
            type="target"
            position={Position.Left}
            id={port.name}
            isConnectableStart={true}
            className="tf-arc-left"
            style={{ top }}
            title={`${port.name} (${port.type})`}
          />
        );
      })}

      {/* ── 원형 본체 ── */}
      <div
        className="tf-node-body relative flex items-center justify-center"
        style={{
          width: NODE_SIZE,
          height: NODE_SIZE,
          borderRadius: "50%",
          background: `radial-gradient(circle at 46% 44%, ${catColor}45, ${catColor}1a)`,
          border: isError
            ? "2.5px solid #ef4444"
            : selected
            ? `2.5px solid ${catColor}aa`
            : `1.5px solid ${catColor}30`,
          boxShadow: selected
            ? `0 0 0 4px ${catColor}18, 0 4px 16px ${catColor}20`
            : `0 2px 10px ${catColor}12`,
          transition: "all 0.15s ease",
        }}
      >
        <Icon size={28} color="#555" strokeWidth={1.7} />

        {isRunning && (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ borderRadius: "50%", background: "rgba(255,255,255,0.35)" }}
          >
            <Loader2 size={24} className="animate-spin" style={{ color: catColor }} />
          </div>
        )}
      </div>

      {/* ── 상태 배지 ── */}
      {isDone && (
        <CheckCircle2 size={16} className="absolute text-emerald-500"
          style={{ top: 1, right: 1, background: "#fff", borderRadius: "50%" }} />
      )}
      {isError && (
        <AlertCircle size={16} className="absolute text-red-500"
          style={{ top: 1, right: 1, background: "#fff", borderRadius: "50%" }} />
      )}

      {/* ── 라벨 ── */}
      <p
        className="text-[11px] font-medium text-center leading-tight select-none"
        style={{
          color: "#555",
          marginTop: 5,
          maxWidth: 100,
          marginLeft: (NODE_SIZE - 100) / 2,
          wordBreak: "keep-all",
          lineHeight: "1.3",
          textShadow: "0 0 8px #fff, 0 0 8px #fff",
        }}
      >
        {nodeData.label}
      </p>

      {/* ── 호버 툴팁 (500ms 후 표시) ── */}
      {showTooltip && <NodeTooltip data={nodeData} catColor={catColor} />}

      {/* ── Output 핸들 — 오른쪽 실선 호 ) ── */}
      {outputs.map((port, i) => {
        const top = NODE_SIZE / (outputs.length + 1) * (i + 1);
        return (
          <Handle
            key={`out-${port.name}`}
            type="source"
            position={Position.Right}
            id={port.name}
            isConnectableEnd={true}
            className="tf-arc-right"
            style={{ top }}
            title={`${port.name} (${port.type})`}
          />
        );
      })}
    </div>
  );
}

export const CustomNode = memo(CustomNodeComponent);
