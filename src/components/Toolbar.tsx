import { useEffect, useRef, useCallback, useState } from "react";
import {
  Play, Save, FolderOpen, FilePlus,
  PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen,
  Settings, Loader2, CheckCircle2, AlertCircle, Workflow,
  ChevronDown, Home,
} from "lucide-react";
import { useStore } from "../store";

export function Toolbar({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const mode = useStore((s) => s.mode);
  const setMode = useStore((s) => s.setMode);
  const executionStatus = useStore((s) => s.executionStatus);
  const runWorkflow = useStore((s) => s.runWorkflow);
  const nodes = useStore((s) => s.nodes);
  const paletteOpen = useStore((s) => s.paletteOpen);
  const propertiesOpen = useStore((s) => s.propertiesOpen);
  const togglePalette = useStore((s) => s.togglePalette);
  const toggleProperties = useStore((s) => s.toggleProperties);
  const saveWorkflow = useStore((s) => s.saveWorkflow);
  const saveAsWorkflow = useStore((s) => s.saveAsWorkflow);
  const autoSave = useStore((s) => s.autoSave);
  const newWorkflow = useStore((s) => s.newWorkflow);
  const workflowName = useStore((s) => s.workflowName);
  const dirty = useStore((s) => s.dirty);
  const workflowId = useStore((s) => s.workflowId);

  const isRunning = executionStatus === "running";
  const hasNodes = nodes.length > 0;

  // 자동저장 (30초 간격, 변경 있을 때만)
  const autoSaveTimer = useRef<ReturnType<typeof setInterval>>();
  useEffect(() => {
    autoSaveTimer.current = setInterval(() => {
      const s = useStore.getState();
      if (s.dirty && s.nodes.length > 0) s.autoSave();
    }, 30_000);
    return () => clearInterval(autoSaveTimer.current);
  }, []);

  // Ctrl+S 저장 — 마운트 시점 클로저(workflowId=null)를 캡처하면 첫 저장 후에도
  // 매번 이름 프롬프트가 뜨고 새 워크플로우가 중복 생성됨. 최신 상태를 직접 조회.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        const s = useStore.getState();
        if (s.mode && s.mode !== "design") return;  // 설계 모드에서만
        if (s.workflowId) {
          s.saveWorkflow();
        } else if (s.nodes.length > 0) {
          const name = prompt("워크플로우 이름:", s.workflowName);
          if (name) s.saveAsWorkflow(name);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // 저장 메뉴
  const [saveMenuOpen, setSaveMenuOpen] = useState(false);

  const handleSave = useCallback(async () => {
    if (workflowId) {
      await saveWorkflow();
    } else {
      const name = prompt("워크플로우 이름:", workflowName);
      if (name) await saveAsWorkflow(name);
    }
  }, [workflowId, workflowName, saveWorkflow, saveAsWorkflow]);

  // 현재 워크플로우를 홈 화면 카드(프리셋)로 등록 — 백엔드 route는 있었으나
  // UI 진입점이 없었음. 저장 안 된 상태면 먼저 저장하도록 안내.
  const handleRegisterPreset = useCallback(async () => {
    setSaveMenuOpen(false);
    let wid = useStore.getState().workflowId;
    if (!wid) {
      const name = prompt("먼저 워크플로우를 저장합니다. 이름:", workflowName);
      if (!name) return;
      await saveAsWorkflow(name);
      wid = useStore.getState().workflowId;
    } else if (useStore.getState().dirty) {
      await saveWorkflow();
    }
    if (!wid) return;
    try {
      const r = await fetch(`/api/workflows/${wid}/preset`, { method: "POST" });
      alert(r.ok ? "홈 화면에 카드로 등록되었습니다." : "등록에 실패했습니다.");
    } catch {
      alert("등록에 실패했습니다.");
    }
  }, [workflowName, saveAsWorkflow, saveWorkflow]);

  const handleSaveAs = useCallback(async () => {
    const name = prompt("새 이름으로 저장:", workflowName);
    if (name) await saveAsWorkflow(name);
    setSaveMenuOpen(false);
  }, [workflowName, saveAsWorkflow]);

  const isDesign = mode === "design";

  return (
    <div className="h-11 bg-white border-b border-tf-border flex items-center px-3 gap-1.5 flex-shrink-0">
      {/* 로고 */}
      <button onClick={() => setMode("home")} className="flex items-center gap-2 mr-2 hover:opacity-80 transition-opacity">
        <div className="w-6 h-6 rounded bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center">
          <Workflow size={14} className="text-white" />
        </div>
        <span className="text-[13px] font-bold text-gray-800">TeacherFlow</span>
      </button>

      {/* 설계 모드 전용 도구 */}
      {isDesign && (
        <>
          <div className="w-px h-5 bg-gray-200 mx-1" />

          <button onClick={togglePalette} title="도구 상자"
            className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors">
            {paletteOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
          </button>

          <button onClick={() => {
              const s = useStore.getState();
              if (s.dirty && s.nodes.length > 0 &&
                  !window.confirm("저장하지 않은 변경이 있습니다. 새 워크플로우를 시작할까요?")) return;
              newWorkflow();
            }} title="새 워크플로우"
            className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors">
            <FilePlus size={16} />
          </button>

          {/* 저장 (드롭다운) */}
          <div className="relative">
            <div className="flex">
              <button onClick={handleSave} disabled={!hasNodes} title="저장 (Ctrl+S)"
                className="p-1.5 rounded-l hover:bg-gray-100 text-gray-500 hover:text-gray-700
                  disabled:opacity-30 transition-colors">
                <Save size={16} />
              </button>
              <button onClick={() => setSaveMenuOpen(!saveMenuOpen)}
                className="px-0.5 rounded-r hover:bg-gray-100 text-gray-400 transition-colors">
                <ChevronDown size={12} />
              </button>
            </div>
            {saveMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setSaveMenuOpen(false)} />
                <div className="absolute left-0 top-8 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-40">
                  <button onClick={handleSave}
                    className="block w-full text-left px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-50">
                    저장 (Ctrl+S)
                  </button>
                  <button onClick={handleSaveAs}
                    className="block w-full text-left px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-50">
                    다른 이름으로 저장
                  </button>
                  <div className="h-px bg-gray-100 my-1" />
                  <button onClick={handleRegisterPreset}
                    className="block w-full text-left px-3 py-1.5 text-[12px] text-gray-600 hover:bg-gray-50">
                    홈 카드로 등록
                  </button>
                </div>
              </>
            )}
          </div>

          <button onClick={() => setMode("manager")} title="워크플로우 관리"
            className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors">
            <FolderOpen size={16} />
          </button>

          <div className="w-px h-5 bg-gray-200 mx-1" />

          {/* 실행 */}
          <button
            onClick={isRunning ? undefined : runWorkflow}
            disabled={!hasNodes || isRunning}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-semibold transition-all
              ${isRunning ? "bg-amber-50 text-amber-600 cursor-wait"
                : hasNodes ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100 active:scale-[0.97]"
                : "bg-gray-50 text-gray-400 cursor-not-allowed"}`}
          >
            {isRunning ? <><Loader2 size={13} className="animate-spin" /> 실행 중...</>
              : executionStatus === "done" ? <><CheckCircle2 size={13} /> 재실행</>
              : executionStatus === "error" ? <><AlertCircle size={13} className="text-red-500" /> 재시도</>
              : <><Play size={13} /> 실행</>}
          </button>

          <div className="w-px h-5 bg-gray-200 mx-1" />

          {/* 워크플로우 이름 */}
          <div className="flex items-center gap-1 min-w-0 mx-1 flex-1">
            <span className="text-[12px] text-gray-600 truncate">{workflowName}</span>
            {dirty && <span className="text-[10px] text-amber-500 flex-shrink-0">●</span>}
            {workflowId && !dirty && (
              <span className="text-[9px] text-emerald-500 flex-shrink-0">저장됨</span>
            )}
          </div>
        </>
      )}

      {!isDesign && <div className="flex-1" />}

      {/* 모드 토글 (4탭) */}
      <div className="flex bg-gray-100 rounded p-0.5">
        {([["home", "홈"], ["design", "설계"], ["chat", "채팅"], ["manager", "관리"]] as const).map(([m, label]) => (
          <button key={m} onClick={() => setMode(m)}
            className={`px-3 py-1 rounded text-[11px] font-semibold transition-all ${
              mode === m ? "bg-white text-gray-800 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="w-px h-5 bg-gray-200 mx-1" />

      {isDesign && (
        <button onClick={toggleProperties} title="속성 패널"
          className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors">
          {propertiesOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
        </button>
      )}
      <button onClick={onOpenSettings} title="설정"
        className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700 transition-colors">
        <Settings size={16} />
      </button>
    </div>
  );
}
