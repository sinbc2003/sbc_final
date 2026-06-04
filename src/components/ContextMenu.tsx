import { useCallback, useEffect, useRef } from "react";
import {
  Copy, Trash2, Scissors, ClipboardPaste, SquareDashedMousePointer,
  AlignLeft, AlignCenter, Play, FileText,
} from "lucide-react";
import { useStore } from "../store";

export interface ContextMenuState {
  x: number;
  y: number;
  type: "pane" | "node" | "edge" | "selection";
  nodeId?: string;
  edgeId?: string;
}

interface Props {
  menu: ContextMenuState;
  onClose: () => void;
}

export function ContextMenu({ menu, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  const nodes = useStore((s) => s.nodes);
  const edges = useStore((s) => s.edges);
  const deleteSelected = useStore((s) => s.deleteSelected);
  const selectNode = useStore((s) => s.selectNode);
  const addNode = useStore((s) => s.addNode);
  const nodeDefinitions = useStore((s) => s.nodeDefinitions);
  const runWorkflow = useStore((s) => s.runWorkflow);
  const updateNodeParams = useStore((s) => s.updateNodeParams);

  const selectedCount = nodes.filter((n) => n.selected).length;

  // 밖 클릭/ESC로 닫기
  useEffect(() => {
    const handleClick = () => onClose();
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("click", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  // 메뉴가 화면 밖으로 나가지 않게
  useEffect(() => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
      ref.current.style.left = `${menu.x - rect.width}px`;
    }
    if (rect.bottom > window.innerHeight) {
      ref.current.style.top = `${menu.y - rect.height}px`;
    }
  }, [menu.x, menu.y]);

  const action = useCallback((fn: () => void) => {
    fn();
    onClose();
  }, [onClose]);

  // 노드 복제
  const duplicateNode = useCallback(() => {
    if (!menu.nodeId) return;
    const node = nodes.find((n) => n.id === menu.nodeId);
    if (!node) return;
    const defId = (node.data as any).definitionId;
    addNode(defId, { x: node.position.x + 50, y: node.position.y + 50 });
    // 파라미터 복사
    const newNodes = useStore.getState().nodes;
    const newNode = newNodes[newNodes.length - 1];
    if (newNode) {
      updateNodeParams(newNode.id, { ...(node.data as any).paramValues });
    }
  }, [menu.nodeId, nodes, addNode, updateNodeParams]);

  // 전체 선택
  const selectAll = useCallback(() => {
    const changes = nodes.map((n) => ({ id: n.id, type: "select" as const, selected: true }));
    useStore.getState().onNodesChange(changes);
  }, [nodes]);

  // 선택된 노드 삭제
  const deleteNodes = useCallback(() => {
    if (menu.nodeId) {
      selectNode(menu.nodeId);
      // 선택 후 삭제
      setTimeout(() => {
        const changes = [{ id: menu.nodeId!, type: "select" as const, selected: true }];
        useStore.getState().onNodesChange(changes);
        deleteSelected();
      }, 0);
    } else {
      deleteSelected();
    }
  }, [menu.nodeId, selectNode, deleteSelected]);

  const items: { label: string; icon: any; action: () => void; danger?: boolean; divider?: boolean; disabled?: boolean }[] = [];

  if (menu.type === "node") {
    items.push(
      { label: "복제", icon: Copy, action: duplicateNode },
      { label: "삭제", icon: Trash2, action: deleteNodes, danger: true },
      { label: "", icon: null, action: () => {}, divider: true },
      { label: "실행", icon: Play, action: () => runWorkflow() },
    );
  } else if (menu.type === "selection") {
    items.push(
      { label: `선택된 ${selectedCount}개 삭제`, icon: Trash2, action: deleteNodes, danger: true },
      { label: "", icon: null, action: () => {}, divider: true },
      { label: "실행", icon: Play, action: () => runWorkflow() },
    );
  } else if (menu.type === "edge") {
    items.push(
      { label: "연결 삭제", icon: Scissors, action: () => {
        if (menu.edgeId) {
          useStore.getState().onEdgesChange([{ id: menu.edgeId, type: "remove" }]);
        }
      }, danger: true },
    );
  } else {
    // 빈 캔버스 우클릭
    items.push(
      { label: "전체 선택", icon: SquareDashedMousePointer, action: selectAll },
      { label: "실행", icon: Play, action: () => runWorkflow(), disabled: nodes.length === 0 },
      { label: "", icon: null, action: () => {}, divider: true },
      { label: "파일 입력 추가", icon: FileText, action: () => addNode("file_input", { x: menu.x, y: menu.y }) },
      { label: "텍스트 입력 추가", icon: AlignLeft, action: () => addNode("text_input", { x: menu.x, y: menu.y }) },
      { label: "LLM 생성 추가", icon: AlignCenter, action: () => addNode("llm_generate", { x: menu.x, y: menu.y }) },
    );
  }

  return (
    <div
      ref={ref}
      className="fixed z-[200] bg-white rounded-lg shadow-xl border border-gray-200 py-1 min-w-[180px] select-none"
      style={{ left: menu.x, top: menu.y }}
      onClick={(e) => e.stopPropagation()}
    >
      {items.map((item, i) => {
        if (item.divider) {
          return <div key={i} className="h-px bg-gray-100 my-1" />;
        }
        const Icon = item.icon;
        return (
          <button
            key={i}
            onClick={() => action(item.action)}
            disabled={item.disabled}
            className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-[12px] text-left transition-colors
              ${item.danger ? "text-red-600 hover:bg-red-50" : "text-gray-700 hover:bg-gray-50"}
              ${item.disabled ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            {Icon && <Icon size={13} className="flex-shrink-0" />}
            <span>{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}
