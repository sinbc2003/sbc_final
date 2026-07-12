# TeacherFlow — 교사 업무 자동화 노드 에디터

## 1. 프로젝트 개요

### 비전
교사들이 **코딩 없이** 자신의 업무를 자동화할 수 있는 데스크톱 앱.
Orange 3 / ComfyUI처럼 노드를 드래그&드롭으로 연결하여 워크플로우를 만들고,
문서 변환, 데이터 처리, AI 작문 등을 자동으로 처리한다.

### 핵심 가치
- **무료 배포**: 전국 교사에게 무료 제공
- **오프라인 동작**: 로컬 LLM으로 인터넷 없이 사용 가능
- **한국 교육 특화**: HWP/HWPX, NEIS, 공문 양식 등 네이티브 지원
- **데이터 플라이휠**: 사용할수록 데이터가 쌓이고, 모델이 개선되는 구조
- **최종 목표**: API 의존도 0 (완전한 로컬 AI)

### 최종 사용자
- 대한민국 고등학교/중학교/초등학교 교사
- IT 비전문가 (코딩 경험 없음)
- 노트북 사양: 2020년대 초반, Intel i5급, RAM 8GB, 저장 200GB, GPU 없음

### 프로젝트 소유자
- 신병철 (고등학교 수학 교사)
- 미션: "공교육의 반격을 통한 사교육 시장의 붕괴"
- 운영 중: http://edu-shin.com

---

## 2. 두 가지 모드

### 2-1. 설계 모드 (비주얼 노드 에디터)
교사가 직접 노드를 드래그&드롭으로 연결하여 워크플로우를 구성한다.
React Flow 기반의 비주얼 에디터. 자주 쓰는 조합은 프리셋으로 저장/공유 가능.

```
[PDF입력] → [PDF→MD변환] → [공문쓰기 LLM] → [MD→HWPX변환] → [결과.hwpx]
```

### 2-2. 채팅 모드 (자연어 → 자동 설계)
교사가 자연어로 업무를 설명하면, 오케스트레이터 LLM이 자동으로 노드 워크플로우를 설계하고 실행한다.

```
교사: "이번 달 각 학교에서 온 성적 파일 5개 합쳐서 NEIS 양식으로 만들어줘"
  → AI가 자동으로 [변환]→[표추출]→[매핑]→[병합]→[표준화]→[엑셀저장] 설계
  → "이렇게 처리할까요?" 확인 → 실행
```

### 모드 전환
두 모드는 앱 내에서 토글로 전환 가능. 채팅 모드에서 생성된 워크플로우는 설계 모드에서 수정 가능.

---

## 3. 아키텍처

### 3-1. 전체 구조

```
┌─ Tauri v2 (앱 껍데기, ~10MB, 메모리 ~30MB) ──────────────────┐
│                                                              │
│  ┌─ 프론트엔드: React + React Flow ────────────────────────┐  │
│  │  - 노드 에디터 UI (드래그&드롭)                           │  │
│  │  - 문서 미리보기 (빈칸 하이라이트)                         │  │
│  │  - 채팅 모드 UI                                         │  │
│  │  - 프리셋 관리                                          │  │
│  │  - 모드 전환 (설계 ⇄ 채팅)                               │  │
│  └──────────────────────────────────────────────────────┘  │
│                         │ HTTP/IPC                          │
│  ┌──────────────────────▼───────────────────────────────┐  │
│  │  Python 엔진 (sidecar, 1프로세스)                      │  │
│  │  ├── 노드 로더 (nodes/ 폴더 스캔, 자동 등록)             │  │
│  │  ├── 파이프라인 실행기 (연결 순서대로 execute 호출)        │  │
│  │  ├── 타입 체커 (입출력 호환 검증)                         │  │
│  │  ├── 메모리 관리자 (RAM 모니터링, 모델 자동 해제)          │  │
│  │  ├── LLM 관리자 (llama.cpp, LoRA 핫스왑)               │  │
│  │  └── 학습 데이터 수집기 (입출력 쌍, 교사 수정, 패턴)       │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 3-2. 기술 스택

| 레이어 | 기술 | 선택 이유 |
|--------|------|----------|
| 앱 껍데기 | **Tauri v2** | Electron 대비 설치 ~10MB(vs 150MB), 메모리 ~30MB(vs 200MB). 8GB RAM 노트북에 적합. 자동 업데이트 내장. Windows WebView2 사용 |
| 프론트엔드 | **React + React Flow** | 노드 에디터 검증된 라이브러리. 커뮤니티 크고 문서 풍부 |
| 백엔드/노드 실행 | **Python (sidecar)** | AI/ML 생태계(llama.cpp, pandas, openpyxl, odfpy, pyhwpx 등) 전부 Python. 기존 도구 3개 중 2개가 Python |
| LLM 런타임 | **llama.cpp** (C++ 바인딩) | GGUF 포맷 모든 모델 지원. LoRA 핫스왑 네이티브 지원. CPU 전용 추론 최적화. 메모리 효율적 |
| 로컬 모델 | **Gemma 2B Q3~Q4** (GGUF) | 8GB RAM에서 실행 가능. 한국어 지원. 양자화 수준은 RAM에 따라 자동 선택 |
| 노드 포맷 | **node.yaml + main.py** | 마메 ROM처럼 통일된 포맷. 폴더 하나 = 노드 하나. 자동 인식 |
| 데이터 처리 | **pandas** | 표 데이터 전처리, 변환, 병합 등 |

### 3-3. 디렉토리 구조

```
TeacherFlow/
├── src-tauri/                    # Tauri 앱 설정
│   └── tauri.conf.json           # 업데이터 설정 포함
├── src/                          # React 프론트엔드
│   ├── App.tsx
│   ├── components/
│   │   ├── NodeEditor/           # React Flow 노드 에디터
│   │   ├── ChatMode/             # 채팅 모드 UI
│   │   ├── PresetManager/        # 프리셋 관리
│   │   └── DocumentPreview/      # 문서 미리보기 (빈칸 하이라이트)
│   └── ...
├── engine/                       # Python 백엔드 엔진
│   ├── server.py                 # FastAPI 서버 (Tauri sidecar)
│   ├── loader.py                 # nodes/ 폴더 스캔, yaml 읽기, 노드 자동 등록
│   ├── runner.py                 # 파이프라인 실행기 (DAG 순서 실행)
│   ├── types.py                  # 데이터 타입 정의 (file, text, table, image, list)
│   ├── memory_manager.py         # RAM 모니터링, 모델 로드/언로드
│   ├── llm_manager.py            # llama.cpp 관리, LoRA 핫스왑
│   ├── training_logger.py        # 학습 데이터 자동 수집
│   ├── anonymizer.py             # 개인정보 마스킹
│   └── requirements.txt
├── nodes/                        # 노드 저장소 (ROM 폴더)
│   ├── pdf_to_md/
│   │   ├── node.yaml
│   │   └── main.py
│   ├── hwp_to_md/
│   ├── hwpx_to_md/
│   ├── xlsx_to_md/
│   ├── docx_to_md/
│   ├── odt_to_md/
│   ├── pdf_to_hwpx/
│   ├── md_to_hwpx/
│   ├── hwpx_fill/                # HWPX 양식 빈칸 감지 & 채우기
│   ├── xlsx_fill/                # 엑셀 양식 빈칸 감지 & 채우기
│   ├── odt_fill/                 # ODT 양식 빈칸 감지 & 채우기
│   ├── table_extract/            # 문서에서 표만 추출
│   ├── column_mapping/           # 컬럼명 통일
│   ├── data_clean/               # 공백/형식/타입 정리
│   ├── data_merge/               # 여러 표 → 하나
│   ├── data_filter/              # 조건부 행 추출
│   ├── data_split/               # 하나 → 여러 개
│   ├── data_standardize/         # 교육부/NEIS 표준 스키마 변환
│   ├── dedup/                    # 중복 제거
│   ├── stats_summary/            # 평균/합계/분포 계산
│   ├── llm_generate/             # 로컬 LLM 텍스트 생성
│   ├── llm_summarize/            # 요약
│   ├── llm_api/                  # 외부 API (Claude/GPT/Gemini)
│   ├── pdf_translate/            # PDF 번역
│   ├── save_hwpx/                # HWPX 저장
│   ├── save_xlsx/                # 엑셀 저장
│   ├── save_jsonl/               # JSONL 저장 (ML 학습용)
│   ├── save_parquet/             # Parquet 저장 (ML 학습용)
│   └── .../                      # 확장 (최종 100개 목표)
├── models/                       # LLM 모델 저장소
│   ├── base/
│   │   └── gemma-2b-q4.gguf     # 베이스 모델 1개
│   └── loras/                    # LoRA 어댑터 (모델별 폴더)
│       └── gemma-2b/
│           ├── 공문쓰기.gguf
│           ├── 상담일지.gguf
│           └── ...
├── data/                         # 사용자 데이터
│   ├── presets/                   # 저장된 프리셋
│   ├── workflows/                 # 저장된 워크플로우
│   └── training/                  # 학습 데이터 (자동 수집)
│       ├── node_pairs/            # 노드별 입출력 쌍
│       ├── workflows/             # 워크플로우 패턴
│       ├── corrections/           # 교사 수정 내역
│       └── schemas/               # 컬럼 매핑 사전
├── vendor/                        # 번들링된 외부 도구
│   └── kordoc/                    # kordoc CLI (당분간 Node.js, 추후 Python 포팅)
└── package.json / pyproject.toml
```

---

## 4. 노드 표준 스펙 (ROM 포맷)

모든 노드는 동일한 구조를 따른다. `nodes/` 폴더에 폴더 하나를 추가하면 앱이 자동으로 인식한다.

### 4-1. node.yaml

```yaml
id: pdf_to_md                          # 고유 ID (폴더명과 일치)
name: PDF → 마크다운                     # UI에 표시되는 이름
version: 1.0.0
category: 변환                          # 변환 | 전처리 | LLM | 출력 | 유틸
icon: file-text                         # UI 아이콘
author: 신병철

