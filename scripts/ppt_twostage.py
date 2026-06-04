"""
2단계 PPT 생성 테스트.
1단계: 기획 (Claude 역할 — 여기서는 하드코딩으로 시뮬레이션)
2단계: GPT-4.1이 기획서 + 디자인 스킬 보고 코드 작성
"""
import json
import os
import sys

secrets = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", ".secrets.json"), encoding="utf-8"))
api_key = secrets.get("openai_api_key", "")
if not api_key:
    print("OpenAI API 키 없음"); sys.exit(1)

from openai import OpenAI
client = OpenAI(api_key=api_key)

# ═══════════════════════════════════════════
#  1단계: 기획 (슬라이드별 상세 스펙)
#  실제로는 Claude가 생성하는 부분
# ═══════════════════════════════════════════

PLAN = """
[슬라이드 기획서 — TeacherFlow 투자 프레젠테이션 20장]

색상 팔레트:
- AMBER = #F59E0B (주 색상)
- DARK = #1F2037 (배경/제목)
- WHITE = #FFFFFF
- LGRAY = #F8F8FA (카드 배경)
- GRAY = #6B7280 (보조 텍스트)
- GREEN = #10B981 (긍정)
- RED = #EF4444 (부정)
- BLUE = #3B82F6 (강조)

캔버스: 13.333 x 7.5 inches (16:9)

공통 규칙:
- 상단 앰버 라인: y=0, 높이=0.06인치, 전체 폭
- 제목: x=0.8, y=0.5, 폰트 32pt bold, 색상 DARK
- 제목 아래 구분선: x=0.8, y=1.3, 폭 1.5인치, 높이 0.04인치, AMBER
- 불릿 텍스트: 18pt, 줄간격 0.55인치, 시작 y=1.8
- 불릿 포인트: 0.12x0.12인치 사각형, x=1.0
- 텍스트 시작: x=1.4
- 도형 테두리: 없음 (line.fill.background())
- 폰트 32pt → 컨테이너 최소 높이 0.7인치
- 폰트 18pt → 컨테이너 최소 높이 0.45인치
- 폰트 14pt → 컨테이너 최소 높이 0.35인치
- 슬라이드당 텍스트 최대 8줄 (넘치면 폰트 줄여라)

---

슬라이드 1: 표지
- 배경: DARK
- 좌측 세로 앰버 바: x=0.8, y=1.5, 폭 0.15, 높이 2인치
- "TeacherFlow": x=1.3, y=1.5, 56pt bold WHITE
- "교사 업무 자동화 플랫폼": x=1.3, y=2.8, 24pt AMBER
- "교실의 시간을 되돌려 드립니다": x=1.3, y=4.0, 18pt GRAY
- "2026 | Investor Deck": x=1.3, y=6.0, 14pt GRAY

슬라이드 2: 문제 정의
- 배경: WHITE, 상단 앰버 라인
- 제목: "교사는 왜 바쁜가?" 36pt bold DARK
- 통계 카드 4개 (가로 배치):
  - x=0.8, y=2.0, 2.5x1.8인치, 배경 LGRAY
    - 숫자 "52h" 36pt bold AMBER, 중앙정렬
    - 라벨 "주당 평균 근무시간" 13pt GRAY, 중앙정렬
  - x=3.8: "40%" RED, "행정 업무 비율"
  - x=6.8: "0개" GRAY, "자동화 도구"
  - x=9.8: "50만" BLUE, "전국 교사 수"
- 하단 설명 3줄: y=4.5, 16pt GRAY
  - "공문 처리, 성적 입력, 양식 작성, 생기부 기록..."
  - "교사의 전문성은 수업에 있지만, 시간의 40%를 행정에 뺏기고 있습니다."
  - "대안은? HWP를 다루는 자동화 도구는 사실상 전무합니다."

슬라이드 3: 솔루션 (섹션 구분)
- 배경: AMBER (전체)
- "TeacherFlow" 44pt bold WHITE 중앙정렬 y=2.5
- "파일 넣고 → 실행 → 완성" 20pt 연한 앰버(#FFF0D0) 중앙정렬 y=4.2

슬라이드 4: 제품 개요
- 배경: WHITE, 상단 앰버 라인, 제목+구분선
- 제목: "제품 개요"
- 불릿 6줄 (y=1.8부터 0.55간격):
  - ● "노코드 업무 자동화 데스크톱 앱" (● AMBER)
  - ● "HWP/HWPX, Excel, PDF, DOCX 네이티브 지원"
  - ● "AI 기반 문서 자동 작성 + 양식 채우기" (● AMBER)
  - ● "오프라인 동작 (학교 네트워크 제약 대응)"
  - ● "열려있는 한/글·Excel·PPT를 AI가 직접 제어" (● AMBER)
  - ● "교사 맞춤 프리셋으로 원클릭 실행"

슬라이드 5: 핵심 기능 섹션
- 배경: AMBER
- "핵심 기능" 44pt WHITE 중앙정렬 y=2.5
- "4가지 핵심 가치" 20pt 연한 앰버 중앙정렬 y=4.2

슬라이드 6: 양식 자동 채우기 (2단)
- 배경: WHITE, 상단 앰버 라인, 제목+구분선
- 제목: "① 양식 자동 채우기"
- 좌측 칼럼 (x=0.8~6.3):
  - 헤더 바: DARK 배경, "기능" 14pt WHITE bold 중앙
  - 5줄: "공문 양식(HWP/Excel) 업로드", "AI가 빈칸 자동 감지", "맥락 기반 내용 생성", "원본 서식 100% 보존", "매크로·수식 영향 없음"
- 우측 칼럼 (x=7.0~12.5):
  - 헤더 바: AMBER 배경, "효과" 14pt WHITE bold 중앙
  - 5줄: "교사 작업: 파일 1개 드래그", "소요 시간: 30분 → 2분", "지원 포맷: HWP, HWPX, XLSX", "COM API + openpyxl 기반", "양식 종류 무제한"
- 텍스트: 15pt GRAY, y시작 2.5, 줄간격 0.45인치

슬라이드 7: 라이브 제어 (2단) — 슬라이드 6과 동일 레이아웃
- 제목: "② 라이브 문서 제어"
- 좌: "기능" — 한/글 Excel PPT 실시간 연결 / 열려있는 문서에 AI가 직접 작성 / 채팅으로 지시 → 즉시 반영 / 25개 COM API 액션
- 우: "기술" — 앱별 LLM 스킬 프롬프트 내장 / GPT-4.1로도 정확한 제어 / 프로세스 자동 감지 (10초) / 한/글 COM + 보안 모듈

슬라이드 8: 성적 분석 (2단) — 동일 레이아웃
- 제목: "③ 성적 분석 자동화"
- 좌: "분석 항목" — 성적 Excel 업로드 / 문항별 정답률 자동 산출 / 반별 평균·표준편차 / 학생 순위 (상위 N명)
- 우: "특징" — 수식 기반 (값이 아닌 수식 삽입) / 원본 데이터 손상 없음 / 새 시트에 분석 결과 생성 / COM API로 실시간 작성

슬라이드 9: 노드 에디터
- 표준 불릿 레이아웃
- 제목: "④ 노드 기반 워크플로우 (고급)"
- 6줄: 고급 사용자를 위한 VBA 모드 / 31개 노드 드래그&드롭 조합 / PDF→변환→AI→출력 자유 파이프라인 / 프리셋으로 저장/공유 / 엔진이 DAG 위상정렬 → 순차 실행 / React Flow 비주얼 에디터

슬라이드 10: 기술 아키텍처
- 표준 불릿 레이아웃
- 제목: "기술 아키텍처"
- 6줄: Tauri v2 — 설치 10MB, 메모리 30MB / Python FastAPI — 33+ API / React + React Flow — 4모드 UI / COM API — HWP/Excel/PPT 제어 / LLM 통합 — Claude, GPT, Gemini, llama.cpp / 오프라인 우선

슬라이드 11: 경쟁 분석
- 배경 WHITE, 상단 앰버 라인, 제목+구분선
- 제목: "경쟁 환경"
- 4개 가로 바 (y=1.8부터 1.2인치 간격):
  - 각 바: 11.5인치 폭, 1.0인치 높이
  - 처음 3개: LGRAY 배경
  - 마지막(TeacherFlow): 연한 초록(#ECFDF5) 배경
  - 이름: 18pt bold (각각 RED, 주황#F97316, GRAY, GREEN)
  - 설명: 14pt GRAY, 이름 아래 0.4인치
  - ChatGPT/Gemini: "HWP 미지원, 온라인만"
  - Inline AI: "HWP만, 양식 채우기 없음"
  - MS Copilot: "HWP 미지원, 유료"
  - TeacherFlow: "모든 포맷 + 오프라인 + 무료"

슬라이드 12: 시나리오 — 공문 처리
- 상단 앰버 라인, 제목+구분선
- 제목: "시나리오: 공문 처리"
- 4단계 (y=1.8부터 0.7인치 간격):
  - 각 단계: 번호(AMBER 사각형 0.5x0.5, 16pt WHITE bold 중앙) + 텍스트(18pt)
  - 1. 교육청에서 공문 도착 (ODT + 첨부)
  - 2. 첨부된 양식(HWP) 드래그&드롭
  - 3. AI가 빈칸 감지 + 내용 자동 생성
  - 4. 교사 확인 → 즉시 제출
- Before/After 비교 (y=5.2):
  - 좌: 5.0x1.2인치, 연한빨강(#FEF2F2), "Before: 30분" 20pt RED bold
  - 우: x=6.5, 5.8x1.2인치, 연한초록(#ECFDF5), "After: 2분" 20pt GREEN bold

슬라이드 13: 시나리오 — 성적 처리 (슬라이드12와 동일 레이아웃)
- 제목: "시나리오: 시험 성적 처리"
- 4단계: 성적 Excel 업로드 / '분석 탭 만들어줘' 클릭 / 문항별 정답률+반별 평균+순위 / 분석 시트 자동 생성→인쇄
- Before: 2시간 / After: 30초

슬라이드 14: 시나리오 — 생기부 (동일 레이아웃)
- 제목: "시나리오: 생기부 작성"
- 4단계: 학생 활동 자료 업로드 / AI가 생기부 초안 생성 / 교사가 수정/보완 / HWP로 저장→NEIS 붙여넣기
- Before: 40분/명 / After: 5분/명

슬라이드 15: 비즈니스 모델
- 상단 앰버 라인, 제목+구분선
- 제목: "비즈니스 모델"
- 3개 가격 카드 (가로 배치):
  - 각 카드: 3.7x3.5인치, LGRAY 배경
  - 상단 헤더바: 3.7x0.8인치
    - Free: GRAY 배경 / Pro: AMBER 배경 / School: DARK 배경
    - 티어명 20pt WHITE bold 중앙
  - 가격: 28pt bold 중앙 (같은 색상)
    - Free: "무료" / Pro: "₩9,900/월" / School: "₩100만/년"
  - 설명: 13pt GRAY 중앙
    - "오프라인 기능 전체" / "API AI + 클라우드 동기화" / "학교 라이센스 + 관리자 대시보드"
  - x좌표: 0.8 / 4.9 / 9.0

슬라이드 16: 로드맵
- 표준 불릿 레이아웃
- 제목: "개발 로드맵"
- 5줄 (1,3번째 ● AMBER):
  - 2026 Q2 — 베타 출시 (교사 100명)
  - 2026 Q3 — 정식 출시 + 노드 50개 + 마켓플레이스
  - 2026 Q4 — 학교 라이센스 + 교육청 파일럿
  - 2027 Q1 — 로컬 LLM 완전 오프라인
  - 2027 Q2 — 모바일 동반자 앱 + API 개방

슬라이드 17: 팀
- 상단 앰버 라인, 제목+구분선
- 제목: "팀"
- 큰 카드: x=2, y=2.0, 9x4인치, LGRAY 배경
  - "신병철" 32pt bold DARK, x=2.5, y=2.3
  - "창업자 / 개발자 / 현직 고등학교 수학 교사" 16pt AMBER, y=3.0
  - 4줄 설명 (15pt GRAY, y=3.7):
    - 미션: "공교육의 반격을 통한 사교육 시장의 붕괴"
    - edu-shin.com 운영 (RAG 기반 생기부 시스템)
    - 6대 장비 클러스터 직접 구축·운영
    - Python/React/COM API 풀스택

슬라이드 18: 트랙션
- 상단 앰버 라인, 제목+구분선
- 제목: "현재 진행 상황"
- 통계 카드 6개 (3x2 그리드):
  - 각 2.1인치 간격, 카드 2.5x1.8인치
  - 행1(y=2.0): "31+" 노드, "33+" API, "3개" 라이브제어
  - 행2(y=4.2): "4모드" UI, "25" COM액션, "3개" LLM스킬
  - 홀수 AMBER, 짝수 BLUE

슬라이드 19: 투자 제안
- 배경: DARK
- "투자 제안" 36pt WHITE bold, y=0.8
- 구분선: AMBER, y=1.6
- "시드 라운드: 3억원" 28pt AMBER bold, y=2.2
- 4개 항목 (y=3.5부터 0.6간격):
  - 번호: AMBER 사각형 0.4x0.4, 12pt WHITE bold 중앙
  - 텍스트: 18pt 연한회색(#CCCCCC)
  - 풀타임 개발자 2명 (18개월)
  - 서버/인프라 (LLM API 비용)
  - 교사 커뮤니티 구축 + 바이럴 마케팅
  - 교육청 파일럿 운영 (3개 시·도)

슬라이드 20: 클로징
- 배경: DARK
- 좌측 세로 앰버 바: x=0.8, y=2.0, 폭 0.15, 높이 2.5인치
- "교실의 시간을\\n되돌립니다" 48pt WHITE bold, x=1.3, y=2.0
- "TeacherFlow" 24pt AMBER bold, y=4.0
- "신병철 | shin@edu-shin.com | edu-shin.com" 16pt GRAY, y=5.0
- "감사합니다" 16pt GRAY, y=5.4
"""

