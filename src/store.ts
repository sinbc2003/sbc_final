import { create } from "zustand";
import {
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
} from "@xyflow/react";
import type {
  FlowNodeData,
  NodeDefinition,
  AppMode,
  ExecutionStatus,
  ChatMessage,
  WorkflowJSON,
} from "./types";

/* ── helpers ─────────────────────────────────────── */

let nodeCounter = 0;
const nextId = () => `node_${++nodeCounter}_${Date.now().toString(36)}`;

function definitionToFlowData(def: NodeDefinition): FlowNodeData {
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

/* ── store type ──────────────────────────────────── */

export interface AppState {
  // 모드
  mode: AppMode;
  setMode: (m: AppMode) => void;

  // 노드 정의 (엔진에서 로드)
  nodeDefinitions: NodeDefinition[];
  setNodeDefinitions: (defs: NodeDefinition[]) => void;

  // React Flow 상태
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;

  // 노드 조작
  addNode: (defId: string, position: { x: number; y: number }) => void;
  addFileNode: (position: { x: number; y: number }, filePath: string, fileName: string) => string | null;
  deleteSelected: () => void;
  updateNodeParams: (nodeId: string, paramValues: Record<string, any>) => void;

  // 선택
  selectedNodeId: string | null;
  selectNode: (id: string | null) => void;

  // 실행
  executionStatus: ExecutionStatus;
  setExecutionStatus: (s: ExecutionStatus) => void;
  setNodeStatus: (
    nodeId: string,
    status: FlowNodeData["status"],
    progress?: number,
    error?: string
  ) => void;
  runWorkflow: () => Promise<void>;

  // 실행 로그/결과
  executionLogs: { nodeId: string; nodeName: string; message: string; timestamp: number }[];
  executionOutputs: Record<string, Record<string, string>>;
  executionPanelOpen: boolean;
  toggleExecutionPanel: () => void;

  // 워크플로우 직렬화
  toWorkflowJSON: () => WorkflowJSON;
  loadWorkflowJSON: (wf: WorkflowJSON) => void;

  // 워크플로우 메타
  workflowId: string | null;
  workflowName: string;
  workflowDescription: string;
  setWorkflowMeta: (name: string, description?: string) => void;
  dirty: boolean; // 미저장 변경 있음

  // 저장 / 불러오기
  saveWorkflow: () => Promise<string | null>;
  saveAsWorkflow: (name: string, description?: string) => Promise<string | null>;
  autoSave: () => void;
  loadAutoSave: () => Promise<boolean>;
  newWorkflow: () => void;

  // 워크플로우 매니저
  managerOpen: boolean;
  setManagerOpen: (open: boolean) => void;

  // 채팅
  chatMessages: ChatMessage[];
  addChatMessage: (msg: Omit<ChatMessage, "id" | "timestamp"> & { id?: string }) => void;
  updateChatMessage: (id: string, updates: Partial<ChatMessage>) => void;
  clearChat: () => void;

  // 사이드바
  paletteOpen: boolean;
  propertiesOpen: boolean;
  togglePalette: () => void;
  toggleProperties: () => void;
}

export const useStore = create<AppState>((set, get) => ({
  /* ── 모드 ───────────────────────────── */
  mode: "home",  // 기본 화면: 홈
  setMode: (m) => set({ mode: m }),

  /* ── 노드 정의 ─────────────────────── */
  nodeDefinitions: [],
  setNodeDefinitions: (defs) => set({ nodeDefinitions: defs }),

  /* ── React Flow ────────────────────── */
  nodes: [],
  edges: [],

  onNodesChange: (changes) =>
    set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) as Node<FlowNodeData>[], dirty: true })),

  onEdgesChange: (changes) =>
    set((s) => ({ edges: applyEdgeChanges(changes, s.edges), dirty: true })),

  onConnect: (connection) => {
    const { nodes } = get();
    let { source, sourceHandle, target, targetHandle } = connection;

    // 역방향 감지: source 노드에서 sourceHandle이 input이면 방향 뒤집기
    const srcNode = nodes.find((n) => n.id === source);
    if (srcNode) {
      const srcData = srcNode.data as FlowNodeData;
      const isReversed = srcData.inputs.some((p) => p.name === sourceHandle);
      if (isReversed) {
        [source, target] = [target!, source!];
        [sourceHandle, targetHandle] = [targetHandle!, sourceHandle!];
      }
    }

    set((s) => ({
      edges: addEdge(
        { source: source!, sourceHandle, target: target!, targetHandle, type: "smoothstep", animated: false },
        s.edges
      ),
      dirty: true,
    }));
  },

  /* ── 노드 조작 ─────────────────────── */
  addNode: (defId, position) => {
    const def = get().nodeDefinitions.find((d) => d.id === defId);
    if (!def) return;
    const newNode: Node<FlowNodeData> = {
      id: nextId(),
      type: "custom",
      position,
      data: definitionToFlowData(def),
    };
    set((s) => ({ nodes: [...s.nodes, newNode], dirty: true }));
  },

  addFileNode: (position, filePath, fileName) => {
    const def = get().nodeDefinitions.find((d) => d.id === "file_input");
    if (!def) return null;
    const id = nextId();
    const data = definitionToFlowData(def);
    data.paramValues.path = filePath;
    data.label = `📄 ${fileName}`;
    const newNode: Node<FlowNodeData> = { id, type: "custom", position, data };
    set((s) => ({ nodes: [...s.nodes, newNode], dirty: true, selectedNodeId: id }));
    return id;
  },

  deleteSelected: () =>
    set((s) => {
      const selectedIds = new Set(
        s.nodes.filter((n) => n.selected).map((n) => n.id)
      );
      if (selectedIds.size === 0) return s;
      return {
        nodes: s.nodes.filter((n) => !selectedIds.has(n.id)),
        edges: s.edges.filter(
          (e) => !selectedIds.has(e.source) && !selectedIds.has(e.target)
        ),
        selectedNodeId:
          s.selectedNodeId && selectedIds.has(s.selectedNodeId)
            ? null
            : s.selectedNodeId,
      };
    }),

  updateNodeParams: (nodeId, paramValues) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, paramValues: { ...n.data.paramValues, ...paramValues } } }
          : n
      ),
      dirty: true,
    })),

  /* ── 선택 ───────────────────────────── */
  selectedNodeId: null,
  selectNode: (id) => set({ selectedNodeId: id }),

  /* ── 실행 ───────────────────────────── */
  executionStatus: "idle",
  setExecutionStatus: (s) => set({ executionStatus: s }),

  setNodeStatus: (nodeId, status, progress = 0, error) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, status, progress, error } }
          : n
      ),
    })),

  runWorkflow: async () => {
    // 이중 실행 방지
    if (get().executionStatus === "running") return;

    const { toWorkflowJSON, setExecutionStatus, setNodeStatus, nodes } = get();
    setExecutionStatus("running");
    set({ executionLogs: [], executionOutputs: {}, executionPanelOpen: true });

    // 모든 노드를 idle로 리셋
    for (const n of nodes) {
      setNodeStatus(n.id, "idle", 0);
    }

    try {
      const wf = toWorkflowJSON();
      const resp = await fetch("/api/run-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(wf),
      });

      if (!resp.body) {
        setExecutionStatus("error");
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE 파싱: "data: {...}\n\n" 패턴
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const match = line.match(/^data:\s*(.+)/);
          if (!match) continue;
          let evt: any;
          try {
            evt = JSON.parse(match[1]);
          } catch {
            continue;
          }

          if (evt.event === "node_progress") {
            if (evt.progress === 0) setNodeStatus(evt.node_id, "running", 0);
            else if (evt.progress >= 1) setNodeStatus(evt.node_id, "done", 1);
            else setNodeStatus(evt.node_id, "running", evt.progress);
          }
          if (evt.event === "node_log") {
            set((s) => ({
              executionLogs: [
                ...s.executionLogs,
                {
                  nodeId: evt.node_id,
                  nodeName: evt.node_name,
                  message: evt.message,
                  timestamp: Date.now(),
                },
              ],
            }));
          }
          if (evt.event === "done") {
            set({ executionOutputs: evt.outputs || {} });
            setExecutionStatus(evt.success ? "done" : "error");
            // 완료 시 아직 'running'인 노드는 실패로 마감 — 실패 노드가
            // 영원히 스피너로 남는 문제 해소(done엔 실패 노드 개별 신호가 없음).
            for (const n of get().nodes) {
              if (n.data?.status === "running") {
                setNodeStatus(n.id, "error", 0, "실행 중단됨");
              }
            }
            for (const err of evt.errors || []) {
              set((s) => ({
                executionLogs: [
                  ...s.executionLogs,
                  {
                    nodeId: "SYSTEM",
                    nodeName: "시스템",
                    message: `[오류] ${err}`,
                    timestamp: Date.now(),
                  },
                ],
              }));
            }
          }
          if (evt.event === "error") {
            setExecutionStatus("error");
            set((s) => ({
              executionLogs: [
                ...s.executionLogs,
                {
                  nodeId: "SYSTEM",
                  nodeName: "시스템",
                  message: `[치명적 오류] ${evt.message}`,
                  timestamp: Date.now(),
                },
              ],
            }));
          }
        }
      }
    } catch {
      setExecutionStatus("error");
      set((s) => ({
        executionLogs: [
          ...s.executionLogs,
          {
            nodeId: "SYSTEM",
            nodeName: "시스템",
            message: "[치명적 오류] 서버 연결 실패",
            timestamp: Date.now(),
          },
        ],
      }));
    }
  },

  /* ── 실행 로그/결과 ────────────────── */
  executionLogs: [],
  executionOutputs: {},
  executionPanelOpen: false,
  toggleExecutionPanel: () => set((s) => ({ executionPanelOpen: !s.executionPanelOpen })),

  /* ── 워크플로우 직렬화 ─────────────── */
  toWorkflowJSON: () => {
    const { nodes, edges } = get();

    // __file_* 파라미터를 initial_inputs로 변환
    const initialInputs: Record<string, Record<string, any>> = {};
    const cleanedNodes = nodes.map((n) => {
      const params: Record<string, any> = {};
      for (const [k, v] of Object.entries(n.data.paramValues)) {
        if (k.startsWith("__file_") && v) {
          // __file_파일 → 입력 포트 "파일"
          const portName = k.slice(7); // "__file_".length === 7
          if (!initialInputs[n.id]) initialInputs[n.id] = {};
          initialInputs[n.id][portName] = v;
        } else {
          params[k] = v;
        }
      }
      return { id: n.id, type: n.data.definitionId, position: n.position, params };
    });

    return {
      id: `wf_${Date.now().toString(36)}`,
      name: "워크플로우",
      version: "1.0.0",
      description: "",
      created_at: new Date().toISOString(),
      nodes: cleanedNodes,
      edges: edges.map((e) => ({
        from: e.source,
        from_port: e.sourceHandle ?? "",
        to: e.target,
        to_port: e.targetHandle ?? "",
      })),
      user_inputs: [],
      initial_inputs: initialInputs,
    };
  },

  loadWorkflowJSON: (wf) => {
    const { nodeDefinitions } = get();
    const defMap = new Map(nodeDefinitions.map((d) => [d.id, d]));

    const newNodes: Node<FlowNodeData>[] = wf.nodes
      .map((wn) => {
        const def = defMap.get(wn.type);
        if (!def) return null;
        const data = definitionToFlowData(def);
        data.paramValues = { ...data.paramValues, ...wn.params };
        return {
          id: wn.id,
          type: "custom" as const,
          position: wn.position,
          data,
        };
      })
      .filter(Boolean) as Node<FlowNodeData>[];

    const newEdges: Edge[] = wf.edges.map((we: any, i: number) => ({
      id: `e_${i}`,
      source: we.from || we.source,
      sourceHandle: we.from_port || we.sourceHandle,
      target: we.to || we.target,
      targetHandle: we.to_port || we.targetHandle,
      type: "smoothstep",
    }));

    const meta = (wf as any)._meta;
    set({
      nodes: newNodes, edges: newEdges, selectedNodeId: null,
      workflowId: meta?.id ?? wf.id ?? null,
      workflowName: meta?.name ?? wf.name ?? "불러온 워크플로우",
      workflowDescription: meta?.description ?? wf.description ?? "",
      dirty: false,
    });
  },

  /* ── 워크플로우 메타 ─────────────────── */
  workflowId: null,
  workflowName: "새 워크플로우",
  workflowDescription: "",
  dirty: false,
  setWorkflowMeta: (name, description) =>
    set({ workflowName: name, workflowDescription: description ?? get().workflowDescription }),

  /* ── 저장 / 불러오기 ───────────────── */
  saveWorkflow: async () => {
    const { toWorkflowJSON, workflowId, workflowName, workflowDescription } = get();
    const wf = toWorkflowJSON();
    wf.name = workflowName;
    wf.description = workflowDescription;
    try {
      const res = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: wf, workflow_id: workflowId }),
      });
      const meta = await res.json();
      set({ workflowId: meta.id, dirty: false });
      return meta.id;
    } catch { return null; }
  },

  saveAsWorkflow: async (name, description) => {
    set({ workflowName: name, workflowDescription: description ?? "" });
    const { toWorkflowJSON } = get();
    const wf = toWorkflowJSON();
    wf.name = name;
    wf.description = description ?? "";
    try {
      const res = await fetch("/api/workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: wf }),
      });
      const meta = await res.json();
      set({ workflowId: meta.id, dirty: false });
      return meta.id;
    } catch { return null; }
  },

  autoSave: () => {
    const { toWorkflowJSON, workflowName, nodes } = get();
    if (nodes.length === 0) return;
    const wf = toWorkflowJSON();
    wf.name = workflowName;
    // localStorage + 서버 양쪽에 저장
    try {
      localStorage.setItem("tf_autosave", JSON.stringify(wf));
      fetch("/api/autosave", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: wf }),
      }).catch(() => {});
    } catch {}
  },

  loadAutoSave: async () => {
    // localStorage 먼저, 없으면 서버
    try {
      const local = localStorage.getItem("tf_autosave");
      if (local) {
        const data = JSON.parse(local);
        get().loadWorkflowJSON(data);
        set({ workflowName: data.name || "복구된 워크플로우", dirty: true });
        return true;
      }
      const res = await fetch("/api/autosave");
      const { data } = await res.json();
      if (data) {
        get().loadWorkflowJSON(data);
        set({ workflowName: data.name || "복구된 워크플로우", dirty: true });
        return true;
      }
    } catch {}
    return false;
  },

  newWorkflow: () =>
    set({
      nodes: [], edges: [], selectedNodeId: null,
      workflowId: null, workflowName: "새 워크플로우", workflowDescription: "",
      dirty: false, executionStatus: "idle",
    }),

  /* ── 워크플로우 매니저 ─────────────── */
  managerOpen: false,
  setManagerOpen: (open) => set({ managerOpen: open }),

  /* ── 채팅 ───────────────────────────── */
  chatMessages: [],
  addChatMessage: (msg) =>
    set((s) => ({
      chatMessages: [
        ...s.chatMessages,
        { ...msg, id: msg.id || `msg_${Date.now()}`, timestamp: Date.now() },
      ],
    })),
  updateChatMessage: (id, updates) =>
    set((s) => ({
      chatMessages: s.chatMessages.map((m) =>
        m.id === id ? { ...m, ...updates } : m
      ),
    })),
  clearChat: () => set({ chatMessages: [] }),

  /* ── 사이드바 ──────────────────────── */
  paletteOpen: true,
  propertiesOpen: true,
  togglePalette: () => set((s) => ({ paletteOpen: !s.paletteOpen })),
  toggleProperties: () => set((s) => ({ propertiesOpen: !s.propertiesOpen })),
}));
