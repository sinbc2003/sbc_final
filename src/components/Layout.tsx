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
import { useStore } from "../store";

export function Layout() {
  const mode = useStore((s) => s.mode);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <Toolbar onOpenSettings={() => setSettingsOpen(true)} />

      <div className="flex-1 flex overflow-hidden">
        {mode === "home" ? (
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

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
