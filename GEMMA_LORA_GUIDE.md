# Gemma LoRA 작업 가이드 — 감사에서 확보한 설계도

> 작성: 2026-07-08 / 프로젝트: TeacherFlow (sbc_final)
> 목적: **§14 노드/워크플로우 감사 + 견고화(§15, 10커밋)** 과정에서 확보한 "소형 모델을 실제로 어떻게 쓰는가"를 정리해, 나중에 **Gemma LoRA 증류(§8 3단계)** 를 바로 시작할 수 있게 한다.
> 이 문서만 읽고 LoRA 학습 데이터 설계 → 학습 → 배선 → 검증까지 이어갈 수 있게 작성.
> 상위 맥락: `LOCAL_LLM_HANDOFF.md` §1(역할분담 원리)·§7(자동채점)·§8(로드맵 3단계)·§9(배포)·§15(감사 수정).

---

## 0. 한 줄 요약

**LoRA는 "생성(자유 양식 작성)"에만 필요하다. 추출·분류·양식채우기는 json_schema 강제 디코딩으로 이미 소형모델이 100%를 낸다(벤치 495/495).** LoRA 학습 데이터의 프롬프트 템플릿 = 아래 §3의 노드 프롬프트를 그대로 쓴다(train/inference skew 방지). LoRA 추론 배선은 현재 **미완**(§5) — 여기부터 손대면 된다.

---

## 1. 감사로 실증된 핵심 결론: LoRA가 필요한 곳 / 불필요한 곳

| 작업 | 노드 | 현재 소형모델 성능 | LoRA 필요? |
|---|---|---|---|
| **구조화 추출** (비정형→표) | llm_extract | **100%** (json_schema 강제, 벤치 495/495) | ❌ 불필요 |
| **분류** (카테고리 선택) | llm_classify | **강제 enum**으로 목록 밖 값 원천차단 | ❌ 불필요 |
| **양식 채우기** (빈칸→값) | form_extract→llm→form_fill/hwpx_fill | **100%** (grid `fill_hwpx_cells`) | ❌ 불필요 |
| **요약** (변환·압축) | llm_summarize | 양호 (창작 아닌 변환) | △ 품질 여유용 |
| **번역** | llm_translate | 양호 | △ 도메인 용어용 |
| **반정형 생성** (가정통신문·공문) | llm_generate | 스캐폴드 프롬프트로 ~가능(§13) | ✅ **주 타깃** |
| **자유 장문** (10p+ 계획서) | llm_generate (map-reduce) | 한계 | ✅ **주 타깃 + API 옵션** |

**결론**: LoRA의 진짜 타깃은 `llm_generate`(생성) 하나다. 추출·분류는 스키마 강제가 LoRA보다 확실하고 싸다. **LoRA 학습에 추출/분류/계산을 넣지 마라 — 베이스의 그 능력을 열화시킨다**(§9 배포 결정: 베이스+어댑터 분리, merge 금지).

---

## 2. 역할 분담 = LoRA 학습 대상의 경계

> **"모델이 작아질수록 지능을 코드로 옮긴다"** (§1). LoRA는 아래 "LLM 담당"의 **생성 부분만** 학습한다.

- **코드 담당 (LoRA 학습 금지)**: 표 위치·병합 계산, 순위·소계·평균·합계, 셀ID/좌표, HWPX/XML 생성, 결과 검증, JSON 파싱·정규화, "이하빈칸" 마커 이동.
- **LLM 담당**:
  - *스키마 강제로 충분* → 비정형→구조화 JSON(추출), 의미 매칭(분류). **LoRA 불필요**.
  - *LoRA 타깃* → 문서 유형별 톤·개조식 구조·관용 표현으로 **본문 생성**(공문/가정통신문/회의록).

**즉 LoRA 학습 데이터 = "요청/맥락 → 완성된 문서 본문" 쌍**. 계산·표조립은 데이터에서 배제하고 코드가 처리한다.

---

## 3. 노드별 LLM 계약 = LoRA 학습 데이터 스키마 (프롬프트 원문)

> 학습·추론 프롬프트를 **동일하게** 유지해야 skew가 없다. 아래는 현재(감사 후) 노드가 실제로 쓰는 프롬프트. LoRA 데이터 생성 시 그대로 사용.