# 사람이 읽는 설명 + LLM 오케스트레이터가 읽는 설명
description: >
  PDF 문서를 마크다운 텍스트로 변환한다.
  표, 이미지, 텍스트를 구조적으로 추출하여
  후속 LLM 처리에 적합한 형태로 출력한다.

# 입력 포트
inputs:
  - name: 파일
    type: file
    accept: [.pdf]
    description: 변환할 PDF 파일

# 출력 포트
outputs:
  - name: 텍스트
    type: text
    description: 추출된 마크다운 텍스트

# 교사가 설정하는 파라미터 (노드 클릭 시 설정 패널)
params:
  - id: pages
    label: 페이지 범위
    type: string
    default: "전체"
    description: "예: 1-5, 3, 10-15"

# 리소스 요구사항
resource:
  requires_api: null                    # null | mathpix | openai | claude | gemini
  max_memory_mb: 200                    # 이 노드가 사용할 최대 메모리 (MB)
  estimated_time: fast                  # fast(<5초) | medium(<30초) | slow(>30초)

# 이 노드만의 추가 Python 패키지 (공유 라이브러리 외)
dependencies:
  - pymupdf>=1.25.0

# 오케스트레이터 LLM이 이 노드를 선택하는 기준 (Phase 3 채팅 모드용)
use_when:
  - PDF 문서의 내용을 읽어야 할 때
  - PDF를 다른 형식으로 변환하기 전 단계로
  - 문서에서 텍스트를 추출해야 할 때
```

### 4-2. main.py

```python
"""
모든 노드가 구현하는 표준 인터페이스.
execute() 함수 하나만 있으면 된다.
"""

def execute(inputs: dict, params: dict, context: dict) -> dict:
    """
    Args:
        inputs:  앞 노드에서 전달된 데이터
                 키는 node.yaml의 inputs[].name과 일치
        params:  교사가 설정한 파라미터
                 키는 node.yaml의 params[].id와 일치
        context: 앱 엔진이 제공하는 환경 정보
                 {
                     "temp_dir": str,          # 임시 파일 경로
                     "progress": Callable,      # 진행률 콜백 (0.0~1.0)
                     "log": Callable,           # 로그 출력
                     "llm": LLMManager,         # LLM 호출 (llm 노드용)
                     "config": dict,            # 앱 설정 (API 키 등)
                 }

    Returns:
        dict: 출력 데이터. 키는 node.yaml의 outputs[].name과 일치
    """
    pdf_path = inputs["파일"]
    pages = params.get("pages", "전체")

    # 진행률 표시 (선택적)
    context["progress"](0.1)

    # 실제 변환 로직 (기존 라이브러리 호출)
    md_text = convert_pdf_to_markdown(pdf_path, pages)

    context["progress"](1.0)

    return {"텍스트": md_text}
