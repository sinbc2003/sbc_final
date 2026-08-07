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

/* ── 실행취소 히스토리 ────────────────────────────
   설계·편집 상태(nodes/edges/workflowName)만 추적한다. 실행 상태·로그·
   패널 열림 등은 되돌릴 대상이 아니다.
   zundo(temporal 미들웨어) 대신 직접 구현: zustand가 이 프로젝트의 직접
   의존성이 아니라 @xyflow/react의 전이 의존성이라, 미들웨어 추가는 버전
   결합 위험이 크다. 필요한 동작(스냅샷·상한·드래그 병합)은 60줄이면 된다. */

interface HistorySnapshot {
  nodes: Node<FlowNodeData>[];
  edges: Edge[];
  workflowName: string;
}

const HISTORY_LIMIT = 50;
const PARAM_COALESCE_MS = 800; // 같은 파라미터 연속 입력은 한 단계로 묶는다

// 드래그 시작 직전 스냅샷(모듈 지역 — 되돌릴 상태가 아니라 기록 도구다)
let _dragSnapshot: HistorySnapshot | null = null;
let _lastParamEdit: { key: string; at: number } | null = null;

function snapshotOf(s: { nodes: Node<FlowNodeData>[]; edges: Edge[]; workflowName: string }): HistorySnapshot {
  return { nodes: s.nodes, edges: s.edges, workflowName: s.workflowName };
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

  // 실행취소 / 다시실행
  history: HistorySnapshot[];
  future: HistorySnapshot[];
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;

  // 노드 조작
  addNode: (defId: string, position: { x: number; y: number }) => void;
  addFileNode: (position: { x: number; y: number }, filePath: string, fileName: string) => string | null;
  deleteSelected: () => void;
  /** recordHistory=false: 직전 동작(노드 복제 등)의 일부라 별도 undo 단계로 만들지 않는다 */
  updateNodeParams: (nodeId: string, paramValues: Record<string, any>, recordHistory?: boolean) => void;

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
  currentRunId: string | null;
  cancelWorkflow: () => Promise<void>;

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

  // 실행 화면(TaskRunner) — 홈 카드·워크플로우 카드·실행 기록 어디서든 연다
  runnerWorkflowId: string | null;
  openRunner: (workflowId: string) => void;
  closeRunner: () => void;

  // 토스트 (연결 실패 사유 등 짧은 피드백)
  toast: { id: number; message: string; kind: "info" | "warn" | "error" } | null;
  showToast: (message: string, kind?: "info" | "warn" | "error") => void;
  dismissToast: () => void;

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

  /* ── 실행취소 히스토리 ─────────────── */
  history: [],
  future: [],

  pushHistory: () =>
    set((s) => ({
      history: [...s.history, snapshotOf(s)].slice(-HISTORY_LIMIT),
      future: [], // 새 편집이 생기면 redo 스택은 버린다
    })),

  undo: () =>
    set((s) => {
      if (s.history.length === 0) return s;
      const prev = s.history[s.history.length - 1];
      return {
        nodes: prev.nodes, edges: prev.edges, workflowName: prev.workflowName,
        history: s.history.slice(0, -1),
        future: [...s.future, snapshotOf(s)].slice(-HISTORY_LIMIT),
        selectedNodeId: prev.nodes.some((n) => n.id === s.selectedNodeId) ? s.selectedNodeId : null,
        dirty: true,
      };
    }),

  redo: () =>
    set((s) => {
      if (s.future.length === 0) return s;
      const next = s.future[s.future.length - 1];
      return {
        nodes: next.nodes, edges: next.edges, workflowName: next.workflowName,
        future: s.future.slice(0, -1),
        history: [...s.history, snapshotOf(s)].slice(-HISTORY_LIMIT),
        selectedNodeId: next.nodes.some((n) => n.id === s.selectedNodeId) ? s.selectedNodeId : null,
        dirty: true,
      };
    }),

  /* ── React Flow ────────────────────── */
  nodes: [],
  edges: [],

  onNodesChange: (changes) => {
    // 드래그 중(position, dragging=true)엔 기록하지 않고 **드래그 시작 직전**
    // 상태를 잡아두었다가 드래그가 끝날 때 한 단계로 커밋한다.
    // (끝나고 잡으면 이미 이동한 위치라 undo가 무의미해진다.)
    const hasRemove = changes.some((c) => c.type === "remove");
    const dragStart = changes.some((c) => c.type === "position" && (c as any).dragging === true);
    const dragEnd = changes.some((c) => c.type === "position" && (c as any).dragging === false);

    if (hasRemove) get().pushHistory();
    if (dragStart && !_dragSnapshot) _dragSnapshot = snapshotOf(get());
    if (dragEnd && _dragSnapshot) {
      const snap = _dragSnapshot;
      _dragSnapshot = null;
      set((s) => ({ history: [...s.history, snap].slice(-HISTORY_LIMIT), future: [] }));
    }
    set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) as Node<FlowNodeData>[], dirty: true }));
  },

  onEdgesChange: (changes) => {
    if (changes.some((c) => c.type === "remove")) get().pushHistory();
    set((s) => ({ edges: applyEdgeChanges(changes, s.edges), dirty: true }));
  },

  onConnect: (connection) => {
    const { nodes } = get();
    get().pushHistory();
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

    // 입력 포트는 하나만 받는다. 예전엔 여러 개가 붙은 뒤 실행 시점에
    // 마지막 값이 조용히 덮어써졌다 → 기존 연결을 교체하고 이유를 알린다.
    const replaced = get().edges.some(
      (e) => e.target === target && e.targetHandle === targetHandle
    );
    set((s) => ({
      edges: addEdge(
        { source: source!, sourceHandle, target: target!, targetHandle, type: "smoothstep", animated: false },
        s.edges.filter((e) => !(e.target === target && e.targetHandle === targetHandle))
      ),
      dirty: true,
    }));
    if (replaced) {
      get().showToast(
        `'${targetHandle}' 입력은 하나만 연결할 수 있어 기존 연결을 교체했습니다.`,
        "info"
      );
    }
  },

  /* ── 노드 조작 ─────────────────────── */
  addNode: (defId, position) => {
    const def = get().nodeDefinitions.find((d) => d.id === defId);
    if (!def) return;
    get().pushHistory();
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
    get().pushHistory();
    const id = nextId();
    const data = definitionToFlowData(def);
    data.paramValues.path = filePath;
    data.label = `📄 ${fileName}`;
    const newNode: Node<FlowNodeData> = { id, type: "custom", position, data };
    set((s) => ({ nodes: [...s.nodes, newNode], dirty: true, selectedNodeId: id }));
    return id;
  },

  deleteSelected: () => {
    const selectedIds = new Set(get().nodes.filter((n) => n.selected).map((n) => n.id));
    if (selectedIds.size === 0) return;
    // Backspace 오삭제가 비가역이던 지점 — 지우기 전에 스냅샷.
    get().pushHistory();
    set((s) => ({
      nodes: s.nodes.filter((n) => !selectedIds.has(n.id)),
      edges: s.edges.filter(
        (e) => !selectedIds.has(e.source) && !selectedIds.has(e.target)
      ),
      selectedNodeId:
        s.selectedNodeId && selectedIds.has(s.selectedNodeId)
          ? null
          : s.selectedNodeId,
      dirty: true,
    }));
  },

  updateNodeParams: (nodeId, paramValues, recordHistory = true) => {
    // 텍스트 파라미터는 키 입력마다 호출된다 → 같은 필드 연속 입력은
    // 한 단계로 묶어 히스토리가 글자 수만큼 쌓이는 것을 막는다.
    const key = `${nodeId}:${Object.keys(paramValues).join(",")}`;
    const now = Date.now();
    if (recordHistory && (!_lastParamEdit || _lastParamEdit.key !== key ||
        now - _lastParamEdit.at > PARAM_COALESCE_MS)) {
      get().pushHistory();
    }
    _lastParamEdit = { key, at: now };
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, paramValues: { ...n.data.paramValues, ...paramValues } } }
          : n
      ),
      dirty: true,
    }));
  },

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
    set({ executionLogs: [], executionOutputs: {}, executionPanelOpen: true, currentRunId: null });

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

          if (evt.event === "run_started") {
            // 엔진이 발급한 실행 ID — '중단' 버튼이 이 ID로 취소를 건다.
            set({ currentRunId: evt.run_id || null });
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
            set({ executionOutputs: evt.outputs || {}, currentRunId: null });
            setExecutionStatus(evt.cancelled ? "cancelled" : evt.success ? "done" : "error");
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
              currentRunId: null,
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
        currentRunId: null,
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

  /* 실행 중단 — 엔진은 다음 노드 경계에서 멈춘다(협조적 취소).
     현재 노드가 끝나야 반응하므로 '중단 요청' 로그를 즉시 남긴다. */
  currentRunId: null,
  cancelWorkflow: async () => {
    const runId = get().currentRunId;
    if (!runId || get().executionStatus !== "running") return;
    set((s) => ({
      executionLogs: [
        ...s.executionLogs,
        {
          nodeId: "SYSTEM",
          nodeName: "시스템",
          message: "중단 요청 — 진행 중인 단계가 끝나면 멈춥니다.",
          timestamp: Date.now(),
        },
      ],
    }));
    try {
      await fetch(`/api/run/${runId}/cancel`, { method: "POST" });
    } catch { /* 이미 끝난 실행 */ }
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
    // 다른 워크플로우를 불러오면 히스토리는 리셋 — 되돌리기가 이전 워크플로우로
    // 넘어가면 두 워크플로우가 섞인다.
    _dragSnapshot = null;
    _lastParamEdit = null;
    set({
      nodes: newNodes, edges: newEdges, selectedNodeId: null,
      workflowId: meta?.id ?? wf.id ?? null,
      workflowName: meta?.name ?? wf.name ?? "불러온 워크플로우",
      workflowDescription: meta?.description ?? wf.description ?? "",
      dirty: false, history: [], future: [],
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

  newWorkflow: () => {
    _dragSnapshot = null;
    _lastParamEdit = null;
    set({
      nodes: [], edges: [], selectedNodeId: null,
      workflowId: null, workflowName: "새 워크플로우", workflowDescription: "",
      dirty: false, executionStatus: "idle", history: [], future: [],
    });
  },

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

  /* ── 실행 화면 ──────────────────────── */
  runnerWorkflowId: null,
  openRunner: (workflowId) => set({ runnerWorkflowId: workflowId }),
  closeRunner: () => set({ runnerWorkflowId: null }),

  /* ── 토스트 ─────────────────────────── */
  toast: null,
  // id를 새로 발급해 같은 문구를 연달아 띄워도 표시가 갱신되게 한다
  showToast: (message, kind = "info") => set({ toast: { id: Date.now(), message, kind } }),
  dismissToast: () => set({ toast: null }),

  /* ── 사이드바 ──────────────────────── */
  paletteOpen: true,
  propertiesOpen: true,
  togglePalette: () => set((s) => ({ paletteOpen: !s.paletteOpen })),
  toggleProperties: () => set((s) => ({ propertiesOpen: !s.propertiesOpen })),
}));