### 3.1 llm_generate (LoRA 주 타깃) — `nodes/llm_generate/main.py`
- 프롬프트 = **`params.prompt_template`의 `{{변수}}` 치환 결과** (자유 형식, 기본 `"{{입력텍스트}}"`).
- 긴 입력은 자동 map-reduce 청킹(`CHUNK_THRESHOLD=8000`, `_split_text`). LoRA는 **청크 단위 생성**을 학습(청크+앞요약 맥락 → 절 생성).
- 출력: 자유 텍스트 → `md_to_hwpx`/`md_to_docx`로 문서화.
- **학습 데이터 형태**:
  ```
  {"prompt": "<스캐폴드 시스템/지시 + 맥락>", "completion": "<하이엔드가 쓴 완성 본문(md)>"}
  ```
- **스캐폴드 패턴(§13 실증)**: 시스템 프롬프트가 개조식 섹션·표틀·필수항목을 제시하고 gemma는 내용만 채움. LoRA는 이 스캐폴드 없이도 유형별 구조를 내재화하는 것이 목표. **단, 현재날짜를 프롬프트에 주입**(소형모델이 연도를 2024로 가정하는 버그, §13·goe §10.8).

### 3.2 llm_extract (LoRA 불필요, 계약만 참고) — 스키마 강제 사용
```
다음 텍스트에서 정보를 추출하라.

[추출 필드]
{f1, f2, ...}

[규칙]
- 응답은 반드시 JSON 배열 형식으로 하라.
- 각 항목은 {"f1": "값", ...} 형태의 객체이다.
- 텍스트에서 찾을 수 있는 모든 항목을 추출하라.
- 값이 없으면 빈 문자열로 표시하라.
- JSON 외의 텍스트를 포함하지 마라.

[텍스트]
{원문}
```
- **json_schema**: `{"type":"array","items":{"type":"object","properties":{f:{"type":"string"}},"required":[fields],"additionalProperties":false}}`
- 출력: records `[{필드: 값}]`.

### 3.3 llm_classify (LoRA 불필요) — enum 강제
```
다음 텍스트를 아래 카테고리 중 하나로 분류하라.

[카테고리 목록]
{c1, c2, ...}

[규칙]
- 반드시 위 카테고리 중 하나만 선택하라.
- 응답은 반드시 JSON 형식으로 하라.
- 형식: {"category": "선택한 카테고리", "confidence": 0.0~1.0}
- JSON 외의 텍스트를 포함하지 마라.

[텍스트]
{원문}
```
- **json_schema**: `{"type":"object","properties":{"category":{"type":"string","enum":[categories]},"confidence":{"type":"number"}},"required":["category","confidence"],"additionalProperties":false}`

### 3.4 llm_summarize — `nodes/llm_summarize/main.py`
```
다음 텍스트를 요약하라.

[요약 규칙]
- {스타일: bullet/paragraph/oneliner 지시}
- 최대 {N}자 이내로 작성하라.
- 원문에 없는 내용을 추가하지 마라.

[원문]
{원문}
```

### 3.5 llm_translate — `nodes/llm_translate/main.py`
```
다음 텍스트를 {대상언어}({English 등})로 번역하라.

[번역 규칙]
- 원문의 의미를 정확히 전달하라.
- 자연스러운 {대상언어} 표현을 사용하라.
- 번역문만 출력하라. 설명이나 부연을 추가하지 마라.

[원문]
{원문}
```

---

## 4. json_schema 강제와 LoRA는 병행한다

- 엔진은 이미 **스키마 강제 디코딩**을 지원: `llm.generate(json_schema=...)` → 로컬은 llama-server `response_format:{type:"json_schema"}`(llama.cpp GBNF 문법 강제). `engine/llm_manager.py:95-134`, `_local_chat_completion:342-347`.
- **추출·분류는 이 강제로 형식을 100% 보장** → LoRA 없이 소형모델이 못 틀린다.
- **LoRA를 학습해도 추론 시 스키마 강제를 계속 켤 수 있다** — 구조는 GBNF가, 내용 품질은 LoRA가 담당. 생성(자유 텍스트)엔 스키마가 없으므로 여기서 LoRA가 유일한 품질 레버.