```

### 4-3. 데이터 타입 시스템

노드 간 연결은 타입이 일치해야 한다. 타입이 안 맞으면 UI에서 연결선이 그어지지 않는다.

```
file       — 파일 경로 (확장자로 세분화: .pdf, .hwp, .hwpx, .xlsx, .odt, .docx)
text       — 문자열 (마크다운, 플레인텍스트, JSON 텍스트)
table      — 표 데이터 (pandas DataFrame의 JSON 직렬화)
image      — 이미지 파일 경로
list       — 위 타입의 배열 (여러 파일, 여러 텍스트 등)
any        — 모든 타입 허용 (유틸 노드용)
```

### 4-4. 워크플로우 JSON 포맷

워크플로우는 JSON으로 직렬화/역직렬화 가능해야 한다.
이 포맷은 프리셋 저장, 공유, 그리고 Phase 3에서 오케스트레이터 LLM이 생성하는 대상이다.

```json
{
  "id": "workflow_abc123",
  "name": "공문 자동 작성",
  "version": "1.0.0",
  "description": "PDF 자료를 읽고 공문을 작성하여 HWPX로 저장",
  "created_at": "2026-04-09T10:30:00",
  "nodes": [
    {
      "id": "n1",
      "type": "pdf_to_md",
      "position": {"x": 100, "y": 200},
      "params": {"pages": "전체"}
    },
    {
      "id": "n2",
      "type": "llm_generate",
      "position": {"x": 400, "y": 200},
      "params": {
        "lora": "공문쓰기",
        "prompt_template": "다음 자료를 바탕으로 {{부서명}} 명의의 공문을 작성하라.\n\n[자료]:\n{{입력텍스트}}"
      }
    },
    {
      "id": "n3",
      "type": "md_to_hwpx",
      "position": {"x": 700, "y": 200},
      "params": {}
    }
  ],
  "edges": [
    {"from": "n1", "from_port": "텍스트", "to": "n2", "to_port": "입력텍스트"},
    {"from": "n2", "from_port": "출력텍스트", "to": "n3", "to_port": "텍스트"}
  ],
  "user_inputs": [
    {"node": "n2", "param": "부서명", "label": "부서명을 입력하세요", "type": "string"}
  ]
}
```

### 4-5. 워크플로우 중첩 (메가 워크플로우)

워크플로우 자체를 하나의 노드처럼 취급할 수 있다.

```yaml
# 워크플로우를 노드로 사용
id: 성적수집_워크플로우
name: 성적 수집 자동화
type: workflow                     # 일반 노드가 아닌 워크플로우 노드
inputs:
  - name: 성적파일들
    type: list
    accept: [.hwp, .hwpx, .pdf, .xlsx, .csv]
outputs:
  - name: 통합성적표
    type: file

contains:
  workflow_file: workflows/성적수집.json
```

이로써:
- Level 1: 노드 → 워크플로우 (단일 업무)
- Level 2: 워크플로우 → 메가 워크플로우 (프로젝트)
- Level 3: 종합 AI가 메가 워크플로우를 자동 설계 (최종 목표)

---

## 5. 기존 도구 래핑 계획

기존 코드는 수정하지 않는다. node.yaml + main.py 래퍼로 감싸기만 한다.

### 5-1. pdf2hwpx (Python)

**위치**: `Y:/완성 프로젝트/01_pdf2hwpx/`

**기능**: PDF → Mathpix OCR → MMD → HWPX (수식 포함 변환)

**핵심 API**:
```python
from packages.core.converter import convert_pdf, ConvertOptions
result = convert_pdf("exam.pdf", ConvertOptions(mode="hybrid", doc_type="exam"))
# result.mmd (마크다운), result.hwpx_path (HWPX 파일), result.tiptap_json
```

**노드 분리**:
| 노드 ID | 입력 | 출력 | API 필요 |
|---------|------|------|---------|
| `pdf_to_hwpx_math` | file(.pdf) | file(.hwpx) | Mathpix |
| `pdf_to_mmd` | file(.pdf) | text(mmd) | Mathpix |

**래핑 예시** (`nodes/pdf_to_hwpx_math/main.py`):
```python
import sys
sys.path.insert(0, "vendor/pdf2hwpx")
from packages.core.converter import convert_pdf, ConvertOptions

def execute(inputs, params, context):
    options = ConvertOptions(
        mode=params.get("mode", "hybrid"),
        doc_type=params.get("doc_type", "general"),
        output_hwpx=context["temp_dir"] + "/output.hwpx",
        app_id=context["config"].get("mathpix_app_id"),
        app_key=context["config"].get("mathpix_app_key"),
    )
    result = convert_pdf(inputs["파일"], options)
    return {"파일": result.hwpx_path}
```

### 5-2. kordoc (TypeScript/Node.js)

**위치**: `Y:/완성 프로젝트/02_kordoc/`

**기능**: HWP/HWPX/PDF/XLSX/DOCX → 마크다운, MD → HWPX, 문서 비교, 양식 필드 추출

**핵심 API**:
```typescript
import { parse, compare, extractFormFields, markdownToHwpx } from "kordoc"
const result = await parse("document.hwpx")  // result.markdown, result.blocks
const hwpxBuf = await markdownToHwpx("# 제목\n내용")  // ArrayBuffer
```

**CLI 인터페이스**:
```bash
npx kordoc document.hwpx                    # → stdout에 마크다운
npx kordoc report.hwp -o report.md           # → 파일 저장
npx kordoc *.pdf -d ./results/               # → 배치 변환
```

**노드 분리**:
| 노드 ID | 입력 | 출력 | API 필요 |
|---------|------|------|---------|
| `hwp_to_md` | file(.hwp) | text | 없음 |
| `hwpx_to_md` | file(.hwpx) | text | 없음 |
| `pdf_to_md` | file(.pdf) | text | 없음 |
| `xlsx_to_md` | file(.xlsx) | text | 없음 |
| `docx_to_md` | file(.docx) | text | 없음 |
| `md_to_hwpx` | text | file(.hwpx) | 없음 |
| `doc_compare` | file + file | text | 없음 |
| `form_extract` | file(.hwpx) | table | 없음 |

**래핑 방식**: Phase 1에서는 subprocess로 CLI 호출, Phase 2에서 Python 포팅 검토
```python
import subprocess, json

def execute(inputs, params, context):
    result = subprocess.run(
        ["npx", "kordoc", inputs["파일"], "--format", "json"],
        capture_output=True, text=True
    )
    parsed = json.loads(result.stdout)
    return {"텍스트": parsed["markdown"]}
```

**중요**: kordoc의 MD→HWPX는 현재 MVP (단락, 헤딩, 표만 지원, 스타일 없음).
양식 채우기가 필요한 경우, HWPX XML을 직접 조작하여 빈 셀만 채우는 별도 노드(`hwpx_fill`)를 구현해야 한다.

### 5-3. translate (Python)

**위치**: `Y:/완성 프로젝트/07_translate/`

**기능**: PDF 논문 번역 (overleaf: LaTeX 3단계 파이프라인, v6: 비전 에이전트)

**핵심 API**: Flask 웹서비스 (POST /translate)
```python
# engines/__init__.py에서 엔진 로드
from engines import load_engine
translate_fn = load_engine("overleaf")
# translate_fn(input_path, output_path, lang_out, model, pages, thread, callback, doc_type, compile_pdf)
```

**노드 분리**:
| 노드 ID | 입력 | 출력 | API 필요 |
|---------|------|------|---------|
| `pdf_translate` | file(.pdf) | file(.pdf) + file(.zip) | OpenAI + Mathpix(overleaf) |

**래핑 예시** (`nodes/pdf_translate/main.py`):
```python
import sys
sys.path.insert(0, "vendor/translate")
from engines import load_engine

