/** 실행 로그를 비개발자에게 읽히는 문구로 바꾼다.
 *  설계 화면(ExecutionPanel)과 교사용 실행 화면(TaskRunner)이 같은 표현을 쓰도록
 *  한 곳에 모았다. */

const REPLACEMENTS: [string, string][] = [
  ["[ERROR] ", ""],
  ["[WARN] ", ""],
  ["pymupdf로 변환", "문서 읽는 중"],
  ["ZIP+XML 파싱으로 변환", "문서 읽는 중"],
  ["pypandoc-hwpx로 변환 완료", "한글 파일 생성 완료"],
];

export function friendlyLogMessage(message: string): string {
  let out = message;
  for (const [from, to] of REPLACEMENTS) out = out.replace(from, to);
  return out;
}

export function isErrorLog(message: string): boolean {
  return message.startsWith("[오류]") || message.startsWith("[치명적 오류]")
    || message.startsWith("[ERROR]");
}

export function isWarnLog(message: string): boolean {
  return message.startsWith("[WARN]");
}
