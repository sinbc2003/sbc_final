"""
Claude가 직접 작성하는 PPT + Excel 데모.
COM API로 열린 Excel/PPT에 바로 쓴다.
"""
import requests
import json
import time

API = "http://127.0.0.1:8322"

def exe(app, action, params):
    r = requests.post(f"{API}/api/live/execute/{app}", json={"action": action, "params": params}, timeout=30)
    d = r.json()
    if not d.get("success"):
        print(f"  [WARN] {app}/{action}: {d.get('message')}")
    return d

# ═══════════════════════════════════════════════════════
#  PPT: TeacherFlow 마케팅 프레젠테이션 20장
# ═══════════════════════════════════════════════════════

print("=== PPT 작성 시작 ===")

# 기존 슬라이드 1,2 위에 쓰고 나머지는 추가
slides = [
    # 1: 표지
    ("TeacherFlow", "교사 업무 자동화 플랫폼\n\n교실의 시간을 되돌려 드립니다"),
    # 2: 문제 정의
    ("교사는 왜 바쁜가?", "평균 주 52시간 근무\n수업 준비 외 행정 업무 40%\n공문 처리, 성적 입력, 양식 작성...\n\n교사의 시간을 수업에 돌려드립니다"),
    # 3: 시장 기회
    ("시장 기회", "전국 교사 50만 명\n연간 행정 업무 시간 → 8,000만 시간\n공교육 디지털 전환 정책 가속\n경쟁 솔루션: 거의 없음"),
    # 4: 솔루션 개요
    ("TeacherFlow란?", "노코드 업무 자동화 데스크톱 앱\n\n파일 넣고 → 실행 → 완성\n\nHWP/HWPX, Excel, PDF 네이티브 지원\nAI 기반 문서 자동 작성"),
    # 5: 핵심 기능 1
    ("핵심 기능 ① 양식 자동 채우기", "공문 양식(HWP/Excel) 업로드\n→ AI가 빈칸 자동 감지\n→ 맥락 기반 내용 생성\n→ 원본 서식 100% 보존\n\n교사 작업: 파일 1개 드래그"),
    # 6: 핵심 기능 2
    ("핵심 기능 ② 라이브 문서 제어", "한/글, Excel, PPT 실시간 연결\n\n열려있는 문서에 AI가 직접 작성\n채팅으로 지시 → 즉시 반영\n\nInline AI 수준의 편의성"),
    # 7: 핵심 기능 3
    ("핵심 기능 ③ 성적 분석 자동화", "성적 Excel 업로드\n→ 문항별/반별/학생별 분석\n→ 순위, 평균, 정답률 자동 산출\n→ 분석 시트 자동 생성"),
    # 8: 핵심 기능 4
    ("핵심 기능 ④ 노드 기반 워크플로우", "고급 사용자를 위한 VBA 모드\n\n30+ 노드 드래그&드롭\nPDF→변환→AI→출력 자유 조합\n프리셋으로 저장/공유"),
    # 9: 기술 아키텍처
    ("기술 아키텍처", "Tauri v2 데스크톱 앱 (10MB)\nPython 엔진 (FastAPI)\nReact + React Flow UI\n\n오프라인 동작 (로컬 LLM)\nAPI 연동 (Claude, GPT, Gemini)"),
    # 10: 차별화
    ("왜 TeacherFlow인가?", "① HWP 네이티브 — 유일한 솔루션\n② 오프라인 우선 — 학교 네트워크 OK\n③ 무료 배포 — 공교육 미션\n④ 데이터 플라이휠 — 쓸수록 개선"),
    # 11: 경쟁 분석
    ("경쟁 환경", "ChatGPT/Gemini: HWP 미지원, 온라인만\nInline AI: HWP만, 양식 채우기 없음\nMS Copilot: HWP 미지원, 유료\nNEIS: 정해진 기능만\n\nTeacherFlow: 모든 포맷 + 오프라인 + 무료"),
    # 12: 사용자 시나리오 1
    ("시나리오: 공문 처리", "1. 교육청에서 공문 도착 (ODT+첨부)\n2. 첨부된 양식(HWP) 드래그\n3. AI가 빈칸 감지 + 내용 생성\n4. 교사 확인 → 제출\n\n소요 시간: 30분 → 2분"),
    # 13: 사용자 시나리오 2
    ("시나리오: 시험 성적 처리", "1. 성적 Excel 파일 업로드\n2. '분석 탭 만들어줘' 클릭\n3. 문항별 정답률, 반별 평균, 순위\n4. 자동 생성 → 바로 인쇄\n\n소요 시간: 2시간 → 30초"),
    # 14: 사용자 시나리오 3
    ("시나리오: 생기부 작성", "1. 학생 활동 자료 업로드\n2. AI가 생기부 초안 생성\n3. 교사가 수정/보완\n4. HWP로 저장\n\n소요 시간: 학생 1명 40분 → 5분"),
    # 15: 비즈니스 모델
    ("비즈니스 모델", "기본: 무료 (오프라인 기능)\n프로: 월 9,900원 (API 기반 AI)\n학교 라이센스: 연 100만원/교\n\nCAC: 0 (교사 커뮤니티 바이럴)\nLTV: 프로 기준 연 118,800원"),
    # 16: 로드맵
    ("개발 로드맵", "2026 Q2: 베타 출시 (교사 100명)\n2026 Q3: 정식 출시 + 노드 50개\n2026 Q4: 학교 라이센스 + 마켓플레이스\n2027 Q1: 로컬 LLM 완전 오프라인\n2027 Q2: 모바일 동반자 앱"),
    # 17: 팀
    ("팀 소개", "신병철 — 창업자/개발자\n현직 고등학교 수학 교사\n\n미션: 공교육의 반격\n\nedu-shin.com 운영\nRAG 기반 생기부 시스템 개발 경험"),
    # 18: 트랙션
    ("현재 진행 상황", "엔진: 31개 노드 구현 완료\nUI: 홈/설계/채팅/관리 4모드\nCOM 제어: HWP+Excel+PPT\n스킬 시스템: 3개 앱 프롬프트 완성\n\n베타 테스트: 2026년 6월 예정"),
    # 19: 투자 요청
    ("투자 제안", "시드 라운드: 3억원\n\n용도:\n- 풀타임 개발자 2명 (18개월)\n- 서버/인프라 (LLM API 비용)\n- 교사 커뮤니티 구축\n- 교육청 파일럿 운영"),
    # 20: 클로징
    ("교실의 시간을 되돌립니다", "TeacherFlow\n\n신병철\nshin@edu-shin.com\nedu-shin.com\n\n감사합니다"),
]

