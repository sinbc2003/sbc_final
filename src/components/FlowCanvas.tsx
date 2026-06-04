import { useCallback, useRef, useEffect, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useReactFlow,
  type Connection,
  type Edge,
  type IsValidConnection,
  type ReactFlowInstance,
  SelectionMode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { CustomNode } from "./nodes/CustomNode";
import { CustomEdge } from "./nodes/CustomEdge";
import { ContextMenu, type ContextMenuState } from "./ContextMenu";
import { useStore } from "../store";
import type { FlowNodeData } from "../types";
import { getPortColor } from "../constants";

const nodeTypes = { custom: CustomNode };
const edgeTypes = { smoothstep: CustomEdge };

const defaultEdgeOptions = {
  type: "smoothstep" as const,
};

export function FlowCanvas() {
  const reactFlowRef = useRef<HTMLDivElement>(null);
  const rfInstance = useRef<ReactFlowInstance | null>(null);
  const hasFitView = useRef(false);

  const nodes = useStore((s) => s.nodes);
  const edges = useStore((s) => s.edges);
  const onNodesChange = useStore((s) => s.onNodesChange);
  const onEdgesChange = useStore((s) => s.onEdgesChange);
  const onConnect = useStore((s) => s.onConnect);
  const addNode = useStore((s) => s.addNode);
  const addFileNode = useStore((s) => s.addFileNode);
  const selectNode = useStore((s) => s.selectNode);
  const deleteSelected = useStore((s) => s.deleteSelected);
  const [fileDragOver, setFileDragOver] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  /* ── 초기 fitView (한 번만, 로드된 노드가 있을 때) ── */
  const onInit = useCallback((instance: any) => {
    rfInstance.current = instance;
  }, []);

  useEffect(() => {
    if (!hasFitView.current && rfInstance.current && nodes.length > 0) {
      rfInstance.current.fitView({ padding: 0.3 });
      hasFitView.current = true;
    }
  }, [nodes.length]);

  /* ── 연결 유효성 검사 (양방향 대응) ─────────── */
  const isValidConnection: IsValidConnection = useCallback(
    (connection: Edge | Connection) => {
      const { source, target, sourceHandle, targetHandle } = connection;
      if (!source || !target || source === target) return false;

      const sourceNode = nodes.find((n) => n.id === source);
      const targetNode = nodes.find((n) => n.id === target);
      if (!sourceNode || !targetNode) return false;

      const srcData = sourceNode.data as FlowNodeData;
      const tgtData = targetNode.data as FlowNodeData;

      // 정방향: source의 output → target의 input
      let outPort = srcData.outputs.find((p) => p.name === sourceHandle);
      let inPort = tgtData.inputs.find((p) => p.name === targetHandle);

      // 역방향: source가 실제로 input이고 target이 output (드래그 방향 반대)
      if (!outPort || !inPort) {
        outPort = tgtData.outputs.find((p) => p.name === targetHandle);
        inPort = srcData.inputs.find((p) => p.name === sourceHandle);
      }

      if (!outPort || !inPort) return false;

      // 타입 호환성
      if (outPort.type === "any" || inPort.type === "any") return true;
      if (outPort.type !== inPort.type) return false;

      // file accept 검사
      if (outPort.type === "file" && inPort.accept?.length) {
        if (outPort.accept?.length) {
          const overlap = outPort.accept.filter((a) => inPort!.accept!.includes(a));
          return overlap.length > 0;
        }
      }

      return true;
    },
    [nodes]
  );

  /* ── 드래그 앤 드롭 ────────────────────────── */
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const isFile = e.dataTransfer.types.includes("Files");
    e.dataTransfer.dropEffect = isFile ? "copy" : "move";
    reactFlowRef.current?.classList.add("drop-target");
    if (isFile) setFileDragOver(true);
  }, []);

  const onDragLeave = useCallback(() => {
    reactFlowRef.current?.classList.remove("drop-target");
    setFileDragOver(false);
  }, []);

  const { screenToFlowPosition } = useReactFlow();

  const onDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      reactFlowRef.current?.classList.remove("drop-target");
      setFileDragOver(false);

      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });

      // 1) 노드 팔레트에서 드래그한 경우
      const defId = e.dataTransfer.getData("application/teacherflow-node");
      if (defId) {
        addNode(defId, position);
        return;
      }

      // 2) OS에서 파일을 드래그한 경우 → 파일 업로드 → file_input 노드 생성
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          const dropPos = { x: position.x + i * 40, y: position.y + i * 40 };

          try {
            const form = new FormData();
            form.append("file", file);
            const res = await fetch("/api/files/upload", { method: "POST", body: form });
            if (res.ok) {
              const data = await res.json();
              addFileNode(dropPos, data.path, data.name);
            }
          } catch {
            // 업로드 실패 시 로컬 경로로 시도
            addFileNode(dropPos, file.name, file.name);
          }
        }
      }
    },
    [addNode, addFileNode, screenToFlowPosition]
  );

  /* ── 노드 선택 ─────────────────────────────── */
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: any) => {
      selectNode(node.id);
    },
    [selectNode]
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  // 다중 선택 시 첫 번째 노드를 속성 패널에 표시
  const onSelectionChange = useCallback(({ nodes: selected }: { nodes: any[] }) => {
    if (selected.length === 1) {
      selectNode(selected[0].id);
    } else if (selected.length === 0) {
      selectNode(null);
    }
    // 2개 이상이면 selectedNodeId 유지 (마지막 클릭한 것)
  }, [selectNode]);

  /* ── 우클릭 컨텍스트 메뉴 ────────────────────── */
  const onNodeContextMenu = useCallback(
    (e: React.MouseEvent, node: any) => {
      e.preventDefault();
      const selectedCount = nodes.filter((n) => n.selected).length;
      setContextMenu({
        x: e.clientX, y: e.clientY,
        type: selectedCount > 1 ? "selection" : "node",
        nodeId: node.id,
      });
    },
    [nodes]
  );

  const onEdgeContextMenu = useCallback(
    (e: React.MouseEvent, edge: any) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, type: "edge", edgeId: edge.id });
    },
    []
  );

  const onPaneContextMenu = useCallback(
    (e: MouseEvent | React.MouseEvent) => {
      e.preventDefault();
      setContextMenu({ x: (e as any).clientX, y: (e as any).clientY, type: "pane" });
    },
    []
  );

  /* ── 키보드 ─────────────────────────────────── */
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Delete" || e.key === "Backspace") {
        deleteSelected();
      }
      // Ctrl+A 전체 선택
      if ((e.ctrlKey || e.metaKey) && e.key === "a") {
        e.preventDefault();
        const changes = nodes.map((n) => ({ id: n.id, type: "select" as const, selected: true }));
        useStore.getState().onNodesChange(changes);
      }
    },
    [deleteSelected, nodes]
  );

  /* ── 미니맵 색상 ────────────────────────────── */
  const nodeColor = useCallback((node: any) => {
    const data = node.data as FlowNodeData;
    return getPortColor(data?.outputs?.[0]?.type ?? "any");
  }, []);

  return (
    <div
      ref={reactFlowRef}
      className="flex-1 h-full relative"
      onKeyDown={onKeyDown}
      tabIndex={0}
    >
      {/* 파일 드래그 오버레이 */}
      {fileDragOver && (
        <div className="absolute inset-0 z-50 flex items-center justify-center pointer-events-none">
          <div className="bg-white/90 backdrop-blur-sm border-2 border-dashed border-amber-400 rounded-2xl px-8 py-6 shadow-lg text-center">
            <p className="text-[14px] font-bold text-amber-600">파일을 여기에 놓으세요</p>
            <p className="text-[11px] text-gray-500 mt-1">자동으로 파일 입력 노드가 생성됩니다</p>
          </div>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        isValidConnection={isValidConnection}
        onNodeClick={onNodeClick}
        onPaneClick={(e) => { onPaneClick(); setContextMenu(null); }}
        onSelectionChange={onSelectionChange}
        onNodeContextMenu={onNodeContextMenu}
        onEdgeContextMenu={onEdgeContextMenu}
        onPaneContextMenu={onPaneContextMenu}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onInit={onInit}
        onMoveStart={() => setContextMenu(null)}
        minZoom={0.1}
        maxZoom={2}
        selectionMode={SelectionMode.Partial}
        multiSelectionKeyCode="Shift"
        panOnScroll
        selectionOnDrag
        proOptions={{ hideAttribution: true }}
        connectionLineStyle={{
          stroke: "#e8a028",
          strokeWidth: 2.5,
          strokeDasharray: "5 3",
        }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#d4d4d4"
        />
        <Controls
          position="bottom-left"
          showInteractive={false}
          style={{ marginBottom: 40, marginLeft: 12 }}
        />
        <MiniMap
          position="bottom-right"
          nodeColor={nodeColor}
          style={{
            width: 160,
            height: 100,
            marginBottom: 40,
            marginRight: 12,
          }}
          pannable
          zoomable
        />
      </ReactFlow>
      {contextMenu && (
        <ContextMenu menu={contextMenu} onClose={() => setContextMenu(null)} />
      )}
    </div>
  );
}