def execute(inputs, params, context):
    engine = load_engine(params.get("engine", "overleaf"))
    output_path = context["temp_dir"] + "/translated"

    engine(
        input_path=inputs["파일"],
        output_path=output_path,
        lang_out=params.get("lang_out", "ko"),
        model=params.get("model", "gpt-4.1-mini"),
        pages=params.get("pages"),
        thread=params.get("threads", 4),
        callback=lambda msg: context["progress"](msg),
        doc_type=params.get("doc_type", "paper"),
        compile_pdf=params.get("compile_pdf", True),
    )
    return {"파일": output_path + ".pdf"}
```

---

## 6. 양식 빈칸 감지 & 채우기

교사 업무의 핵심: 기존 양식(HWP/XLSX/ODT)의 빈칸을 자동으로 감지하고 채우기.

### 6-1. 감지 원리

**XLSX**:
- `cell.value is None` → 빈 셀
- 헤더 행 감지 (텍스트 연속 채워진 행)
- 수식 셀 (`=SUM(...)`) → 건드리면 안 되는 곳
- 서식만 있는 셀 (테두리/배경색 있는데 값 없음) → 입력란
- 라이브러리: `openpyxl`

**HWPX**:
- XML 기반 (ZIP 풀면 `Contents/section0.xml`)
- `<hp:t></hp:t>` 또는 `<hp:t> </hp:t>` → 빈 텍스트 노드
- 누름틀(FormField) → 명시적 입력란 (가장 확실)
- 라벨 셀 옆의 빈 셀 → 입력란 추정
- 서식 정보(`charPrIDRef` 등)는 보존하고 텍스트만 교체

**ODT**:
- XML 기반 (ZIP 풀면 `content.xml`)
- 국제 표준(ODF)이라 라이브러리 풍부
- `odfpy` 라이브러리로 표/셀 접근
- HWPX와 동일한 원리로 빈 셀 감지

**구형 HWP**:
- 읽기는 kordoc으로 가능
- 쓰기는 불안정 → hwpx로 변환 후 처리
- `[구형.hwp] → [hwpx 변환] → [빈칸 감지&채우기] → [결과.hwpx]`

### 6-2. 채우기 흐름

```
문서 업로드 → 구조 분석(코드) → 빈칸 목록 → AI 의미 파악 → 매핑 제안 → 교사 확인 → 채우기
                                               ↑
                                     앞 노드에서 온 데이터와 매칭
```

### 6-3. HWPX 채우기 구현 원리

```xml
<!-- 원본: 서식 유지한 채 빈 텍스트만 교체 -->
<hp:tc>
  <hp:p>
    <hp:run charPrIDRef="5">       <!-- 글꼴/크기 설정 보존 -->
      <hp:t></hp:t>                <!-- 빈칸 → "국립과천과학관" -->
    </hp:run>
  </hp:p>
</hp:tc>
```

빈 텍스트 노드만 교체하므로 글꼴, 크기, 정렬 등 **원본 서식 100% 유지**.

---

## 7. LLM 관리

### 7-1. 로컬 LLM

- **런타임**: llama.cpp (GGUF 포맷)
- **베이스 모델**: Gemma 2B (양자화 수준은 RAM에 따라 자동 선택)
- **LoRA 핫스왑**: 베이스 모델 1개 + 작업별 LoRA 어댑터 교체

```
llama-server --model gemma-2b-q4.gguf --lora 공문쓰기.gguf   # 공문 모드
llama-server --model gemma-2b-q4.gguf --lora 상담일지.gguf   # 상담 모드
```

### 7-2. RAM 기반 자동 최적화

```
앱 시작 시 시스템 RAM 감지:

8GB  → Gemma 2B Q3 (1.2GB) + 컨텍스트 2048 토큰
12GB → Gemma 2B Q4 (1.5GB) + 컨텍스트 4096 토큰
16GB → Gemma 2B Q6 (1.8GB) + 컨텍스트 8192 토큰
```

### 7-3. 메모리 생명주기

```
[앱 대기] ~80MB
  → LLM 노드 실행 → 모델 로드 (~1.5GB) → 추론 → 완료 → 모델 해제
[앱 대기] ~80MB로 복귀
```

**쓸 때만 올리고, 끝나면 내림.**

### 7-4. 모델 교체 전략

- GGUF 포맷이면 어떤 모델이든 교체 가능 (파일 바꾸면 끝)
- **LoRA는 베이스 모델에 종속** (모델 바꾸면 LoRA 재학습 필요)
- **학습 데이터가 진짜 자산** — 데이터만 있으면 모델 바뀌어도 재학습 가능

### 7-5. LoRA vs 프롬프트 템플릿

Phase 1에서는 프롬프트 템플릿으로 시작 (모델 교체 영향 없음).
품질이 부족한 작업만 선별적으로 LoRA 추가.

```
Phase 1: 프롬프트 템플릿 (모델 무관, 빠르게 100개 노드 구현)
Phase 2: 품질 부족한 작업에만 LoRA (공문쓰기 등 양식 엄격한 것)
Phase 3: 데이터 축적 후 LoRA 재학습 자동화
```

### 7-6. API LLM

로컬 모델로 부족할 때 선택적으로 사용:
- Claude API
- OpenAI API
- Gemini API

API키가 없는 교사는 로컬 모델만 사용. 앱이 자동으로 로컬/API 전환.

---

## 8. 데이터 전처리 노드

교육 데이터 표준화를 위한 전용 노드 카테고리.

### 8-1. 노드 목록

| 노드 | 기능 | LLM 필요 |
|------|------|---------|
| `table_extract` | 문서에서 표 데이터만 추출 | 아니오 |
| `column_mapping` | 컬럼명 통일 ("학번"→"학생번호") | 제안만 (선택) |
| `data_clean` | 공백/형식/타입/단위 정리 | 아니오 |
| `data_merge` | 여러 표 → 하나로 병합 | 아니오 |
| `data_filter` | 조건부 행 추출 | 아니오 |
| `data_split` | 하나 → 학급별/과목별 분리 | 아니오 |
| `data_standardize` | NEIS/교육부 표준 스키마 변환 | 제안만 (선택) |
| `dedup` | 중복 데이터 제거 | 아니오 |
| `stats_summary` | 평균/합계/분포 계산 | 아니오 |

### 8-2. 컬럼 매핑 (AI 자동 제안)

```
원본 컬럼: ["학번", "성명", "국", "수"]
표준 컬럼: ["학생번호", "이름", "국어점수", "수학점수"]