# 슬라이드 1 수정 (이미 있음)
exe("ppt", "set_text", {"slide": 1, "shape": 0, "text": slides[0][0]})
exe("ppt", "set_text", {"slide": 1, "shape": 1, "text": slides[0][1]})

# 슬라이드 2 수정 (이미 있음)
exe("ppt", "set_text", {"slide": 2, "shape": 0, "text": slides[1][0]})
exe("ppt", "set_text", {"slide": 2, "shape": 1, "text": slides[1][1]})

# 슬라이드 3~20 추가
for i, (title, content) in enumerate(slides[2:], start=3):
    exe("ppt", "add_slide", {"title": title, "content": content, "layout": 2})
    print(f"  슬라이드 {i}/{len(slides)} 완료")

print(f"PPT 완료: {len(slides)}장")

# ═══════════════════════════════════════════════════════
#  Excel: 분석 탭 생성
# ═══════════════════════════════════════════════════════

print("\n=== Excel 분석 탭 작성 시작 ===")

# 새 시트 추가
exe("excel", "add_sheet", {"name": "분석"})
time.sleep(0.5)

# ── 헤더 ──
headers = {
    "A1": "[ 시험 성적 종합 분석 ]",
    "A3": "■ 전체 요약",
    "A4": "항목", "B4": "값",
    "A5": "응시 인원", "B5": "=COUNTA(Sheet2!E2:E127)",
    "A6": "전체 평균", "B6": "=ROUND(AVERAGE(Sheet2!R2:R127),1)",
    "A7": "최고점", "B7": "=MAX(Sheet2!R2:R127)",
    "A8": "최저점", "B8": "=MIN(Sheet2!R2:R127)",
    "A9": "표준편차", "B9": "=ROUND(STDEV(Sheet2!R2:R127),1)",
    "A10": "만점자", "B10": "=COUNTIF(Sheet2!R2:R127,\">=96\")",
}
exe("excel", "set_cells", {"cells": headers})

