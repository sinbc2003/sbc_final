import type { Connection, Edge } from "@xyflow/react";
import type { FlowNodeData } from "./types";
import { PORT_TYPE_LABELS } from "./constants";

/* ── 연결 가능 여부 + 사유 ─────────────────────────
   isValidConnection(불리언)과 실패 안내(문구)가 같은 규칙을 쓰도록 한 곳으로
   모았다. 예전엔 false만 반환해 드래그한 선이 소리 없이 사라졌다. */

export type ConnCheck = { ok: true } | { ok: false; reason: string };

type NodeLike = { id: string; data: FlowNodeData };

const typeLabel = (t: string) => `${PORT_TYPE_LABELS[t] ?? t}(${t})`;

export function checkConnection(
  connection: Edge | Connection,
  nodes: NodeLike[]
): ConnCheck {
  const { source, target, sourceHandle, targetHandle } = connection;
  if (!source || !target) return { ok: false, reason: "연결할 노드를 찾지 못했습니다." };
  if (source === target)
    return { ok: false, reason: "같은 노드끼리는 연결할 수 없습니다." };

  const sourceNode = nodes.find((n) => n.id === source);
  const targetNode = nodes.find((n) => n.id === target);
  if (!sourceNode || !targetNode)
    return { ok: false, reason: "연결할 노드를 찾지 못했습니다." };

  const srcData = sourceNode.data;
  const tgtData = targetNode.data;

  // 정방향: source의 output → target의 input
  let outPort = srcData.outputs.find((p) => p.name === sourceHandle);
  let inPort = tgtData.inputs.find((p) => p.name === targetHandle);

  // 역방향: source가 실제로 input이고 target이 output (드래그 방향 반대)
  if (!outPort || !inPort) {
    outPort = tgtData.outputs.find((p) => p.name === targetHandle);
    inPort = srcData.inputs.find((p) => p.name === sourceHandle);
  }

  if (!outPort || !inPort)
    return { ok: false, reason: "출력 → 입력 방향으로만 연결할 수 있습니다." };

  // 타입 호환성
  if (outPort.type !== "any" && inPort.type !== "any" && outPort.type !== inPort.type) {
    return {
      ok: false,
      reason:
        `${typeLabel(outPort.type)} 출력은 ${typeLabel(inPort.type)} 입력에 ` +
        `연결할 수 없습니다 — 사이에 변환 노드를 넣으세요.`,
    };
  }

  // file accept 검사 (양쪽 다 확장자를 선언했을 때만 교집합을 요구)
  if (outPort.type === "file" && inPort.accept?.length && outPort.accept?.length) {
    const overlap = outPort.accept.filter((a) => inPort!.accept!.includes(a));
    if (overlap.length === 0) {
      return {
        ok: false,
        reason:
          `'${inPort.name}' 입력은 ${inPort.accept.join(", ")} 형식만 받습니다 ` +
          `(보낸 형식: ${outPort.accept.join(", ")}).`,
      };
    }
  }

  return { ok: true };
}
