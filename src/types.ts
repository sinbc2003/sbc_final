/** 노드 포트 스펙 */
export interface PortSpec {
  name: string;
  type: string;
  accept?: string[];
  description?: string;
}

/** 노드 파라미터 정의 */
export interface ParamDef {
  id: string;
  label: string;
  type: string; // string | text | integer | float | select | boolean
  default?: string | number | boolean;
  description?: string;
  options?: string[];
}

/** 엔진에서 로드한 노드 정의 */
export interface NodeDefinition {
  id: string;
  name: string;
  version: string;
  category: string;
  icon: string;
  author: string;
  description: string;
  inputs: PortSpec[];
  outputs: PortSpec[];
  params: ParamDef[];
  resource: {
    requires_api?: string | null;
    max_memory_mb?: number;
    estimated_time?: string;
  };
  use_when?: string[];
}

/** React Flow 노드의 data 필드 */
export interface FlowNodeData {
  definitionId: string;
  label: string;
  category: string;
  icon: string;
  description: string;
  inputs: PortSpec[];
  outputs: PortSpec[];
  params: ParamDef[];
  paramValues: Record<string, any>;
  status: "idle" | "running" | "done" | "error";
  progress: number; // 0~1
  error?: string;
  [key: string]: unknown;
}

/** 워크플로우 직렬화 포맷 */
export interface WorkflowJSON {
  id: string;
  name: string;
  version: string;
  description: string;
  created_at: string;
  nodes: {
    id: string;
    type: string;
    position: { x: number; y: number };
    params: Record<string, any>;
  }[];
  edges: {
    from: string;
    from_port: string;
    to: string;
    to_port: string;
  }[];
  user_inputs: any[];
}

/** 앱 모드 */
export type AppMode = "home" | "design" | "chat" | "manager";

/** 실행 상태 */
export type ExecutionStatus = "idle" | "running" | "done" | "error";

/** 채팅 메시지 */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  workflowId?: string;
  workflowJson?: WorkflowJSON;
  /** 라이브 문서 제어 결과 */
  liveResults?: { action: string; success: boolean; message: string }[];
  liveSummary?: string;
  /** AI 응답 스트리밍 중 */
  isStreaming?: boolean;
  /** FormAssist 자동 라우팅 결과 */
  formAssist?: boolean;
  formFile?: string | null;
}
