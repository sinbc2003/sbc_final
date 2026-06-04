import type { FlowNodeData, NodeDefinition } from "../types";

let nodeCounter = 0;
export const nextId = () => `node_${++nodeCounter}_${Date.now().toString(36)}`;

export function definitionToFlowData(def: NodeDefinition): FlowNodeData {
  const paramValues: Record<string, any> = {};
  for (const p of def.params) {
    paramValues[p.id] = p.default ?? "";
  }
  return {
    definitionId: def.id,
    label: def.name,
    category: def.category,
    icon: def.icon,
    description: def.description,
    inputs: def.inputs,
    outputs: def.outputs,
    params: def.params,
    paramValues,
    status: "idle",
    progress: 0,
  };
}