LLM이 매핑 제안 → 교사가 확인 → pandas로 변환 실행
```

### 8-3. ML 학습용 출력 노드

데이터를 AI/딥러닝/기계학습 훈련에 적합한 형태로 저장하는 노드:

| 노드 | 출력 포맷 | 용도 |
|------|----------|------|
| `save_jsonl` | JSONL | instruction tuning, LoRA 학습 |
| `save_parquet` | Parquet | 대규모 분석, HuggingFace 호환 |
| `save_csv` | CSV | 범용 |
| `save_pairs` | 원본+결과 파일 쌍 | 파일 변환 모델 학습 |

---

## 9. 학습 데이터 자동 수집 (데이터 플라이휠)

### 9-1. 수집 대상

교사가 워크플로우를 실행할 때마다 자동으로 수집:

```
data/training/
├── node_pairs/                   # 노드별 입출력 쌍 (LoRA 재학습용)
│   └── 공문쓰기/
│       └── 2026-04-09_abc.jsonl
│       {"instruction": "...", "input": "...", "output": "..."}
│
├── workflows/                    # 워크플로우 패턴 (오케스트레이터 학습용)
│   └── 2026-04-09_def.jsonl
│   {"task": "...", "nodes_used": [...], "workflow_json": {...}}
│
├── corrections/                  # 교사가 AI 결과 수정한 것 (가장 귀중)
│   └── 2026-04-09_ghi.jsonl
│   {"node": "공문쓰기", "ai_output": "...", "teacher_corrected": "..."}
│
└── schemas/                      # 컬럼 매핑 패턴 (동의어 사전 자동 구축)
    └── neis_성적.json
```

### 9-2. 개인정보 마스킹

저장 전 자동 처리:
- 이름 → [학생A], [학생B]
- 학번 → [번호1], [번호2]
- 전화번호 → [연락처1]
- 주소 → [주소1]
- 주민번호 → 완전 삭제

**한계**: 맥락 속 간접 식별정보는 LLM도 놓칠 수 있음. 100% 마스킹 불가능.
교사에게 저장 전 검토 옵션 제공.

### 9-3. 수집 설정 UI

```
☑ 업무 결과를 학습 데이터로 저장
☑ 개인정보 자동 마스킹
☐ 원본도 함께 저장 (로컬에만)
```

### 9-4. 중앙 데이터 수집 (동의 기반)

```
각 교사 PC → (동의 후) → 중앙 서버 (edu-shin.com 또는 별도)
```

내보내기 표준 포맷:
```json
{
  "format_version": "1.0",
  "app_version": "0.3.0",
  "export_date": "2026-04-09",
  "anonymized": true,
  "consent": true,
  "teacher_id": "hashed_anonymous_id",
  "data": {
    "workflows": [],
    "node_pairs": [],
    "corrections": [],
    "schemas": []
  }
}
```

### 9-5. 데이터 활용 계획

| 데이터 | 활용 |
|--------|------|
| corrections (교사 수정) | LoRA 재학습 → 모델 품질 개선 |
| workflows (워크플로우 패턴) | 오케스트레이터 LLM 학습 → 채팅 모드 정확도 향상 |
| schemas (매핑 패턴) | "국=국어=국어점수" 동의어 사전 구축 |
| node_pairs (입출력 쌍) | 범용 교육 업무 AI 학습 |

**최종 목표**: 이 데이터로 학습된 모델이 API 없이 교사 업무 전체를 이해하고 자동화.

---

## 10. 업데이트 시스템

### 10-1. Tauri 자동 업데이트

```json
// tauri.conf.json
{
  "updater": {
    "active": true,
    "endpoints": ["https://edu-shin.com/app/updates/{{target}}/{{current_version}}"]
  }
}
```

### 10-2. 업데이트 종류

| 대상 | 방법 | 재시작 |
|------|------|--------|
| 앱 자체 (UI, 엔진) | Tauri 자동 업데이트 | 필요 |
| 도구 노드 추가/수정 | 핫 업데이트 (노드 파일만 다운) | 불필요 |
| LoRA 모델 추가 | 모델 마켓 (필요한 것만 다운) | 불필요 |
| 베이스 모델 교체 | 별도 다운로드 | 필요 |

### 10-3. 배포 인프라

GitHub Releases (무료):
- 앱 설치파일 (.msi)
- 노드 팩 (zip)
- LoRA 모델

---

## 11. 보안

```
1. 데이터 로컬 처리 기본
   - 로컬 도구/LLM은 네트워크 사용 안 함
   - API 호출 시에만 데이터 전송 + 사전 알림

2. API 키 안전 보관
   - Windows Credential Manager 사용
   - 평문 저장 금지

3. 노드 검증
   - 공식 노드: 서명된 패키지만 자동 설치
   - 커뮤니티 노드: 설치 시 경고

4. 학생 개인정보
   - 처리 결과 임시파일 자동 삭제
   - LLM 전송 시 마스킹 옵션
   - 학습 데이터 저장 시 자동 익명화
```

---

## 12. 구현 순서 및 진행 상태

### Phase 1 — 엔진 + 노드 표준 (MVP) ✅ 완료 (2026-04-09)

**목표**: 노드 3개를 연결해서 CLI에서 파이프라인 1개 돌리기

```
✅ 1-1. 노드 표준 스펙 확정 (이 문서의 섹션 4)
✅ 1-2. 워크플로우 JSON 포맷 확정 (이 문서의 섹션 4-4)
✅ 1-3. 엔진 구현
        - loader.py: nodes/ 폴더 스캔, node.yaml 파싱, 노드 자동 등록
        - runner.py: 워크플로우 JSON 읽고 DAG 위상정렬 순서로 execute() 호출
        - types.py: 6종 타입 정의, 입출력 호환성 검증
        - memory_manager.py: RAM 프로필, 양자화(Q3/Q4/Q6) 자동 선택
        - llm_manager.py: local(llama.cpp)/claude/openai/gemini 통합 관리
✅ 1-4. 기존 도구 래핑 (3개)
        - pdf_to_md: kordoc CLI → fallback pymupdf 자동 전환
        - llm_generate: 프롬프트 템플릿 {{변수}} 치환 + 멀티 프로바이더
        - md_to_hwpx: kordoc CLI → fallback 내장 HWPX XML 빌더
✅ 1-5. CLI 테스트
        - python run_pipeline.py workflow.json (--list-nodes, --info, --output-dir)
        - PDF→MD→HWPX E2E 파이프라인 동작 확인 (0.1초)
```

**구현 결과물:**
- `engine/` — types.py, loader.py, runner.py, memory_manager.py, llm_manager.py
- `nodes/` — pdf_to_md/, llm_generate/, md_to_hwpx/ (각 node.yaml + main.py)
- `run_pipeline.py`, `sample_workflow.json`

---

### Phase 2 — 앱 UI ✅ 완료 (2026-04-09)

**목표**: 교사가 실제로 쓸 수 있는 데스크톱 앱

```
✅ 2-1. Tauri v2 + React 프로젝트 셋업
        - Vite 6 + React 18 + TypeScript + Tailwind CSS 3
        - @xyflow/react v12 (React Flow)
        - Zustand 상태관리
        - src-tauri/ (Cargo.toml, tauri.conf.json, capabilities)
