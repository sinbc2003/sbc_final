"""
GPT-4.1이 만드는 TeacherFlow 마케팅 PPT.
1. GPT-4.1에게 python-pptx 코드 생성을 요청
2. 생성된 코드를 실행하여 PPT 파일 생성
"""
import json
import os
import sys
import tempfile

# API 키 로드
secrets = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", ".secrets.json"), encoding="utf-8"))
api_key = secrets.get("openai_api_key", "")
if not api_key:
    print("OpenAI API 키 없음")
    sys.exit(1)

from openai import OpenAI
client = OpenAI(api_key=api_key)

SYSTEM_PROMPT = """당신은 python-pptx로 전문적인 마케팅 PPT를 만드는 전문가입니다.
16:9 비율(13.333x7.5 inch), 앰버(#F59E0B)/다크(#1F2037) 색상 팔레트로
기업 투자용 프레젠테이션을 만들어야 합니다.

규칙:
- python-pptx만 사용 (import 가능한 표준 라이브러리 포함)
- 코드만 반환. 설명 없이 python 코드 블록만.
- 20장 슬라이드
- 디자인 요소: 배경색, 색상 도형, 폰트 크기/색상/굵기, 통계 카드, 2단 레이아웃 등
- 저장 경로: OUTPUT_PATH 변수 사용
- print(f"저장 완료: {OUTPUT_PATH}") 마지막에 포함
"""

USER_PROMPT = """TeacherFlow라는 교사 업무 자동화 플랫폼의 투자자용 마케팅 PPT를 20장으로 만들어주세요.

제품 정보:
- 교사 업무(공문, 성적, 생기부 등) 자동화 데스크톱 앱
- HWP/Excel/PPT를 AI가 직접 제어 (COM API)
- 노드 기반 워크플로우 에디터 (VBA 같은 고급 모드)
- 프리셋 기반 원클릭 실행 (홈 화면)
- 양식 자동 채우기 (빈칸 감지 → LLM 작성 → 원본 주입)
- 오프라인 동작 (로컬 LLM)
- 전국 교사 50만명 대상, 무료 배포 + Pro 유료
- 창업자: 신병철 (현직 수학 교사)

슬라이드 구성:
1. 표지 (다크 배경, 큰 제목)
2. 문제 정의 (교사 업무 과부하 통계)
3. 솔루션 개요 (TeacherFlow 소개)
4. 제품 기능 상세
5-8. 핵심 기능 4가지 (양식채우기, 라이브제어, 성적분석, 노드에디터)
9. 기술 아키텍처
10. 차별화 포인트
11. 경쟁 분석
12-14. 사용 시나리오 3개 (Before/After 시간 비교)
15. 비즈니스 모델 (Free/Pro/School)
16. 로드맵
17. 팀 소개
18. 트랙션/현황
19. 투자 제안 (시드 3억)
20. 클로징

디자인:
- 앰버(#F59E0B)를 주 색상, 다크(#1F2037)를 보조
- 깔끔한 기업 스타일
- 통계 수치는 큰 폰트 + 색상 강조
- 각 슬라이드에 상단 앰버 라인
- 배경은 흰색 또는 다크
- 도형, 카드 UI 적극 활용

OUTPUT_PATH 변수를 사용하여 저장하세요."""

print("GPT-4.1 호출 중...")
response = client.chat.completions.create(
    model="gpt-4.1",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ],
    max_tokens=16000,
    temperature=0.7,
)

code = response.choices[0].message.content
# 코드 블록 추출
if "```python" in code:
    code = code.split("```python")[1].split("```")[0]
elif "```" in code:
    code = code.split("```")[1].split("```")[0]

output_path = os.path.join(os.path.dirname(__file__), "..", "data", "TeacherFlow_GPT41.pptx")

print(f"GPT-4.1 코드 생성 완료 ({len(code)}자)")
print("코드 실행 중...")

# OUTPUT_PATH 주입 후 실행
code = f'OUTPUT_PATH = r"{output_path}"\n' + code

try:
    exec(code, {"__builtins__": __builtins__})
    print(f"\nGPT-4.1 PPT 저장: {output_path}")
except Exception as e:
    print(f"\n실행 오류: {e}")
    # 디버그: 생성된 코드 저장
    debug_path = os.path.join(os.path.dirname(__file__), "ppt_gpt41_generated.py")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"생성된 코드 저장: {debug_path}")
    print("수동 디버그 필요")