# ═══════════════════════════════════════════
#  2단계: GPT-4.1이 기획서 보고 코드 작성
# ═══════════════════════════════════════════

DESIGN_SKILL = """당신은 python-pptx 코드를 작성하는 실행 엔진입니다.

규칙:
1. 기획서에 명시된 좌표, 크기, 색상, 폰트를 **정확히** 따르세요. 임의로 바꾸지 마세요.
2. python-pptx만 사용합니다.
3. 코드만 반환. 설명 없이 python 코드 블록만.
4. RGBColor의 인자는 정수 (0xFF 형태).
5. 도형 테두리는 shape.line.fill.background()로 제거.
6. word_wrap = True 항상 설정.
7. OUTPUT_PATH 변수에 저장.
8. 마지막에 print(f"완료: {len(prs.slides)}장")
9. 기획서의 좌표는 인치 단위 → Inches() 사용.
10. 기획서에 없는 요소를 추가하지 마세요.
"""

print("GPT-4.1 호출 중 (2단계 방식)...")
response = client.chat.completions.create(
    model="gpt-4.1",
    messages=[
        {"role": "system", "content": DESIGN_SKILL},
        {"role": "user", "content": f"다음 기획서를 python-pptx 코드로 변환하세요.\n\n{PLAN}"},
    ],
    max_tokens=16000,
    temperature=0.3,  # 낮은 temperature — 기획서 충실하게
)

code = response.choices[0].message.content
if "```python" in code:
    code = code.split("```python")[1].split("```")[0]
elif "```" in code:
    code = code.split("```")[1].split("```")[0]

output_path = os.path.join(os.path.dirname(__file__), "..", "data", "TeacherFlow_TwoStage.pptx")
code = f'OUTPUT_PATH = r"{output_path}"\n' + code

print(f"코드 생성 완료 ({len(code)}자)")
print("코드 실행 중...")

# 생성 코드 저장 (디버그용)
with open(os.path.join(os.path.dirname(__file__), "ppt_twostage_generated.py"), "w", encoding="utf-8") as f:
    f.write(code)

try:
    exec(code, {"__builtins__": __builtins__})
    print(f"저장: {output_path}")
except Exception as e:
    print(f"실행 오류: {e}")
    import traceback; traceback.print_exc()