---

## 5. ⚠️ LoRA 추론 배선 — 현재 미완 (이번 감사 #22 실측). 여기부터 손대라.

LoRA "핫스왑 스캐폴딩"이 있다지만 **실제로는 전 구간 미배선**이다(감사 확정결함 #22). 정확한 공백:

| 위치 | 현재 상태 | LoRA 시 필요한 작업 |
|---|---|---|
| `nodes/llm_generate/main.py` | `lora`를 `llm.generate(lora=...)`로 넘김. **지금은 넘겨도 무시됨 → `[WARN]` 로그**(수정10에서 추가) | 배선 완료 후 WARN 제거 |
| `engine/llm_manager.py` `generate()` :126 | `local`일 때만 `_generate_local(...lora...)` 전달, API는 lora 버림 | 유지 |
| `_generate_local()` :366-373 | **lora 인자 받지만 본문에서 미사용** → `_local_chat_completion`(lora 파라미터 없음) 호출 | `_local_chat_completion(..., lora=lora)` 전달 |
| `_local_chat_completion()` :324-364 | payload에 lora 필드 없음 | 요청 payload에 어댑터 선택 추가 (아래) |
| `_start_llama_server()` :414-422 | 기동 cmd에 **`--lora` 플래그 없음** | 어댑터들을 `--lora-scaled <path> 0.0`로 프리로드(로드+off) |
| `_find_lora()` :497-507 | `models/loras/*.gguf` 이름검색 구현됨. **호출처 0 (죽은코드)** | `_generate_local`에서 호출해 어댑터 경로 해석 |

**배선 레시피 (llama.cpp llama-server 기준)**:
1. 기동: 모든 어댑터를 `--lora-scaled adapter.gguf 0.0`로 프리로드(로드하되 scale 0 = off).
2. 요청별 on/off: `/v1/chat/completions` payload에 `"lora":[{"id":<idx>,"scale":1.0}]` (또는 `POST /lora-adapters`로 scale 세팅) → 요청마다 어댑터 즉시 전환(재기동 불필요).
3. `_find_lora(name)`로 어댑터 인덱스/경로 매핑, `llm_generate`의 `lora`(문서유형명) → 어댑터 선택.
4. 미지원 provider(claude/openai)에서 lora 지정 시 경고(이미 있음).

**배선 후 검증**: 같은 벤치(495/495)로 회귀 + 베이스 능력(추출·분류) 열화 없는지 확인(어댑터 off 상태 = 베이스와 동일해야 함).

---

## 6. 증류 파이프라인 (§8 3단계 구체화)

### 6.1 데이터 수집 — 지금부터 로깅 시작
- **로깅 지점**: `engine/llm_manager.py generate()`에서 provider가 API(claude/openai)일 때 `(prompt, 하이엔드 출력)` 쌍을 파일로 적재. 특히 **`llm_generate` 경로**(생성)만 모으면 됨.
- **사용자 보유 실제 문서 활용**(더 중요): 신병철 교사가 보유한 실제 공문서·가정통신문 대량 → `hwpx_to_md`/`hwp_to_md`/pandoc으로 md 변환(감사에서 kordoc npx 경로 복구됨, §15 수정5).
  - **개인정보 익명화 필수**(이름·전화·계좌 → 더미) — 학습 전 반드시. 익명화 스크립트 위치는 미정, 원본 문서 위치는 사용자 확인.
  - **지시문 역생성**: 하이엔드에게 "이 문서를 만들 요청문을 역으로 써줘"(1회성 API, 몇천 원) → `{요청문 → 문서}` 쌍.
- 중복 제거, 변환 깨진 문서(복잡표·그림 위주) 필터.

### 6.2 학습 — 이 Desktop(RTX5080)이 본진
- 장비: **coka_desktop, RTX5080 16GB**(Blackwell/sm_120). axolotl 또는 unsloth.
- 베이스: **Gemma 3n E4B**(현재 `D:\models\teacherflow\gemma-4-E4B-it-*.gguf`). ⚠️ 배포 타깃이 8GB 노트북이면 **E2B(2B) 재검증 필요**(§13, E2B 미검증).
- 어댑터 구성: 시작은 "교사 문서 통합 LoRA" 1개(공문+통신문+회의록 혼합) → 벤치에서 처지는 유형만 분리(§9).
- **단일턴 우선**(지시→문서), 2차로 수정턴(문서+수정지시→수정본). 긴 자유 대화 학습은 로컬엔 과욕 → API.

### 6.3 변환·배치
- 학습 산출 → **GGUF LoRA 변환** → `models/loras/`(`_find_lora`가 여기 검색). 파일명에 유형명 포함(예: `gatong_v1.gguf`).

### 6.4 배포 (§9 결정 재확인)
- **베이스 + 어댑터 분리**(merge 금지): 용량(어댑터 수십MB)·업데이트(어댑터만 교체)·안전성(추출/매칭/JSON 능력 보존).
- 교사 UI엔 "LoRA" 용어 미노출 → "문서 스타일: [자동][공문체][가정통신문][회의록]" 버튼, 기본은 파이프라인이 유형 판단→어댑터 자동선택.
- 원클릭 풀번들(앱+엔진EXE+llama-server+GGUF+어댑터+pandoc), 학교망 outbound 차단 대비 다운로드 방식 배제.

---

## 7. 소형모델 실측 교훈 (LoRA 데이터·프롬프트에 반영)

- **배열 공백화 함정**: 문법 강제만 걸면 소형모델이 배열을 비워버림 → `minItems`/few-shot 1줄 필수(§10). 추출에서 검증됨.
- **날짜 연도 2024 가정**: 학습기본값으로 연도를 2024로 씀 → 생성 프롬프트에 **현재날짜 주입**(코드). goe(§10.8)·문서생성(§13) 공통.
- **LLM에 셀ID 매핑·계산 시키지 마라**: 출력 수천토큰·산수틀림 → LLM은 "비정형→JSON"만, 배치·계산은 코드(§10.5).
- **reasoning OFF**: gemma-4는 사고모델 → `--reasoning off` 필수(구조화·요약엔 사고 불필요, 속도 유리). LoRA 학습·추론 동일.
- **-np 1**: 8GB급 GPU에서 다중슬롯 KV캐시가 VRAM 초과→크래시. 구형 노트북 배포 안정성(§10). RTX5080 전용 16GB는 여유.

---

## 8. 검증 안전망 (LoRA 전후 반드시)

- **회귀 벤치**: `set PYTHONUTF8=1 && python scripts\benchmark_form_fill.py --llm local` → 레벨2 **495/495** 유지 확인. (어댑터 off = 베이스 = 495/495 이어야 함. LoRA가 추출/분류 능력을 안 깨는지 확인.)
- **생성 품질**: 유형별 샘플 생성 → `md_to_hwpx`로 한/글 열기 확인. 표 포함 문서는 표 보존 확인(§13 표드롭 폴백).
- 기준 hwpx: `data\fixtures\bench_score.hwpx`(`BENCH_HWPX` 환경변수로 교체 가능).
- 실행법·경로·모델: `LOCAL_LLM_HANDOFF.md` §11.

---

## 9. 착수 체크리스트 (다음 LoRA 세션)

1. [ ] 데이터 소스 확정: 사용자 보유 실제 문서 위치 + 익명화 스크립트(사용자 확인 필요).
2. [ ] `llm_generate` API 호출 로깅 추가(증류쌍 수집 시작).
3. [ ] 익명화 → md 변환 → 지시문 역생성 → 데이터셋(단일턴 `{요청→문서}`).
4. [ ] E4B(또는 E2B) 베이스로 통합 어댑터 1개 학습(unsloth/axolotl, RTX5080).
5. [ ] GGUF 변환 → `models/loras/`.
6. [ ] **§5 배선**: `_start_llama_server --lora-scaled` 프리로드 + `_local_chat_completion` payload lora + `_find_lora` 호출 + `_generate_local` 전달.
7. [ ] 검증: 벤치 495/495 유지(off) + 생성 품질 육안(on) + 어댑터 핫스왑 즉시성.
8. [ ] `llm_generate`의 lora `[WARN]` 제거(수정10).