# ── 반별 평균 ──
class_headers = {
    "A12": "■ 반별 평균",
    "A13": "반", "B13": "인원", "C13": "평균", "D13": "최고", "E13": "최저",
}
exe("excel", "set_cells", {"cells": class_headers})

for cls in range(1, 9):
    row = 13 + cls
    cells = {
        f"A{row}": f"{cls}반",
        f"B{row}": f'=COUNTIFS(Sheet2!C2:C127,{cls})',
        f"C{row}": f'=ROUND(AVERAGEIFS(Sheet2!R2:R127,Sheet2!C2:C127,{cls}),1)',
        f"D{row}": f'=MAXIFS(Sheet2!R2:R127,Sheet2!C2:C127,{cls})',
        f"E{row}": f'=MINIFS(Sheet2!R2:R127,Sheet2!C2:C127,{cls})',
    }
    exe("excel", "set_cells", {"cells": cells})
print("  반별 평균 완료")

# ── 문항별 분석 ──
q_labels = ["1번", "2(1)", "2(2)", "3(1)", "3(2)", "4(1)", "4(2)", "5번", "6번", "7번", "8(1)", "8(2)"]
q_cols = ["F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q"]
q_max  = [10, 6, 8, 4, 7, 4, 8, 12, 15, 14, 2, 10]

q_header = {
    "A23": "■ 문항별 분석",
    "A24": "문항", "B24": "배점", "C24": "평균", "D24": "정답률(%)", "E24": "표준편차",
}
exe("excel", "set_cells", {"cells": q_header})

for i, (label, col, mx) in enumerate(zip(q_labels, q_cols, q_max)):
    row = 25 + i
    cells = {
        f"A{row}": label,
        f"B{row}": mx,
        f"C{row}": f"=ROUND(AVERAGE(Sheet2!{col}2:{col}127),2)",
        f"D{row}": f"=ROUND(AVERAGE(Sheet2!{col}2:{col}127)/{mx}*100,1)",
        f"E{row}": f"=ROUND(STDEV(Sheet2!{col}2:{col}127),2)",
    }
    exe("excel", "set_cells", {"cells": cells})
print("  문항별 분석 완료")

# ── 학생 순위 (상위 20명) ──
rank_header = {
    "A38": "■ 학생 순위 (상위 20명)",
    "A39": "순위", "B39": "반", "C39": "번호", "D39": "이름", "E39": "총점", "F39": "환산",
}
exe("excel", "set_cells", {"cells": rank_header})

for rank in range(1, 21):
    row = 39 + rank
    cells = {
        f"A{row}": rank,
        f"B{row}": f'=INDEX(Sheet2!C$2:C$127,MATCH(LARGE(Sheet2!R$2:R$127,{rank}),Sheet2!R$2:R$127,0))',
        f"C{row}": f'=INDEX(Sheet2!D$2:D$127,MATCH(LARGE(Sheet2!R$2:R$127,{rank}),Sheet2!R$2:R$127,0))',
        f"D{row}": f'=INDEX(Sheet2!E$2:E$127,MATCH(LARGE(Sheet2!R$2:R$127,{rank}),Sheet2!R$2:R$127,0))',
        f"E{row}": f'=LARGE(Sheet2!R$2:R$127,{rank})',
        f"F{row}": f'=ROUND(LARGE(Sheet2!R$2:R$127,{rank})/100*25,2)',
    }
    exe("excel", "set_cells", {"cells": cells})
print("  학생 순위 완료")

# 열 너비 자동 조정
exe("excel", "auto_fit", {})

print("\n=== 전체 완료 ===")