✅ 2-2. React Flow 노드 에디터 (설계 모드)
        - 커스텀 노드: 왼쪽 카테고리 바, 아이콘, 타입 배지, 상태(idle/running/done/error)
        - 커스텀 엣지: 소스 포트 타입 기반 색상, 실행 중 애니메이션
        - 연결 시 타입 호환성 실시간 검증
        - 미니맵, 줌 컨트롤, 도트 배경, Delete 키 삭제
✅ 2-3. 채팅 모드 UI
        - 예시 프롬프트, 메시지 버블, 엔진 서버 연동
        - (채팅→워크플로우 자동 생성은 Phase 3)
✅ 2-4. 모드 전환 (설계 ⇄ 채팅) 토글
✅ 2-5. 워크플로우 저장/관리 시스템
        - engine/storage.py: 파일 기반 CRUD, 자동저장(5개), 히스토리(100개), 프리셋
        - API 18개 엔드포인트: /api/workflows, /api/autosave, /api/history 등
        - WorkflowManager 모달: 목록/검색/복제/삭제/내보내기/가져오기
        - Ctrl+S 저장, 자동저장(30초), dirty 추적, 이름 표시
        - 프리셋 저장/불러오기
⬜ 2-6. 문서 미리보기 (빈칸 하이라이트) — 미구현
⬜ 2-7. 설정 화면 (API 키, 모델 선택, 메모리 설정) — 미구현
⬜ 2-8. 도구 노드 확장 (현재 3개 실구현 / 12개 UI 표시)
        - ⬜ 변환 노드 전체 (hwp, hwpx, xlsx, docx, odt → 마크다운)
        - ⬜ 전처리 노드 (표추출, 매핑, 정제, 병합, 필터, 분할, 표준화)
        - ⬜ 빈칸 감지&채우기 노드 (hwpx_fill, xlsx_fill, odt_fill)
        - ⬜ 출력 노드 (save_xlsx, save_jsonl, save_parquet)
⬜ 2-9. 자동 업데이트 설정 — 미구현
```

**구현 결과물:**
- `src/` — App.tsx, store.ts, types.ts, constants.ts, index.css
- `src/components/` — Layout, Toolbar, NodePalette, FlowCanvas, PropertiesPanel, ChatMode, StatusBar, WorkflowManager
- `src/components/nodes/` — CustomNode, CustomEdge
- `engine/server.py` — FastAPI 18개 엔드포인트 (포트 8321)
- `engine/storage.py` — 파일 기반 데이터 저장소
- `src-tauri/` — Tauri v2 설정
- 빌드: 394KB JS + 44KB CSS (2.4초)
- 디자인: Orange3 스타일 라이트 테마

---

### Phase 3 — 지능화 ⬜ 미착수

**목표**: 채팅으로 자동 워크플로우 설계 + 데이터 플라이휠

```
⬜ 3-1. 학습 데이터 수집기 (training_logger.py)
⬜ 3-2. 개인정보 마스킹 (anonymizer.py)
⬜ 3-3. 오케스트레이터 LLM (node.yaml의 description + use_when 기반)
⬜ 3-4. 중앙 데이터 수집 (동의 기반 내보내기)
⬜ 3-5. 축적 데이터로 LoRA 개선
⬜ 3-6. 워크플로우 중첩 (메가 워크플로우)
⬜ 3-7. 도구 100개 + 커뮤니티 템플릿 공유
⬜ 3-8. API 의존도 점진적 축소
```

---

## 13. 리스크 & 솔직한 한계

| 영역 | 리스크 | 대응 |
|------|--------|------|
| 구형 HWP 쓰기 | 서식 깨질 수 있음 | HWPX 변환 후 처리, hwpx로 출력 |
| 개인정보 마스킹 | 100% 불가능 (간접 식별정보) | 교사 검토 단계 필수 |
| 채팅→워크플로우 정확도 | 노드 100개 중 정확한 조합 고르기 어려움 | 교사 확인 후 실행, 데이터 축적으로 개선 |
| API 의존도 0 | 현재 로컬 2B 모델로는 복잡한 추론 부족 | 모델 발전 속도에 의존, 장기 목표로 열어둠 |
| 8GB RAM에서 LLM | 다른 프로그램과 동시 사용 시 빠듯함 | 자동 양자화 선택, 사용 후 즉시 해제 |
| kordoc MD→HWPX | 현재 MVP (스타일 없음) | 양식 채우기는 XML 직접 조작으로 별도 구현 |

---

## 14. 용량 & 성능 예측

### 설치 용량

```
Tauri 앱 ··············  ~10MB
Python 런타임 ··········  ~80MB
공유 라이브러리 ·········  ~120MB
노드 100개 코드 ········  ~5MB
kordoc (Node.js) ······  ~150MB  (Python 포팅 후 제거)
llama.cpp 엔진 ········  ~30MB
Gemma 2B Q4 모델 ······  ~1.5GB
LoRA 10개 ·············  ~300MB
─────────────────────────────
합계: ~2.2GB  (200GB 중 ~1.8%)
```

### RAM 사용

```
대기 시: ~80MB (Tauri 30MB + Python 50MB)
도구 실행 시: ~280MB
LLM 실행 시: ~2.1GB (모델 1.5GB + 추론 300MB + 앱 300MB)
```

---

## 15. 핵심 설계 원칙

1. **노드 = 함수**: `execute(inputs, params, context) → outputs`. 이것만 지키면 됨
2. **ROM 포맷**: 모든 노드가 동일한 구조 (node.yaml + main.py). 폴더 추가 = 노드 추가
3. **타입 안전**: 입출력 타입이 맞아야 연결 가능. 안 맞으면 UI에서 차단
4. **온디맨드 로딩**: LLM은 쓸 때만 로드, 끝나면 해제
5. **로컬 우선**: 기본은 오프라인 동작. API는 선택적 확장
6. **데이터 우선**: 모든 실행 결과를 학습 데이터로 축적
7. **점진적 확장**: Phase 1(엔진) → Phase 2(UI) → Phase 3(지능화)
8. **기존 코드 보존**: 래퍼로 감싸기만, 기존 도구 수정하지 않음
9. **Python 통일**: 노드 언어는 Python으로 통일 (kordoc만 당분간 CLI 호출)
10. **워크플로우 = JSON**: 저장, 공유, LLM 생성 모두 JSON 포맷

---

## 부록 A: 기존 도구 상세 분석

### A-1. pdf2hwpx

- **위치**: `Y:/완성 프로젝트/01_pdf2hwpx/`
- **언어**: Python (FastAPI) + Next.js (편집기)
- **파이프라인**: PDF → Mathpix OCR → MMD → IR(Pydantic) → HWPX(ZIP/XML)
- **핵심 모듈**:
  - `packages/core/converter.py` — 메인 변환 엔진 (`convert_pdf()`)
  - `packages/extractor/mathpix_client.py` — Mathpix API 클라이언트
  - `packages/extractor/mmd_parser.py` — MMD → DocumentIR 파서
  - `packages/core/hwpx_generator/` — IR → HWPX XML 빌더 + ZIP 패키저
  - `packages/core/equation_converter/rules.py` — LaTeX ↔ 한컴수식 변환
  - `packages/core/ir/schema.py` — DocumentIR Pydantic 스키마
- **외부 API**: Mathpix OCR (환경변수 `MATHPIX_APP_ID`, `MATHPIX_APP_KEY`)
- **모드**: hybrid(권장), pdf, image
- **CLI**: `python cli.py convert-pdf input.pdf --mode hybrid -o output.hwpx`

### A-2. kordoc

- **위치**: `Y:/완성 프로젝트/02_kordoc/`
- **언어**: TypeScript/Node.js
- **배포**: npm 패키지 (`npx kordoc`)
- **지원 포맷**: HWP(레거시, 암호화 포함), HWPX, PDF, XLSX, DOCX
- **핵심 기능**:
  - `parse()` — 모든 포맷 → 마크다운 + IRBlock[]
  - `compare()` — 두 문서 비교 (신구대조표)
  - `extractFormFields()` — 양식 필드 추출
  - `markdownToHwpx()` — MD → HWPX (MVP: 단락/헤딩/표만, 스타일 없음)
  - `detectFormat()` — 파일 타입 자동 감지
- **특수 기능**: HWP AES-128 복호화, 손상 파일 복구, 2단 PDF 레이아웃 감지
- **MCP 서버**: Claude/Cursor 연동 (7개 도구)
- **외부 API**: 없음 (완전 로컬)

### A-3. translate

- **위치**: `Y:/완성 프로젝트/07_translate/`
- **언어**: Python (Flask)
- **엔진 2개**:
  - overleaf: Mathpix(PDF→LaTeX) → 3단계(요약→용어집→번역) → ZIP+PDF
  - v6: 비전 에이전트 (AI가 페이지 이미지 직접 보고 번역) → PDF
- **외부 API**: OpenAI (번역 LLM), Mathpix (overleaf 엔진만)
- **인터페이스**: Flask 웹서비스 (POST /translate, GET /status, GET /download)
- **포트**: 5007
- **비동기**: threading (데몬 스레드)

---

## 11. 2026-04-10 세션 추가 아키텍처

### 11-1. 3모드 시스템

```
AppMode = "design" | "chat" | "manager"

