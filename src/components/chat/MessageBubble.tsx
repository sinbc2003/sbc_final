import { Bot, User, Monitor, CheckCircle, XCircle, FileCheck, FolderOpen } from "lucide-react";
import { ChatWorkflowPreview } from "../ChatWorkflowPreview";
import type { ChatMessage } from "../../types";

export function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";

  const openFile = async (filePath: string) => {
    try {
      await fetch("/api/files/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePath }),
      });
    } catch { /* ignore */ }
  };

  const openFolder = async (filePath: string) => {
    const dir = filePath.replace(/[/\\][^/\\]+$/, "");
    try {
      await fetch("/api/files/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: dir }),
      });
    } catch { /* ignore */ }
  };

  return (
    <div className={`flex gap-2.5 ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0
        ${isUser ? "bg-amber-50" : "bg-gray-100"}`}>
        {isUser ? <User size={14} className="text-amber-600" /> : <Bot size={14} className="text-gray-600" />}
      </div>
      <div className={`max-w-[80%] ${isUser ? "" : ""}`}>
        <div className={`rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap
          ${isUser ? "bg-amber-50 text-gray-800 rounded-tr-sm" : "bg-gray-50 text-gray-700 rounded-tl-sm border border-gray-200"}`}>
          {msg.content}
          {msg.isStreaming && (
            <span className="inline-block w-1.5 h-4 bg-blue-400 ml-0.5 animate-pulse rounded-sm align-text-bottom" />
          )}
        </div>
        {msg.formAssist && msg.formFile && (
          <div className="mt-2 bg-emerald-50 border border-emerald-200 rounded-lg p-2.5 text-[12px]">
            <div className="font-bold text-emerald-700 mb-1.5 flex items-center gap-1">
              <FileCheck size={12} className="text-emerald-600" />
              양식 채우기 완료
            </div>
            <div className="flex gap-2 mt-1.5">
              <button
                onClick={() => openFile(msg.formFile!)}
                className="flex items-center gap-1 px-2.5 py-1 bg-emerald-600 text-white rounded text-[11px] hover:bg-emerald-700 transition-colors"
              >
                <FileCheck size={11} /> 파일 열기
              </button>
              <button
                onClick={() => openFolder(msg.formFile!)}
                className="flex items-center gap-1 px-2.5 py-1 bg-gray-100 text-gray-600 rounded text-[11px] hover:bg-gray-200 transition-colors"
              >
                <FolderOpen size={11} /> 폴더 열기
              </button>
            </div>
          </div>
        )}
        {msg.workflowJson && (
          <ChatWorkflowPreview workflow={msg.workflowJson} workflowId={msg.workflowId} />
        )}
        {msg.liveResults && msg.liveResults.length > 0 && (
          <div className="mt-2 bg-white border border-gray-200 rounded-lg p-2.5 text-[12px]">
            <div className="font-bold text-gray-600 mb-1.5 flex items-center gap-1">
              <Monitor size={12} className="text-blue-500" />
              문서 제어 실행 결과 — {msg.liveSummary}
            </div>
            {msg.liveResults.map((r, i) => (
              <div key={i} className="flex items-center gap-1.5 py-0.5">
                {r.success
                  ? <CheckCircle size={11} className="text-emerald-500" />
                  : <XCircle size={11} className="text-red-500" />}
                <span className={r.success ? "text-gray-600" : "text-red-600"}>
                  {r.action}: {r.message}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
