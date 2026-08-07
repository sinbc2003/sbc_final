import { useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Toolbar } from "./Toolbar";
import { NodePalette } from "./NodePalette";
import { FlowCanvas } from "./FlowCanvas";
import { PropertiesPanel } from "./PropertiesPanel";
import { StatusBar } from "./StatusBar";
import { ChatMode } from "./ChatMode";
import { HomeScreen } from "./HomeScreen";
import { WorkflowManagerPage } from "./WorkflowManagerPage";
import { ExecutionPanel } from "./ExecutionPanel";
import { SettingsModal } from "./SettingsModal";
import { TaskRunner } from "./TaskRunner";
import { Toast } from "./Toast";
import { useStore } from "../store";

export function Layout() {
  const mode = useStore((s) => s.mode);
  const runnerWorkflowId = useStore((s) => s.runnerWorkflowId);
  const closeRunner = useStore((s) => s.closeRunner);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Toolbar onOpenSettings={() => setSettingsOpen(true)} />

      <div className="flex-1 flex overflow-hidden">
        {/* 실행 화면은 모드보다 우선 — 관리 화면의 '실행'에서도 같은 화면을 쓴다.
            닫으면 원래 보던 모드로 돌아간다. */}
        {runnerWorkflowId ? (
          <TaskRunner presetId={runnerWorkflowId} onBack={closeRunner} />
        ) : mode === "home" ? (
          <HomeScreen />
        ) : mode === "design" ? (
          <>
            <NodePalette />
            <div className="flex-1 flex flex-col overflow-hidden">
              <ReactFlowProvider>
                <FlowCanvas />
              </ReactFlowProvider>
              <ExecutionPanel />
            </div>
            <PropertiesPanel />
          </>
        ) : mode === "manager" ? (
          <WorkflowManagerPage />
        ) : (
          <ChatMode />
        )}
      </div>

      <StatusBar />
      <Toast />

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