설계 모드: NodePalette + FlowCanvas + PropertiesPanel + ExecutionPanel
채팅 모드: ChatMode (GPT-4.1 워크플로우 자동 생성)
관리 모드: WorkflowManagerPage (전체 페이지, 미니 플로우차트)
```

Toolbar에 3버튼 토글. 폴더 아이콘 클릭도 관리 모드로 이동.

### 11-2. 채팅 워크플로우 생성 (engine/chat_handler.py)

```
사용자 메시지 → build_system_prompt(노드 카탈로그 + 프리셋 예시)
→ GPT-4.1 (generate_chat, 멀티턴)
→ parse_workflow_response (JSON 추출 + 위치 자동 레이아웃)
→ store.save_workflow
→ 프론트엔드: ChatWorkflowPreview (미니 플로우차트 + "설계모드에서 열기")
```

ChatRequest에 history 필드 추가. 응답: {reply, workflow_id, workflow_json}.

### 11-3. 긴 문서 자동 청킹 (map-reduce)

llm_generate 노드에서 입력 텍스트 > 8000자일 때:
1. 6000자 청크 + 300자 겹침으로 분할
2. 각 청크에 동일 프롬프트 적용
3. 결과 합치기
4. "요약" 키워드 있으면 최종 통합 요약까지

테스트: 60,444자 HWPX → 11청크 → 1,353자 통합 요약 (108초).

### 11-4. MiniFlowChart (SVG)

워크플로우 카드에 노드 연결 시각화. React Flow 인스턴스 없이 순수 SVG.
- 노드: 카테고리 색상 원 (흰 테두리)
- 엣지: 회색 선 + 화살표 마커
- 위치 정규화: 모든 노드 위치를 SVG 영역에 맞게 스케일
- thumbnail_data: storage.py에서 save/load 시 자동 생성

### 11-5. 출력 파일 관리

- /api/files/open: OS 기본 앱으로 파일 열기 (Windows: os.startfile)
- /api/files/open-folder: 파일 탐색기에서 해당 위치 열기 (explorer /select,)
- 설정 > 일반 > output_dir: 출력 파일 자동 저장 경로 (기본: 바탕화면)
- runner.py: 실행 완료 후 파일 출력을 지정 경로로 자동 복사

### 11-6. pypandoc-hwpx 통합

MD→HWPX 변환 우선순위: pypandoc-hwpx > kordoc > 내장 빌더.
전처리 (github.com/msjang/pypandoc-hwpx/issues/1):
1. 빈 표 셀 → . 삽입 (한/글 크래시 방지)
2. 리스트 마커 → 가운뎃점 (1pt 버그)
3. 직선 따옴표 → 유니코드 꺾은따옴표 (텍스트 소실 방지)
4. SMP 이모지 제거 (한/글 XML 파서 한계)

### 11-7. 분기형 프리셋 워크플로우

| # | 이름 | 노드 | 엣지 | 구조 |
|---|------|------|------|------|
| 1 | PDF 요약+번역 분기 | 6 | 6 | 1→1→2분기→합류→1 |
| 2 | 다중 파일 병합 보고서 | 9 | 8 | 3병렬→합류→1→1 |
| 3 | 상담일지 분류 분기 | 7 | 7 | 1→1→1→2분기→합류→1 |
| 4 | RAG 기반 자료 조사 | 7 | 5 | 2병렬→RAG→1→1 |
| 5 | 성적 통합 이중 출력 | 11 | 10 | 3병렬→합류→2분기→각각 출력 |

### 11-8. pdf2hwpx 통합 (수식 변환)

`vendor/pdf2hwpx/` (365KB)에 핵심 모듈만 내장. 원본 `01_pdf2hwpx/` 수정 없음.

구조:
```
vendor/pdf2hwpx/
├── packages/
│   ├── core/           # 변환 엔진, 수식 변환기, HWPX 생성기
│   │   ├── converter.py      # convert_pdf() 메인 함수
│   │   ├── pipeline.py       # ir_to_hwpx(), latex_text_to_hwpx()
│   │   ├── equation_converter/  # LaTeX↔한컴 수식 (100+ 연산자)
│   │   ├── hwpx_generator/     # SectionBuilder, Packager
│   │   └── ir/                  # DocumentIR 중간 표현
│   └── extractor/      # Mathpix API, MMD 파서
```

수식 노드 3개:
- `pdf_to_hwpx_math`: PDF → Mathpix OCR → LaTeX → 한컴수식 → HWPX (API 필요)
- `latex_to_hwpx`: LaTeX 텍스트 → 한컴수식 HWPX (API 불필요)
- `latex_to_hwp_eq`: LaTeX↔한컴 수식 양방향 텍스트 변환 (API 불필요)

### 11-9. 이식성

프로젝트 전체를 다른 경로로 이동해도 동작한다.
- 모든 경로가 `__file__` 기준 상대 경로
- 절대 경로 하드코딩 없음
- vendor/ 내장으로 외부 프로젝트 의존 없음
- `data/` 폴더는 런타임 자동 생성

### 11-10. HWP COM 제어 아키텍처 (pyhwpx 기반)

**모듈**: `engine/hwp_controller.py`

```
HwpController (싱글톤)
├── connect()          → Hwp(visible=True), 기존 연결 재활용
├── extract_cvd()      → DocumentScanner.scan() → BlockManager.initialize_from_scan()
├── execute()          → HwpEditor.replace_cell_content() 등 14개 명령
└── read_text()        → init_scan + get_text 루프 (위치 추적 없음)

