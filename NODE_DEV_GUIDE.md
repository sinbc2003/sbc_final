# TeacherFlow 노드 개발 가이드

> 이 문서는 새 노드(도구)를 만들려는 개발자를 위한 표준 스펙입니다.

## 구조

```
nodes/
└── 노드ID/
    ├── node.yaml      ← 메타데이터 (필수)
    ├── main.py        ← 실행 코드 (필수)
    └── requirements.txt  ← 추가 의존성 (선택)
```

폴더를 `nodes/`에 넣으면 앱이 **자동으로 인식**합니다. 재시작만 하면 됩니다.

---

## node.yaml 스펙

```yaml
id: my_node                           # 고유 ID (폴더명과 일치, 영문 snake_case)
name: 내 노드                          # UI에 표시되는 이름 (한글 OK)
version: 1.0.0                         # 시맨틱 버전
category: 변환                          # 변환 | 전처리 | LLM | 출력 | 유틸
icon: file-text                         # lucide-react 아이콘 이름
author: 홍길동                          # 제작자

description: >
  이 노드가 무엇을 하는지 한 문단으로 설명.
  채팅 모드에서 AI가 이 설명을 읽고 노드를 선택합니다.

# 입력 포트 (앞 노드에서 받는 데이터)
inputs:
  - name: 파일                          # 포트 이름 (한글 가능)
    type: file                          # file | text | table | image | list | any
    accept: [.pdf, .hwpx]              # file 타입일 때 허용 확장자 (선택)
    description: 변환할 PDF 파일

# 출력 포트 (다음 노드로 보내는 데이터)
outputs:
  - name: 텍스트
    type: text
    description: 추출된 마크다운 텍스트

# 사용자 설정 파라미터 (노드 클릭 시 속성 패널에 표시)
params:
  - id: pages                           # 파라미터 ID (영문 snake_case)
    label: 페이지 범위                   # UI 라벨
    type: string                         # string | text | integer | float | select | boolean
    default: "전체"                      # 기본값
    description: "예: 1-5, 3, 10-15"    # 도움말
    options: ["옵션1", "옵션2"]          # type=select일 때만

# 리소스 요구사항 (선택)
resource:
  requires_api: null                     # null | openai | claude | gemini | mathpix
  max_memory_mb: 200
  estimated_time: fast                   # fast(<5초) | medium(<30초) | slow(>30초)

# 추가 Python 패키지 (선택)
dependencies:
  - pymupdf>=1.25.0

# AI가 이 노드를 선택하는 힌트 (채팅 모드용)
use_when:
  - PDF 문서의 내용을 읽어야 할 때
  - 문서에서 텍스트를 추출해야 할 때
```

---

## main.py 스펙

```python
def execute(inputs: dict, params: dict, context: dict) -> dict:
    """
    Args:
        inputs:  앞 노드에서 전달된 데이터
                 키 = node.yaml의 inputs[].name
                 값 = 문자열, 리스트, 딕셔너리 등
                 
        params:  사용자가 설정한 파라미터
                 키 = node.yaml의 params[].id
                 값 = 사용자 입력값 (없으면 default)
                 
        context: 앱이 제공하는 환경
                 {
                     "temp_dir": str,           # 임시 파일 저장 경로
                     "progress": Callable,       # 진행률 (0.0~1.0)
                     "log": Callable,            # 로그 메시지 (str 1개)
                     "llm": LLMManager | None,   # LLM 호출 (LLM 노드용)
                     "config": dict,             # 앱 설정
                 }

    Returns:
        dict: 출력 데이터
              키 = node.yaml의 outputs[].name
              값 = 다음 노드에 전달할 데이터
    """
    # 1. 입력 가져오기
    file_path = inputs["파일"]
    pages = params.get("pages", "전체")

    # 2. 진행률 표시 (UI에 반영됨)
    context["progress"](0.1)

    # 3. 로그 (실행 패널에 표시, 한글로 쓰세요)
    context["log"]("문서 읽는 중...")

    # 4. 실제 처리
    result = do_something(file_path, pages)

    # 5. 완료
    context["progress"](1.0)
    context["log"](f"완료 ({len(result)}자)")

    # 6. 출력 반환 (키 = outputs[].name)
    return {"텍스트": result}
```

---

## 데이터 타입

| 타입 | 설명 | Python 값 |
|------|------|----------|
| `file` | 파일 경로 | `str` (절대 경로) |
| `text` | 텍스트 | `str` |
| `table` | 표 데이터 | `list[dict]` 또는 JSON 문자열 |
| `image` | 이미지 경로 | `str` |
| `list` | 위 타입의 배열 | `list` |
| `any` | 모든 타입 | 아무거나 |

### 중요: table 타입은 JSON 문자열로 올 수 있음

앞 노드에서 `table` 데이터가 JSON 문자열로 전달될 수 있습니다.
반드시 파싱 처리를 해주세요:

```python
import json

table_data = inputs["표데이터"]
if isinstance(table_data, str):
    table_data = json.loads(table_data)
```

---

## LLM 호출

LLM 노드는 `context["llm"]`을 통해 AI를 호출합니다:

```python
llm = context["llm"]

# 단일 프롬프트
result = llm.generate(
    prompt="질문",
    max_tokens=2048,
    temperature=0.7,
    provider="auto",     # auto | local | claude | openai | gemini
    model=None,          # 특정 모델 지정 (예: "gpt-4.1")
)

# 멀티턴 대화
result = llm.generate_chat(
    messages=[
        {"role": "system", "content": "시스템 프롬프트"},
        {"role": "user", "content": "사용자 질문"},
    ],
    provider="openai",
    model="gpt-4.1",
)
```

---

## 에러 처리

- `raise FileNotFoundError("파일 없음: ...")` → 파일 관련 에러
- `raise ValueError("...")` → 입력값 에러
- `raise RuntimeError("...")` → 실행 에러
- 에러 메시지는 **한글로** (교사가 읽음)

---

## 파일 출력

출력 파일은 `context["temp_dir"]`에 저장하세요. 앱이 자동으로 사용자의 저장 경로(바탕화면 등)로 복사합니다.

```python
import os
output_path = os.path.join(context["temp_dir"], "결과.hwpx")
# ... 파일 생성 ...
return {"파일": output_path}
```

---

## 카테고리별 예시

### 변환 노드 (입력 파일 → 텍스트)
`pdf_to_md`, `hwpx_to_md`, `xlsx_to_md`, `url_to_md`

### 전처리 노드 (텍스트/표 가공)
`table_extract`, `text_split`, `data_merge`, `column_mapping`

### LLM 노드 (AI 처리)
`llm_generate`, `llm_summarize`, `llm_translate`, `llm_classify`

### 출력 노드 (결과 파일 생성)
`md_to_hwpx`, `md_to_docx`, `save_xlsx`

### 유틸 노드 (입력/연결)
`file_input`, `text_input`, `text_template`

---

## 테스트

```bash
# 엔진 서버 실행
python -m engine.server

# API로 노드 단독 테스트
curl -X POST http://127.0.0.1:8321/api/run \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test", "name": "test", "version": "1.0.0",
    "nodes": [{"id": "n1", "type": "내노드ID", "position": {"x":0,"y":0}, "params": {}}],
    "edges": [],
    "initial_inputs": {"n1": {"입력포트명": "값"}}
  }'
```

---

## 배포 (마켓플레이스)

노드 폴더를 ZIP으로 압축하면 마켓플레이스에서 설치 가능:
```
my_node.zip
├── node.yaml
├── main.py
└── requirements.txt (선택)
```

`/api/nodes/install/{node_id}` API로 원격 설치도 지원됩니다.
