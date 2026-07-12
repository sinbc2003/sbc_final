import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Sparkles, Loader2, Upload, FileText, X, Monitor, Plug, ChevronDown, FileEdit, Cpu, Palette, MessageSquare } from "lucide-react";
import { useStore } from "../store";
import { MessageBubble } from "./chat/MessageBubble";
import { ActionReviewPanel } from "./chat/ActionReviewPanel";
import { describeAction } from "./chat/describeAction";

interface AppDoc {
  index: number;
  title: string;
  path: string;
}

export function ChatMode() {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<{ name: string; path: string }[]>([]);
  const [fileDragOver, setFileDragOver] = useState(false);
  const [liveMode, setLiveMode] = useState(false);
  const [liveApp, setLiveApp] = useState<string | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [detectedApps, setDetectedApps] = useState<Record<string, { running: boolean; connected: boolean }>>({});
  // 다중 문서 (앱별)
  const [appDocuments, setAppDocuments] = useState<Record<string, AppDoc[]>>({});
  const [selectedDocIndex, setSelectedDocIndex] = useState<Record<string, number>>({});
  const [docDropdownOpen, setDocDropdownOpen] = useState(false);
  const [pendingActions, setPendingActions] = useState<Array<{action: string; params: any; checked: boolean}> | null>(null);
  // 모델 선택
  const [models, setModels] = useState<{id: string; name: string; provider: string; available?: boolean}[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("openai/gpt-4.1-mini");
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  // 디자인 스킬 선택
  const [designSkills, setDesignSkills] = useState<{id: string; name: string}[]>([]);
  const [selectedDesign, setSelectedDesign] = useState<string>("default");
  const [designDropdownOpen, setDesignDropdownOpen] = useState(false);

  const messages = useStore((s) => s.chatMessages);
  const addMessage = useStore((s) => s.addChatMessage);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const liveModeRef = useRef(liveMode);
  liveModeRef.current = liveMode;
  const docDropdownRef = useRef<HTMLDivElement>(null);
  const modelDropdownRef = useRef<HTMLDivElement>(null);
  const designDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // 모델 목록 + 디자인 스킬 로드
  useEffect(() => {
    fetch("/api/models").then(r => r.json()).then((list: any[]) => {
      if (Array.isArray(list) && list.length > 0) {
        setModels(list);
        // 엔진 설정(local_model)의 활성 모델을 기본 선택 — 하드코딩 OpenAI
        // 기본값이 설정(default_provider=local)을 무시하고 429를 내던 문제 수정.
        const active = list.find(m => m.active);
        if (active) {
          setSelectedModel(active.id);
        } else if (!list.find(m => m.id === selectedModel)) {
          setSelectedModel(list[0].id);
        }
      }
    }).catch(() => {});
    fetch("/api/design-skills").then(r => r.json()).then((list: any[]) => {
      if (Array.isArray(list) && list.length > 0) setDesignSkills(list);
    }).catch(() => {});
  }, []);

  // 드롭다운 바깥 클릭 닫기
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (docDropdownRef.current && !docDropdownRef.current.contains(e.target as Node)) {
        setDocDropdownOpen(false);
      }
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false);
      }
      if (designDropdownRef.current && !designDropdownRef.current.contains(e.target as Node)) {
        setDesignDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // 라이브 앱 감지 + 문서 목록
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch("/api/live/detect", { signal: AbortSignal.timeout(3000) });
        if (!res.ok) return;
        const data = await res.json();
        if (data.error) return;

        // 모든 앱 감지 상태
        const detected: Record<string, { running: boolean; connected: boolean }> = {};
        for (const [key, app] of Object.entries(data) as [string, any][]) {
          detected[key] = {
            running: !!app.doc_name || app.connected,
            connected: !!app.connected,
          };
          // 모든 앱의 문서 목록 업데이트
          if (app.connected && app.documents && Array.isArray(app.documents)) {
            setAppDocuments((prev) => ({ ...prev, [key]: app.documents }));
            setSelectedDocIndex((prev) => {
              const cur = prev[key] ?? 0;
              return cur >= app.documents.length ? { ...prev, [key]: 0 } : prev;
            });
          } else if (!app.connected) {
            setAppDocuments((prev) => { const n = { ...prev }; delete n[key]; return n; });
          }
        }
        setDetectedApps(detected);

        // 활성 앱 자동 선택 (liveMode ON이면 사용자 선택 유지)
        setLiveApp((prev) => {
          if (prev && liveModeRef.current) return prev;
          if (prev && detected[prev]?.running) return prev;
          for (const key of Object.keys(detected)) {
            if (detected[key].connected) return key;
          }
          for (const key of Object.keys(detected)) {
            if (detected[key].running) return key;
          }
          return null;
        });
      } catch {}
    };
    check();
    const timer = setInterval(check, 10_000);
    return () => clearInterval(timer);
  }, []);

  // liveConnected 동기화
  useEffect(() => {
    setLiveConnected(liveApp ? detectedApps[liveApp]?.connected ?? false : false);
  }, [liveApp, detectedApps]);

  // 앱별 ���어 토글
  const handleAppToggle = useCallback(async (app: string) => {
    if (liveApp === app && liveMode) {
      setLiveMode(false);
      return;
    }
    setConnecting(true);
    try {
      const res = await fetch(`/api/live/connect/${app}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setLiveApp(app);
          setLiveConnected(true);
          setLiveMode(true);
          // 문서 목록 가져오기 (모든 앱)
          try {
            const docsRes = await fetch(`/api/live/documents/${app}`);
            if (docsRes.ok) {
              const docsData = await docsRes.json();
              setAppDocuments((prev) => ({ ...prev, [app]: docsData.documents || [] }));
            }
          } catch {}
          addMessage({ role: "assistant", content: `${appLabel[app] ?? app} 연결 완료 — ${data.message}` });
        } else {
          addMessage({ role: "assistant", content: `${appLabel[app] ?? app} 연결 실패: ${data.message || "알 수 없는 오류"}` });
        }
      } else {
        addMessage({ role: "assistant", content: `${appLabel[app] ?? app} 연결 실패 (서버 오류)` });
      }
    } catch {
      addMessage({ role: "assistant", content: `${appLabel[app] ?? app} 연결 실패 — 엔진 서버에 연결할 수 없습니다.` });
    }
    setConnecting(false);
  }, [liveApp, liveMode, addMessage]);

  // 수정 내역 반영
  const handleApplyActions = useCallback(async () => {
    if (!pendingActions || !liveApp) return;
    const selected = pendingActions.filter((a) => a.checked);
    if (selected.length === 0) { setPendingActions(null); return; }
    setSending(true);
    try {
      const res = await fetch("/api/live/execute-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          app_type: liveApp,
          actions: selected.map((a) => ({ action: a.action, params: a.params })),
        }),
      });
      const data = await res.json();
      addMessage({
        role: "assistant",
        content: `${selected.length}개 작업 반영 완료`,
        liveResults: data.results,
        liveSummary: data.summary,
      });
    } catch {
      addMessage({ role: "assistant", content: "실행 중 오류가 발생했습니다." });
    }
    setPendingActions(null);
    setSending(false);
  }, [pendingActions, liveApp, addMessage]);

  // HWP 문서 전환
  const switchDocument = useCallback(async (app: string, docIndex: number) => {
    setSelectedDocIndex((prev) => ({ ...prev, [app]: docIndex }));
    setDocDropdownOpen(false);
    try {
      if (app === "hwp") {
        await fetch(`/api/hwp/switch/${docIndex}`, { method: "POST" });
      } else {
        await fetch(`/api/live/documents/${app}/activate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ index: docIndex }),
        });
      }
    } catch {}
  }, []);

  // 파일 업로드
  const uploadFile = useCallback(async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/files/upload", { method: "POST", body: form });
      if (res.ok) {
        const data = await res.json();
        setAttachedFiles((prev) => [...prev, { name: data.name, path: data.path }]);
      }
    } catch {}
  }, []);

  // 파일 드래그&드롭
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.types.includes("Files")) setFileDragOver(true);
  }, []);
  const onDragLeave = useCallback(() => setFileDragOver(false), []);
  const onDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setFileDragOver(false);
    for (const file of Array.from(e.dataTransfer.files)) {
      await uploadFile(file);
    }
  }, [uploadFile]);

  // 파일 선택 (클릭)
  const onFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    for (const file of Array.from(e.target.files || [])) {
      await uploadFile(file);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [uploadFile]);

  const removeFile = useCallback((idx: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleSend = async () => {
    const text = input.trim();
    if ((!text && attachedFiles.length === 0) || sending) return;

    // 메시지 구성: 텍스트 + 첨부 파일 정보
    let userMsg = text;
    if (attachedFiles.length > 0) {
      const fileList = attachedFiles.map((f) => f.name).join(", ");
      userMsg = text
        ? `${text}\n\n[첨부 파일: ${fileList}]`
        : `[첨부 파일: ${fileList}]`;
    }

    addMessage({ role: "user", content: userMsg });
    setInput("");
    const filesToSend = [...attachedFiles];
    setAttachedFiles([]);
    setSending(true);

    try {
      const history = useStore.getState().chatMessages.map((m) => ({
        role: m.role, content: m.content,
      }));

      if (liveMode && liveApp) {
        // ── 라이브 문서 제어 모드 (LLM 토큰 스트리밍) ──
        const resp = await fetch("/api/chat/live/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            app_type: liveApp,
            history,
            doc_index: liveApp === "hwp" ? (selectedDocIndex["hwp"] ?? 0) : undefined,
            model: selectedModel,
            design_skill: selectedDesign !== "default" ? selectedDesign : undefined,
          }),
        });

        const reader = resp.body?.getReader();
        const decoder = new TextDecoder();
        let replyMsgId: string | null = null;
        let streamedText = "";
        const streamResults: { action: string; success: boolean; message: string }[] = [];
        let buffer = "";

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              try {
                const ev = JSON.parse(line.slice(6));
                if (ev.type === "thinking") {
                  // AI가 생각 시작 — 빈 메시지 버블 생성 (typing indicator)
                  replyMsgId = crypto.randomUUID();
                  streamedText = "";
                  addMessage({ role: "assistant", content: "···", id: replyMsgId, isStreaming: true });
                } else if (ev.type === "token") {
                  // LLM 토큰 수신 — 실시간 텍스트 누적
                  streamedText += ev.content;
                  if (replyMsgId) {
                    useStore.getState().updateChatMessage(replyMsgId, {
                      content: streamedText,
                      isStreaming: true,
                    });
                  }
                } else if (ev.type === "reply_done") {
                  // LLM 응답 완료 — 깔끔한 텍스트로 교체
                  if (replyMsgId) {
                    useStore.getState().updateChatMessage(replyMsgId, {
                      content: ev.content || streamedText,
                      isStreaming: false,
                    });
                  }
                } else if (ev.type === "reply") {
                  // 폴백: 스트리밍 없는 경우 (기존 호환)
                  if (!replyMsgId) {
                    replyMsgId = crypto.randomUUID();
                    addMessage({ role: "assistant", content: ev.content || "작업을 실행합니다...", id: replyMsgId });
                  }
                } else if (ev.type === "actions") {
                  // 액션 실행 시작 알림
                  if (replyMsgId) {
                    const cur = useStore.getState().chatMessages.find(m => m.id === replyMsgId);
                    if (cur) {
                      useStore.getState().updateChatMessage(replyMsgId, {
                        content: cur.content + `\n\n⏳ ${ev.count}개 작업 실행 중...`,
                      });
                    }
                  }
                } else if (ev.type === "result") {
                  streamResults.push({ action: ev.action, success: ev.success, message: ev.message });
                  const icon = ev.success ? "✓" : "✗";
                  const resultLine = `${icon} ${ev.action}: ${ev.message}`;
                  const currentMsg = useStore.getState().chatMessages.find(m => m.id === replyMsgId);
                  if (currentMsg && replyMsgId) {
                    // 첫 결과 시 "실행 중..." 줄을 교체
                    const base = currentMsg.content.replace(/\n\n⏳ \d+개 작업 실행 중\.\.\./, "");
                    const prevResults = streamResults.slice(0, -1).map(r =>
                      `${r.success ? "✓" : "✗"} ${r.action}: ${r.message}`
                    ).join("\n");
                    const allResults = prevResults ? prevResults + "\n" + resultLine : resultLine;
                    useStore.getState().updateChatMessage(replyMsgId, {
                      content: base + "\n\n" + allResults,
                    });
                  }
                } else if (ev.type === "done") {
                  const currentMsg = useStore.getState().chatMessages.find(m => m.id === replyMsgId);
                  if (currentMsg && replyMsgId) {
                    useStore.getState().updateChatMessage(replyMsgId, {
                      content: currentMsg.content + "\n\n" + ev.summary,
                      liveResults: streamResults,
                      liveSummary: ev.summary,
                      isStreaming: false,
                    });
                  }
                }
              } catch { /* skip parse errors */ }
            }
          }
        }
      } else {
        // ── 일반 워크플로우 모드 ──
        const thinkId = crypto.randomUUID();
        addMessage({ role: "assistant", content: "···", id: thinkId, isStreaming: true });
        let message = text;
        if (filesToSend.length > 0) {
          const filePaths = filesToSend.map((f) => f.path).join("\n");
          message = `${text}\n\n첨부된 파일 경로:\n${filePaths}`;
        }
        const resp = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, history, model: selectedModel }),
        });
        const data = await resp.json();
        useStore.getState().updateChatMessage(thinkId, {
          content: data.reply ?? "응답 없음",
          workflowId: data.workflow_id,
          workflowJson: data.workflow_json,
          formAssist: data.form_assist || false,
          formFile: data.file || null,
          isStreaming: false,
        });
      }
    } catch {
      addMessage({ role: "assistant", content: "엔진 서버에 연결할 수 없습니다." });
    } finally {
      setSending(false);
    }
  };

  const appLabel: Record<string, string> = { hwp: "한/글", excel: "Excel", ppt: "PPT", word: "Word" };
  const currentDocs = liveApp ? (appDocuments[liveApp] || []) : [];
  const currentDocIdx = liveApp ? (selectedDocIndex[liveApp] ?? 0) : 0;
  const selectedDoc = currentDocs.find((d) => d.index === currentDocIdx);

  return (
    <div className="flex-1 flex flex-col bg-gray-50 relative"
      onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
      {/* 파일 드래그 오버레이 */}
      {fileDragOver && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-amber-50/80 backdrop-blur-sm pointer-events-none">
          <div className="border-2 border-dashed border-amber-400 rounded-2xl px-8 py-6 text-center">
            <Upload size={28} className="text-amber-500 mx-auto mb-2" />
            <p className="text-[14px] font-bold text-amber-600">파일을 여기에 놓으세요</p>
            <p className="text-[11px] text-gray-500">AI가 파일을 읽고 처리합니다</p>
          </div>
        </div>
      )}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-4 chat-selectable">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-14 h-14 rounded-2xl bg-amber-50 flex items-center justify-center mb-4">
              <Sparkles size={26} className="text-amber-500" />
            </div>
            <h3 className="text-[15px] font-bold text-gray-700 mb-1">무엇을 도와드릴까요?</h3>
            <p className="text-[13px] text-gray-500 max-w-sm mb-5">
              {liveMode && liveApp
                ? `${selectedDoc ? `"${selectedDoc.title}"` : (appLabel[liveApp] ?? liveApp)} 문서를 자연어로 제어합니다.`
                : "업무를 설명하면 AI가 자동으로 처리합니다."}
            </p>
            <div className="space-y-2 w-full max-w-md">
              {(liveMode && liveApp ? ({
                hwp: [
                  "이 문서의 수신자를 경기도교육청으로 바꿔줘",
                  "본문 끝에 '위와 같이 보고합니다.' 추가해줘",
                  "표 첫 번째 행에 '과목', '점수', '등급' 넣어줘",
                  "제목을 16pt, 가운데 정렬로 바꿔줘",
                  "전체에서 '2024'를 '2025'로 바꿔줘",
                ],
                excel: [
                  "이 시트의 데이터를 요약해줘",
                  "A열의 합계를 구해서 아래에 넣어줘",
                  "빈 셀을 0으로 채워줘",
                  "새 시트를 추가하고 요약 표를 만들어줘",
                  "열 너비를 자동 조정해줘",
                ],
                ppt: [
                  "새 슬라이드를 추가해줘",
                  "제목을 '2025년 업무 보고'로 바꿔줘",
                  "슬라이드 3을 삭제해줘",
                  "모든 슬라이드에 발표자 노트를 추가해줘",
                  "텍스트를 24pt 볼드로 바꿔줘",
                ],
                word: [
                  "문서 내용을 요약해줘",
                  "'2024'를 '2025'로 전체 바꿔줘",
                  "문서 끝에 '이상입니다.' 추가해줘",
                  "제목을 가운데 정렬로 바꿔줘",
                  "저장해줘",
                ],
              } as Record<string, string[]>)[liveApp] ?? [] : [
                "이 PDF를 읽고 한국어로 요약해서 HWPX로 저장해줘",
                "영어 논문을 한국어로 번역해줘",
                "성적 데이터를 분석하고 보고서를 작성해줘",
                "이 문서에서 핵심 키워드를 추출하고 분류해줘",
                "시험 범위에서 연습 문제 10개 만들어줘",
              ]).map((ex) => (
                <button key={ex} onClick={() => setInput(ex)}
                  className="block w-full text-left px-4 py-2.5 rounded-lg bg-white border border-gray-200
                    hover:border-amber-300 hover:bg-amber-50/50 text-[12px] text-gray-600 transition-all">
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}
      </div>
      {/* 수정 내역 검토 패널 */}
      {pendingActions && (
        <ActionReviewPanel
          actions={pendingActions}
          sending={sending}
          onToggle={(i) => setPendingActions((prev) => prev?.map((a, j) => j === i ? { ...a, checked: !a.checked } : a) ?? null)}
          onSelectAll={() => setPendingActions((prev) => prev?.map((a) => ({ ...a, checked: true })) ?? null)}
          onDeselectAll={() => setPendingActions((prev) => prev?.map((a) => ({ ...a, checked: false })) ?? null)}
          onApply={handleApplyActions}
          onCancel={() => setPendingActions(null)}
        />
      )}
      <div className="border-t border-gray-200 px-4 py-3 bg-white">
        <div className="max-w-3xl mx-auto">
          {/* 라이브 모드 제어 바 */}
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            {/* 앱별 제어 버튼 — 항상 4개 표시 */}
            {(["hwp", "excel", "ppt", "word"] as const).map((app) => {
              const info = detectedApps[app];
              const isActive = liveApp === app && liveMode;
              const isRunning = info?.running;
              const isConnected = info?.connected;
              return (
                <button
                  key={app}
                  onClick={() => handleAppToggle(app)}
                  disabled={connecting}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all border
                    ${isActive
                      ? "bg-blue-50 text-blue-700 border-blue-300"
                      : isRunning
                        ? "bg-gray-100 text-gray-600 border-gray-200 hover:border-blue-300 hover:bg-blue-50/30"
                        : "bg-gray-50 text-gray-400 border-gray-100 hover:border-gray-200"}
                    disabled:opacity-50`}
                >
                  {connecting && liveApp === app
                    ? <Loader2 size={11} className="animate-spin" />
                    : <Monitor size={11} />}
                  {appLabel[app]}
                  {isActive ? " ON" : isConnected ? " ●" : isRunning ? "" : ""}
                </button>
              );
            })}

            {/* 문서 선택 드롭다운 (모든 앱) */}
            {liveMode && liveConnected && liveApp && currentDocs.length > 0 && (
              <div ref={docDropdownRef} className="relative">
                <button
                  onClick={() => setDocDropdownOpen(!docDropdownOpen)}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium
                    bg-blue-50 text-blue-700 border border-blue-200 hover:border-blue-400 transition-all max-w-[220px]"
                >
                  <FileEdit size={11} />
                  <span className="truncate">
                    {selectedDoc?.title || "문서 선택"}
                  </span>
                  {currentDocs.length > 1 && <ChevronDown size={10} />}
                </button>
                {docDropdownOpen && currentDocs.length > 1 && (
                  <div className="absolute bottom-full left-0 mb-1 w-64 bg-white border border-gray-200
                    rounded-lg shadow-lg z-50 py-1 max-h-48 overflow-y-auto">
                    {currentDocs.map((doc) => (
                      <button
                        key={doc.index}
                        onClick={() => switchDocument(liveApp, doc.index)}
                        className={`w-full text-left px-3 py-2 text-[12px] flex items-center gap-2
                          hover:bg-blue-50 transition-colors
                          ${doc.index === currentDocIdx ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-700"}`}
                      >
                        <FileEdit size={12} className={doc.index === currentDocIdx ? "text-blue-500" : "text-gray-400"} />
                        <span className="truncate flex-1">{doc.title}</span>
                        {doc.index === currentDocIdx && (
                          <span className="text-[9px] text-blue-500 bg-blue-100 px-1.5 py-0.5 rounded-full flex-shrink-0">제어 중</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* 연결 상태 */}
            {liveMode && liveConnected && (
              <span className="flex items-center gap-1 text-[10px] text-emerald-500">
                <Plug size={9} /> 연결됨
              </span>
            )}
            {liveMode && !liveConnected && !connecting && (
              <span className="text-[10px] text-amber-500">
                메시지 전송 시 자동 연결
              </span>
            )}
          </div>
          {/* 첨부 파일 목록 */}
          {attachedFiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {attachedFiles.map((f, i) => (
                <div key={i} className="flex items-center gap-1 px-2 py-1 bg-amber-50 border border-amber-200 rounded-lg text-[11px]">
                  <FileText size={11} className="text-amber-600" />
                  <span className="text-amber-800 max-w-[150px] truncate">{f.name}</span>
                  <button onClick={() => removeFile(i)} className="text-amber-400 hover:text-amber-600">
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}
          {/* 모델 선택 + 디자인 스킬 + 입력 */}
          <div className="flex items-center gap-1.5 mb-1">
            <div ref={modelDropdownRef} className="relative">
              <button onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
                className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-gray-500
                  hover:bg-gray-100 border border-gray-200 transition-colors">
                <Cpu size={11} />
                <span>{models.find(m => m.id === selectedModel)?.name || selectedModel.split("/").pop()}</span>
                <ChevronDown size={10} />
              </button>
              {modelDropdownOpen && models.length > 0 && (
                <div className="absolute bottom-full left-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50 min-w-[180px] max-h-64 overflow-y-auto">
                  {["openai", "claude", "gemini", "local"].map(provider => {
                    const group = models.filter(m => m.provider === provider);
                    if (group.length === 0) return null;
                    const label: Record<string, string> = { openai: "OpenAI", claude: "Anthropic", gemini: "Google", local: "Local" };
                    return (
                      <div key={provider}>
                        <div className="px-3 py-1 text-[10px] font-bold text-gray-400 uppercase">{label[provider] ?? provider}</div>
                        {group.map(m => (
                          <button key={m.id}
                            onClick={() => { if (m.available !== false) { setSelectedModel(m.id); setModelDropdownOpen(false); } }}
                            className={`w-full text-left px-3 py-1.5 text-[12px]
                              ${m.available === false ? "text-gray-300 cursor-not-allowed" :
                                m.id === selectedModel ? "text-amber-600 font-medium bg-amber-50/50" : "text-gray-700 hover:bg-gray-50"}`}>
                            {m.name}
                            {m.available === false && <span className="ml-1 text-[9px] text-gray-300">(키 없음)</span>}
                          </button>
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            {/* 모드 선택 */}
            <div className="flex items-center rounded-md border border-gray-200 overflow-hidden">
              <button
                onClick={() => setLiveMode(false)}
                className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium transition-colors
                  ${!liveMode
                    ? "text-amber-700 bg-amber-50"
                    : "text-gray-400 bg-white hover:bg-gray-50"}`}
              >
                <MessageSquare size={11} />
                <span>플로우</span>
              </button>
              <button
                onClick={() => setLiveMode(true)}
                className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium transition-colors border-l border-gray-200
                  ${liveMode
                    ? "text-blue-700 bg-blue-50"
                    : "text-gray-400 bg-white hover:bg-gray-50"}`}
              >
                <Monitor size={11} />
                <span>문서 제어</span>
              </button>
            </div>
            {/* 디자인 스킬 선택 */}
            {liveMode && designSkills.length > 0 && (
              <div ref={designDropdownRef} className="relative">
                <button onClick={() => setDesignDropdownOpen(!designDropdownOpen)}
                  className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] transition-colors border
                    ${selectedDesign !== "default"
                      ? "text-violet-600 bg-violet-50 border-violet-200 hover:bg-violet-100"
                      : "text-gray-500 hover:bg-gray-100 border-gray-200"}`}>
                  <Palette size={11} />
                  <span>{designSkills.find(s => s.id === selectedDesign)?.name || "기본"}</span>
                  <ChevronDown size={10} />
                </button>
                {designDropdownOpen && (
                  <div className="absolute bottom-full left-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50 min-w-[140px]">
                    {designSkills.map(s => (
                      <button key={s.id}
                        onClick={() => { setSelectedDesign(s.id); setDesignDropdownOpen(false); }}
                        className={`w-full text-left px-3 py-1.5 text-[12px]
                          ${s.id === selectedDesign ? "text-violet-600 font-medium bg-violet-50/50" : "text-gray-700 hover:bg-gray-50"}`}>
                        {s.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="relative flex items-end gap-2">
            <button onClick={() => fileInputRef.current?.click()} title="파일 첨부"
              className="p-2 rounded-lg text-gray-400 hover:text-amber-500 hover:bg-amber-50 transition-colors flex-shrink-0">
              <Upload size={16} />
            </button>
            <input ref={fileInputRef} type="file" multiple onChange={onFileSelect} className="hidden" />
            <textarea value={input} onChange={(e) => { setInput(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 150) + "px"; }}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              placeholder={liveMode && selectedDoc
                ? `"${selectedDoc.title}" 문서에 할 작업을 설명하세요...`
                : liveMode ? `${appLabel[liveApp!] ?? liveApp} 문서에 할 작업을 설명하세요...`
                : "업무를 설명하세요... (Shift+Enter 줄바꿈)"}
              rows={1}
              className={`flex-1 pl-3 pr-12 py-2.5 rounded-lg text-[13px] border
                text-gray-700 placeholder-gray-400 resize-none
                focus:outline-none transition-all overflow-hidden
                ${liveMode
                  ? "bg-blue-50/30 border-blue-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-200"
                  : "bg-gray-50 border-gray-200 focus:border-amber-400 focus:ring-1 focus:ring-amber-200"}`} />
            <button onClick={handleSend} disabled={(!input.trim() && attachedFiles.length === 0) || sending}
              className={`absolute right-2 bottom-2 p-1.5 rounded text-white
                disabled:opacity-30 disabled:cursor-not-allowed transition-all
                ${liveMode ? "bg-blue-500 hover:bg-blue-600" : "bg-amber-500 hover:bg-amber-600"}`}>
              {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