DocumentScanner
└── scan()             → init_scan(0x07, 0x77) → get_text + move_pos(201) + get_pos + is_cell 루프
                         list_id > 0 또는 is_cell()이면 표 셀 (td)

BlockManager
├── initialize_from_scan()  → block_id 부여 (100, 102, 104, ...)
├── get_position(block_id)  → (list_id, para_id, char_pos) 반환
└── to_cvd_text()           → LLM 프롬프트용 블록 텍스트

HwpEditor
├── replace_cell_content()  → set_pos → is_cell 확인 → SelectAll → insert_text
├── replace_paragraph()     → set_pos → MoveParaBegin → MoveSelParaEnd → insert_text
└── ... (14개 편집 명령)
```

**핵심 주의사항**:
- **gencache 초기화 필수**: 서버 startup에서 `win32com.client.gencache` 경로를 삭제해야 `get_pos()`가 정상 작동 (stale 캐시 → list_id=0 반환 버그)
- **block_id는 스캔 세션 한정**: 리스캔 시 ID가 재할당됨. 스캔→LLM→편집은 한 세션에서 수행
- **COM 단일 스레드**: `_com_pool` (ThreadPoolExecutor max_workers=1)에서만 COM 호출
- **Windows 좀비 TCP**: 서버 종료 후 포트가 해제되지 않을 수 있음 → `ENGINE_PORT` 환경변수로 포트 변경

## 12. 2026-04-13 세션 — COM 연결 개선 + 채팅 FormAssist

### 12-1. 채팅 모드 FormAssist 자동 라우팅

채팅에서 양식 파일 첨부+수정 의도 → FormAssist 3-phase 파이프라인 자동 호출.

```
사용자: [정산서.xlsx 첨부] "김준영 팀으로 채워줘"
→ detect_form_intent() = True (양식 확장자 + 의도 키워드)
→ chat_handler → _handle_form_assist_chat() → run_form_assist()
→ form_extract (lxml 폴백) → LLM → form_fill (lxml 폴백)
→ 결과 파일 반환 (MessageBubble에 "양식 채우기 완료" 카드)
```

**파일**: `engine/chat_handler.py` (detect_form_intent, extract_file_paths), `engine/routes/chat.py` (_handle_form_assist_async), `src/components/chat/MessageBubble.tsx`

### 12-2. Excel openpyxl 크래시 lxml 폴백

일부 xlsx 파일에서 openpyxl `_cell_styles` IndexError 발생 → lxml으로 직접 XML 파싱.

- `nodes/form_extract/main.py`: `_extract_xlsx_raw()` — ZIP 내 sharedStrings/sheet XML 직접 파싱
- `nodes/form_fill/main.py`: `_fill_xlsx_raw()` — inlineStr 타입으로 셀 값 주입

### 12-3. COM 유령 인스턴스 정리 + subprocess 실행

`live_controller.py` connect 로직 전면 개편:

```
connect(app_type):
  1. 기존 연결 유효? → 재사용
  2. 기존 연결이 유령(Visible=False, 문서0)? → Quit() 후 삭제
  3. GetActiveObject → 유효한 인스턴스만 사용 (유령이면 Quit)
  4. subprocess.Popen으로 앱 실행 → GetActiveObject 재시도 (최대 5초)
  5. 최후 수단: Dispatch
```

**핵심**: subprocess로 시작한 앱은 COM 참조와 독립 → 서버 `--reload` 시에도 앱 유지.

### 12-4. 앱별 문서 목록 드롭다운

기존 HWP 전용 드롭다운을 모든 앱(Excel/PPT/Word)으로 일반화.

- **API**: `GET /api/live/documents/{app}`, `POST /api/live/documents/{app}/activate`
- **프론트**: `appDocuments: Record<string, AppDoc[]>`, `selectedDocIndex: Record<string, number>`
- **detect**: 연결된 앱의 문서 목록을 자동 포함

### 12-5. 죽은 연결 자동 정리

`routes/live.py` detect에서:
- 프로세스 없으면 `_connections`에서 제거
- `list_documents` RPC 오류 시 연결 해제 + connected=false 반환

### 12-6. Office 라이선스 제한 사항

이 기기의 Office가 "제품 활성화되지 않은 제품" 상태:
- **Excel**: COM 접근 가능하지만 GetActiveObject가 유령 인스턴스를 반환하는 경우 있음 → subprocess 방식으로 우회 성공
- **Word**: 자동 종료됨 (라이선스 미활성 시 COM으로 시작한 Word가 수초 내 자동 종료). 라이선스 활성화 필요
- **PPT**: 정상 동작

### 12-7. HWP 문서 스캔 구조 정보 부재 (개선 필요)

현재 `hwp_controller.py`의 `DocumentScanner.scan()`은 COM 커서 순회(`init_scan` + `TableRightCell`) 방식으로 텍스트만 수집한다. 다음 구조 정보가 누락됨:

| 누락 정보 | 영향 |
|---|---|
| 셀 병합 (rowSpan/colSpan) | LLM이 병합 셀을 인식 못함 → 양식 편집 오류 |
| 표 크기 (행×열) | 표 구조 파악 불가 |
| 셀 너비/높이 | 레이아웃 판단 불가 |
| 글자/단락 서식 | 서식 보존 편집 불가 |

**개선 방안**: COM `SaveAs`로 임시 HWPX 저장 → ZIP 내 `content.xml` 파싱(HWPML)으로 구조 정보 보강하는 하이브리드 방식.

```
현재:  COM 커서 순회 → CVD (텍스트만)
개선:  COM 커서 순회 → CVD (텍스트)
       + HWPX XML 파싱 → 병합/크기/서식 정보 보강
```

특히 양식 문서(생기부, 성적표, 공문)처럼 셀 병합이 복잡한 문서에서 현재 방식은 정확도가 크게 떨어짐. HWPML의 `<hp:tc>` → `<hp:cellSpan colSpan="N" rowSpan="M"/>` 속성으로 병합 정보를 정확히 파악 가능.
