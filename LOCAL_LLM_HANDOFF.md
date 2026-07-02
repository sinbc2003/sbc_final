# 로컬 LLM 전환 설계 — 핸드오프 문서

> 작성: 2026-07-02 / 프로젝트: TeacherFlow (`C:\Users\sinbc\OneDrive\바탕 화면\00_sbc_final`)
> 목적: 이 문서만 읽고 새 세션에서 바로 이어서 작업할 수 있게 정리.

> ## ⏩ 다음 세션은 여기부터 (2026-07-02 오후 갱신)
> **§10(맨 아래)을 먼저 읽어라.** 로드맵 1단계(§8 A~D)는 **전부 완료**됐고, 모델은 **Gemma 4 E4B**(사고 OFF, `-np 1`)로 확정, goe 메신저 요약기도 로컬 전환 완료.
> - **§1~§7의 "즉시 고칠 것 / ★여기부터 시작" 표시는 대부분 이미 완료됨** — 배경 설명으로만 읽고, 실제 할 일은 **§10 "남은 TODO"**를 따를 것.
> - ✅ 추가 완료(07-02 오후): "이하빈칸" 마커 자동 이동(§10.5) + 한/글 육안 검증 + 1단계 전체 git 커밋.
> - 바로 시작할 일 후보: ①노드 UI E2E(form_extract→LLM local→form_fill), ②3단계 증류(공문서 익명화+로깅), ③goe 마감일 연도 주입, ④HWPML blockId→COM 좌표 캘리브레이션.

---

## 0. 한 줄 목표

> **구형 노트북을 쓰는 교사도 로컬 LLM(gemma 등)으로 hwpx/엑셀/ppt 문서 작업을 할 수 있게 만든다. (API 모델 연결도 병행 지원.)**

현재는 하이엔드 LLM을 API로 불러 문서를 작성/제어하는 형태. 이걸 로컬 소형 모델로도 돌아가게 하되, API는 "품질 업그레이드 옵션"으로 남긴다.

---

## 1. 핵심 설계 원칙 (이번 논의의 결론)

> **"모델이 작아질수록, 지능을 코드로 옮긴다."**

- 구형 노트북 = 1B~4B급 소형 모델 = 멍청함. 그래서 모델이 하는 일을 "작은 입력 → 작은 판단"으로 최대한 줄인다.
- **코드(파이썬)가 담당**: 표 위치 계산, 순위·점수·합계 산정, HWPX/XML 생성, 셀 주소 지정, 결과 검증. → 구형 노트북에서도 0.1초.
- **LLM이 담당**: "이 값이 어느 라벨/셀에 들어가나"(의미 매칭), "이 문단 톤 다듬기" 같은 판단만.
- **출력 형식**: JSON/문법 강제 디코딩(GBNF/스키마)으로 모델이 틀리고 싶어도 못 틀리게.
- **결과**: 자동 검증 → 틀리면 재시도. 소형 모델의 실수를 시스템이 흡수.

핵심 통찰: **품질을 결정하는 건 "모델 성능"이 아니라 "시스템 설계"다.** 그래서 구형 노트북에서도 쓸 만해진다.

### "Inline AI도 Opus로 만든 거 아니냐"에 대한 답

- Inline AI가 복잡한 표를 잘 채우는 건 **런타임 모델이 천재라서가 아니라**, 스캔·주소지정·검증 시스템이 모델에게 떠먹여 주기 때문. (실제로 v0.3.1 런타임은 GPT-5.4를 씀 — 아래 3절.)
- 즉 **같은 시스템을 만들면 그 자리에 gemma를 꽂아도 된다.** Inline AI가 큰 모델을 쓰는 건 "표 채우기가 어려워서"가 아니라 "긴 문서 작성·자유 대화까지 한 모델로 커버하려니까".
- 우리는 **표 채우기라는 좁은 작업만 떼어내** 거기 맞는 최소 모델을 쓴다.

---

## 2. Inline AI 스캔/채우기 메커니즘의 정체 (역공학 분석 결과)

사용자 관찰: "hwpx 열고 AI에게 지시하면 **포인터가 문서 전체를 자동으로 쭉 훑고** → 해당 위치들에 텍스트를 **정확히 채워넣더라.**"

### 그 "훑기"의 정체 = 100% 결정적 파이썬 코드 (AI 아님)

- OS 마우스 포인터가 아니라 **편집 캐럿(text caret) + 선택 하이라이트**가 이동하는 것. AI가 화면을 보는 게 아님. 컴퓨터 비전 전혀 없음.
- 원인 2가지 (v0.2.12 `document_extractor.py` 기준):
  1. **범위 확정**: `goto_page` → `_page_down`이 `MoveSelPageDown/MoveSelLineDown/MoveSelRight` 반복 → 파란 선택 블록이 문서를 쓸고 내려감.
  2. **실제 스캔**: `init_scan` 열고 while 루프에서 `get_text()` → `move_pos(201)`(캐럿 한 요소씩 전진) → `get_pos()` → 서식 수집. 이게 요소 단위로 캐럿을 계속 옮김.
- 위치는 전부 COM이 주는 `get_pos()` 좌표 튜플 `(list_pos, para_pos, char_pos)`로 다룸.

### "정확히 채우기"의 정체 = blockId → COM 좌표 매핑

1. 스캔 때 각 요소(문단/셀/각주)에 순차 **blockId** 부여 + `id_to_pos[blockId] = (list, para, char)` 저장. (결정적)
2. **LLM은 blockId만 참조** — 좌표를 전혀 모름. LLM 출력은 `op / id / new_text` 같은 작은 명령.
   예: `op: replace_cell_content\nid: 102\nnew_text: 신병철`
3. 편집기가 blockId를 좌표로 풀어 `set_pos(...)` → `is_cell()` 확인 → `SelectAll()`(셀 내부) → 삽입. 삽입 후 뒤 blockId 좌표 보정(insertion_tracker).

**결론: LLM = 의미 결정(어디=blockId, 무엇=값). 스캔·좌표계산·캐럿이동·삽입·검증 = 전부 결정적 코드+COM.** → 이 구조라서 소형 모델로 교체 가능.

---

## 3. v0.3.1에서 방법론이 바뀌었나? (분석 결과)

사용자 질문: "지금은 개선했다는데 방법론이 바뀐 건지 모르겠다." + "역공학 버전은 낡았다."

**답: 편집 방식은 패러다임 전환됐지만, 스캔/blockId 뼈대는 유지·정교화됐다.**

| 항목 | v0.2.12 | v0.3.1 |
|---|---|---|
| **편집 실행** | AgentDelta (선언형 텍스트 델타, `op:/id:/new_text`, `---` 구분) | **LLM이 Python 코드 작성 → 로컬 executor 실행** (`hwp_run_python_code`). `set_paragraph(block_id, ...)` 등 함수 API. = code-as-action 전환 |
| **문서 읽기** | CVD 일괄 추출 | `hwp_scan_document`(개요) + `hwp_read_pages`(내용) **2단계 분리** (정교화) |
| **blockId 체계** | 있음 | **그대로 유지** (`core/block_manager.py` 존속) |
| **스캔 코어** | COM 캐럿 + CVD | **COM/pyhwpx 유지** + HWPML XML 파싱 경로 신규 추가 (의존도↓) |
| **에이전트** | 단일 SSE 스트림 | tool_use/tool_result 루프(최대 200턴), 서브에이전트, write_todo, skill-pack |
| **런타임 모델** | 불명 | **GPT-5.4-2026-03-05** (서브에이전트 gpt-5.4-mini) |
| **배포** | 서버가 스크립트 AES 암호화 전송 | **Nuitka C 컴파일 EXE, 오프라인 동작 가능** |
| **포맷** | HWP | HWP+Excel(편집)+DOCX/PPTX/PDF/CSV/이미지(읽기) |

**시사점**: "포인터 훑기 → blockId → 정확히 채우기"의 뼈대는 안 바뀐다(COM 제어인 이상 물리적으로 못 바꿈). v0.3.1은 이 위에 HWPML 파싱을 얹고 편집을 code-as-action으로 바꾼 것. 우리 방향(스캔+blockId+검증 시스템)은 최신 버전과도 일치.

---

## 4. HWPML 표 복잡성 — 어디까지 코드로, 어디부터 AI? (분석 결과)

> **문법(syntax)은 100% 결정적 파싱 가능. 의미(semantics)·시각 결과(rendering intent)만 AI 판단 영역.**

### 결정적 코드로 완전 해석 가능
- 다중 셀 병합: HWPML은 HTML의 "셀 생략"이 아니라 **주소 기반**(`ColAddr/RowAddr + ColSpan/RowSpan`) → 오히려 HTML보다 결정적. `get_merged_cell_map`이 `(row,col)→cell`을 순수 산술로 전사.
- 중첩표, 셀 안 복수 문단, 셀 크기/여백/테두리 ID, 수식 스크립트 **원문 추출**.

### 코드만으로 안 되는 4가지 (AI 판단 or 파서 확장 필요)
1. **의미 판단**: 헤더 행/열 식별, 병합 셀 라벨의 적용 범위, 레이아웃용 표 vs 데이터 표 구분. → HWPML에 `th` 같은 헤더 마커가 **없음**.
2. **수식 의미 변환**: 스크립트 추출은 결정적이나, 한/글 고유 문법(`matrix{}`, `cases` 등) 비표준 표기의 의미 변환·검증은 AI 필요.
3. **스키마 불확실성**: HWPML 공식 스키마 비공개. 미지 태그/속성 강건성은 결정적 보장 불가.
4. **현 파서 공백** (아래 3개는 파서 확장으로 결정적 해결 가능):
   - `borderFill` 미해석 → "선 없는 셀"로 구획한 시각 구조 복원 불가.
   - 세로쓰기 셀 미지원.
   - 텍스트+수식 혼합 셀의 인라인 순서 소실.
   - (버그) 중첩표 이중 등록 위험: `parser.py:424-426` `_find_recursive`가 셀 내부 표를 바깥 문단으로 끌어올림, `if table_el in p_node.iter()` 가드는 항상 참이라 무의미.

---

## 5. TeacherFlow 현재 구현 상태 (분석 결과)

### 이미 되어 있는 것 (놀랍게도 많음)
- **스캔→CVD→blockId→편집 파이프라인이 end-to-end로 실제 동작**: `HwpController.connect/_refresh_hwp` → `extract_cvd` → `/api/hwp/cvd`·`/api/hwp/execute` → 채팅 LLM 액션 파싱·실행 루프.
- **듀얼 스캔 모드**: (1) HWPML 모드 `SaveAs('HWPML2X')→parse→PositionEngine`, (2) 커서 폴백 `init_scan + get_into_nth_table + TableRightCell`. auto에서 HWPML 우선, 실패 시 커서 폴백.
- **PositionEngine**: blockId 할당 + 셀 병합 메타(col/row_addr, span, is_merged) 보존 + `extract_table_merge_map`.
- **CVD 빌더**: Dominant+Exception 스타일 인코딩, colspan/rowspan HTML 렌더링, 수식/각주/텍스트박스 렌더링.
- **HwpEditor 자가 복구**: 좌표 밀림 감지 → 리스캔 → 재시도. 구조 변경 후 `_needs_rescan` 자동 리스캔. block_id 액션을 문서 뒤에서부터 실행(좌표 밀림 예방).
- **지원 편집 op 22종**: `replace_cell_content, delete_cell_content, replace_paragraph, append_paragraph, find_and_replace_all, insert_text, apply_para_style, create_table, replace_table_row, append_table_row, style_cell, style_row, merge_cells, set_table_col_width, style_table_row_idx, style_table_cell_idx, set_table_widths, format_text, save, save_as` 등.

### Inline AI 대비 빠진 것 / 약점 (= 앞으로 할 일)
1. **채팅 파이프라인이 저품질 CVD를 씀**: `_read_with_cvd`(chat_handler.py:523-565)가 **커서 스캔 CVD만** 사용. colspan/rowspan·스타일이 담긴 **HWPML `build_cvd`는 `/api/hwp/cvd` 엔드포인트에만 배선**되고 채팅 편집 루프에선 미사용. → **연결만 하면 큰 개선.**
2. **HWPML blockId→COM 좌표 캘리브레이션 부재**: `PositionEngine.id_to_pos`가 자체 카운터로 만든 **가상 좌표**(position_engine.py:93,184)라 실제 COM 좌표와 불일치 → HWPML 모드 `set_pos` 폴백 신뢰 불가. td는 `table_idx+cell_seq` 순회로 우회하나 병합 표에서 COM `TableRightCell` 순서와 어긋날 수 있음.
3. **페이지 캘리브레이션 부재**: `build_cvd`에 `id_to_page`·페이지 마커 로직 있으나 아무도 안 채움. `page_range`도 무시됨(대형 문서 부분 스캔 불가, 15초 타임아웃 절단).
4. **문자 단위(char_pos) 편집 없음**: 전부 char_pos=0, 문단 전체 교체만. 문단 내 부분 교체 불가.
5. **수식/이미지/텍스트박스/각주 편집 op 부재**: CVD엔 노출되나 편집 명령 없음. `latex_to_hwp` 모듈은 있는데 라이브 편집에 미연결.
6. **merge_cells 아래 방향 미완성**(hwp_controller.py:948-951 자인). 셀 분할·행/열 삭제·임의 위치 삽입 op 없음.
7. **LLM 노출 스키마 불완전**: `HWP_ACTIONS_SCHEMA`(hwp_controller.py:1719-1768)가 12개 op만 기술 → style/merge 계열을 LLM이 모름.
8. **undo/트랜잭션/프리뷰 없음**.

### 파일 편집 경로(form_fill) vs 라이브 COM 경로 — 능력 차이 큼
- **`nodes/form_fill/main.py`**: 구조 인식 없는 단순 주입기. HWPX는 "이전 텍스트=라벨, 빈 `<t>`=빈칸" 휴리스틱(main.py:316-357). **blockId·표 구조·병합 개념 전혀 없음** → 복잡한 공문에서 오채움 구조적으로 불가피. (XLSX만 openpyxl 셀 좌표로 정밀.)
- **라이브 COM 경로(`hwp_controller`)**: HWPML 파싱으로 병합 구조 보존, CVD로 LLM에 표 구조 그대로 노출, blockId·(table,row,col)로 타겟 편집. **복잡한 병합 표 읽기·표현은 압도적 우위.**
- **결론**: 복잡한 표는 라이브 경로로 가야 함. (단, 라이브도 병합 표 "쓰기"는 cell_seq 순서 의존이라 완전 보장은 아님 → 위 2번 캘리브레이션 필요.)

---

## 6. LLM 관리 현황 (llm_manager.py)

- **provider 파라미터가 노드별로 이미 있음**: `auto | local | claude | openai | gemini`. → "로컬로 하다 품질 아쉬우면 API 키만 넣으면 업그레이드"가 자연스러움.
- **로컬 지원 이미 구현(Phase 2)**: `_generate_local`이 llama-server(127.0.0.1:8400) HTTP 호출, 미실행 시 자동 시작, **Gemma 채팅 템플릿(`<start_of_turn>`) 하드코딩**, LoRA 핫스왑 스캐폴딩.
- **memory_manager**: 8GB→Q3/ctx2048, 12GB→Q4/ctx4096, 16GB→Q6/ctx8192 자동 프로필. (구형 노트북 자동 강등 전제 설계.)

### ✅ 아래 3개는 2026-07-02 전부 해결됨 (배경 기록용, 재작업 불필요 — 상세 §10)
1. ~~ctx 캡 버그~~ → **해결**: `local_ctx` 설정 우선, 캡 제거. 기동 `-c 8192`.
2. ~~이 노트북에 GGUF 없음~~ → **해결**: `C:\Users\sinbc\models\teacherflow\gemma-4-E4B-it-Q4_K_M.gguf` 설치. (모델도 gemma-4 E4B로 확정)
3. ~~JSON 문법 강제 미적용~~ → **해결**: `/v1/chat` `response_format: json_schema` + `minItems` + few-shot으로 강제.
   - ※ 위 §6 line "`<start_of_turn>` 하드코딩" 서술은 **구버전** — 지금은 `/v1/chat/completions`(내장 템플릿) 사용.

---

## 7. 테스트 기준 파일 & 자동 벤치마크 (중요)

**성공 기준 파일**: `C:\Users\sinbc\OneDrive\바탕 화면\2024학년도 기간제 교사 채용 점수 집계표(역사, 체육, 러시아어, 프랑스어).hwpx`

### 실측 구조 (직접 파싱함)
- 표 16개 = (과목정보 + 점수집계표) × 8세트 (1차 서류 4과목 + 2차 면접 4과목).
- **병합은 헤더에만, 완전히 규칙적**: 관리번호/성명/순위=세로 2칸 병합, "심사위원별 총점"=가로 6칸 병합. **데이터 행(점수 들어가는 곳)은 병합 없는 정규 격자.** → 그리드 좌표로 명확히 지정 가능.
- **Opus가 헷갈렸던 물증**: "이하빈칸" 표시가 셀 하나에 한 글자씩 흩어짐 — `(4,3)="이" (4,4)="하" (4,5)="빈" (4,6)="칸"`. form_extract처럼 선형으로 펴서 "직전 텍스트=라벨" 붙이면 빈칸 라벨이 "칸","빈"이 됨. → **모델 탓 아니라 입력 표현 탓.**

### 이 파일이 그대로 자동 채점 시험지가 됨
- 파일에 **이미 정답이 채워져 있음**(역사 28명, 체육 12명 점수·소계·평균·순위).
- 채점 루프: (1) 채워진 행을 코드로 지워 "빈 시험지" 생성 → (2) 지운 데이터를 자연어 입력인 척 gemma에 주고 파이프라인 실행 → (3) 결과를 원본과 셀 단위 비교 → 정확도 % 산출.
- → "gemma가 채우면 성공"을 사람 눈이 아니라 **자동 채점 회귀 테스트**로 측정. 모델/프롬프트/LoRA 바꿀 때마다 재사용.

### 이 문서에서 gemma가 실제 할 일 (아주 작음)
| 단계 | 담당 |
|---|---|
| 표 구조 해석 (어느 열=위원1, 데이터 몇 행부터) | **파이썬** (헤더 규칙적) |
| 사용자 입력을 {이름, 점수4개} JSON으로 정리 + 어느 과목 표인지 판단 | **gemma** (유일한 판단, 2B로 충분) |
| 소계·평균·순위 계산 (동점 공동순위: 7,7,7→10 방식) | **파이썬** (모델에 시키면 산수 틀림) |
| 셀 주소 지정 + XML 쓰기 + "이하빈칸" 마커 아래로 이동 | **파이썬** |
| 채운 뒤 재추출 검증 | **파이썬** |

---

## 7.5 제품의 일반 구조 (사용자 정의 — 채용점수표는 예시일 뿐)

교사 사용 패턴의 일반형:
**입력** = 채팅 입력 + 파일 업로드(pdf, hwp, hwpx, xls, xlsx, csv 등 아무거나) = "맥락"
**출력** = ① 정해진 양식이 있으면 → 양식의 채워야 할 부분을 맥락 바탕으로 채우기, ② 없으면 → 자유 양식 작성 (보고서, 공문, 회의록 등)

```
교사 입력 (채팅 + 파일 아무거나)
        │
   [코드] 형식 변환·정규화 → "맥락"     ← 변환 노드 이미 있음 (pdf/hwp/hwpx/xlsx/docx/url_to_md)
        │
        ├─ 양식 있음 → [코드] 양식 그리드·빈칸 스키마 추출
        │              [LLM] 맥락에서 빈칸별 값 추출·매칭   ← 로컬 쉬움 (대부분의 사용)
        │              [코드] 채움 + 검증
        │
        └─ 양식 없음 → [LLM] 문서 유형 판단 (공문? 회의록? 보고서?)
                       [LLM] 유형별 LoRA/템플릿으로 생성
                       [코드] md → hwpx/docx 출력
```

핵심 판단:
- **입력의 다양성은 난이도에 영향 없음** — 형식 변환은 전부 코드가 흡수. 모델은 항상 정규화된 텍스트만 봄.
- **난이도는 출력 모드가 결정**: 양식 채우기 = 추출+매칭 = 로컬 친화. 긴 맥락(30p pdf)도 "빈칸별 필요 사실 추출"로 쪼개져 청크 처리 가능(llm_extract·rag_query 노드).
- **"자유 양식"의 대부분은 사실 암묵적 양식이 있음**: 공문(개조식·고정구조, 극도로 정형) = LoRA 최적 타깃 / 회의록 = 창작이 아닌 변환·요약 = 로컬 가능 / 가정통신문 = 반정형 = LoRA 커버. 진짜 자유 장문(10p+ 계획서)만 로컬 한계 영역 → 절 단위 생성 + API 옵션.
- **Inline AI와의 차이 재확인**: 우리는 "문서에 뭐든 해줘"가 아니라 "맥락 주고 → 문서 받기" 단일 패턴. 모델이 탐색·코드작성·에이전트 루프를 할 필요가 구조적으로 없음 → 하이엔드 불필요 논리가 일반 구조에서도 유지됨.
- **편집 방식 결정**: v0.3.1의 code-as-action(LLM이 파이썬 작성)은 따라하지 않음 — 소형 모델이 가장 못하는 게 코드 작성. 우리는 v0.2.12식 선언형 명령(JSON 액션, 스키마 강제)을 유지. TeacherFlow의 22종 op + 액션 JSON 구조가 이미 그 방식. 반복·계산의 유연함은 파이프라인 파이썬이 담당.

---

## 8. 로드맵 (권장 순서)

### 1단계 (기반 공사 + 즉시 Opus 오류도 해결) — ✅ 2026-07-02 완료 (A~D 전부, §10 참조)
- **A. 표 채우기 파이프라인 개선**:
  - form_extract를 **병합-인지 그리드**로 교체 (HWPML `build_cvd`/`parser` 활용). 선형 스트림 폐기.
  - **계산·배치를 파이썬으로** (순위·소계·평균). LLM은 의미 매칭만.
  - **채운 뒤 자동 검증** → 틀리면 재시도.
- **B. 채팅 파이프라인이 HWPML CVD를 쓰게 배선** (5절 gap #1 — 연결만 해도 큰 개선).
- **C. ctx 캡(4096) 해제** + **JSON 문법 강제 디코딩** 연결 (6절 문제 #1,#3).
- **D. 이 hwpx로 자동 채점 벤치마크 구축** (7절).
- ※ A+B+C+D는 한 묶음. 로컬 모델의 기반이면서 지금 API에서도 품질이 오름.

### 2단계 (로컬 정확도 강화)
- HWPML blockId→COM 좌표 캘리브레이션 (5절 gap #2) — 병합 표 "쓰기" 신뢰성.
- 소형 모델용 few-shot 프롬프트 + 노드별 provider=local 전환 (분류·추출·양식채우기·짧은 요약부터).

### 3단계 (증류 = 하이엔드 따라하기)
- **데이터 수집**: 지금부터 API 호출 (프롬프트 템플릿 → 하이엔드 출력) 쌍 로깅.
- **기존 문서 활용**: 사용자가 보유한 실제 사람 작성 공문서(ODT)·가정통신문 대량 보유 →
  - hwpx_to_md/pandoc으로 텍스트 변환 (md_to_hwpx와 같은 마크다운 규칙으로).
  - **개인정보 익명화** 스크립트 필수 (이름/전화/계좌 → 더미). ← 학습 전 반드시.
  - **지시문 역생성**: 하이엔드에게 "이 문서를 만들 요청문을 역으로 써줘" (1회성, API 몇천 원).
  - 중복 제거, 변환 깨진 문서(복잡 표·그림 위주) 필터.
- **LoRA 학습**: Desktop(RTX 5080, `ssh PC@100.111.200.103`)에서 axolotl/unsloth. 노드 종류별로 따로(가정통신문/공문/계획서). GGUF LoRA 변환 → `models/loras/` (핫스왑 코드 이미 있음).
- **멀티턴**: 1차는 단일턴(지시→문서). 2차로 "수정턴"(문서+수정지시→수정본) 추가. 긴 자유 대화 학습은 로컬엔 과욕, API에 맡김.

### 4단계 (장문)
- A4 10~15페이지 계획서: **한 방에 X**. 개요 생성 → 절 단위 생성(목차+앞 절 요약만 컨텍스트) → 파이썬 병합. llm_generate의 map-reduce 청킹(nodes/llm_generate/main.py:80)을 "긴 출력 생성"용으로 확장.

---

## 9. 사양별 현실 그림

| 교사 노트북 | 모델 | 되는 것 | API 권장 영역 |
|---|---|---|---|
| 8GB 구형 | 1B~2B Q4 | 표 채우기, 분류·추출, 짧은 통신문 (30초~2분) | 긴 계획서 |
| 16GB (이 노트북, Arc 140V 8GB) | 4B Q4~Q6 | 위 전부 + 중간 문서, 품질 한 단계↑ | 고품질 장문 |
| API 키 입력 교사 | 하이엔드 | 전부 | — |

- **같은 워크플로우가 세 경우 모두 동작**(provider 파라미터).
- **배포 모델**: 교사는 아무것도 학습 안 함. 사용자가 5080으로 LoRA 만들어 앱에 동봉 → 교사는 설치·실행만. 첫 실행 때 램 감지해 GGUF 자동 다운로드(memory_manager). LoRA는 앱 업데이트로 배포(핫스왑).
- **배포 형태 결정: 합본(merge) 아닌 "베이스 + 어댑터"** — ① 용량(통모델 GB급 vs 어댑터 수십 MB), ② 업데이트(어댑터 파일만 교체), ③ 안전성(글쓰기 LoRA를 merge하면 베이스의 추출·매칭·JSON 능력이 열화될 수 있음 — 표 채우기는 깨끗한 베이스로, 작성은 어댑터 붙여서), ④ llama-server가 다중 어댑터 로드+요청별 on/off 지원, llm_manager에 핫스왑 코드 기존재. 교사 눈엔 "완성된 전용 모델"로 보이지만 내부는 베이스+어댑터.
- **어댑터 구성**: 시작은 "교사 문서 통합 LoRA" 1개(공문+통신문+회의록 혼합 학습) → 벤치마크에서 처지는 유형만 분리. 유형별 다중 어댑터는 품질 상한↑, 통합은 관리 단순.
- **라이선스**: Gemma 약관은 파인튜닝 파생물 재배포 허용(사용 제한 조항 고지 의무 따라붙음). 배포 시점에 최신 약관 재확인.

### 배포 UX 결정 (교사 = 코딩 모름, 최대한 간편)
- **원클릭 풀 번들 설치본** (2.5~4GB, 사용자 결정): 설치 exe 하나에 앱(Tauri) + 엔진(파이썬→EXE 컴파일) + llama-server.exe + gemma GGUF + LoRA 어댑터들 + pandoc까지 전부 동봉. 더블클릭→설치→실행이 전부. "첫 실행 때 모델 다운로드" 방식 배제 — **학교망은 outbound 차단이 흔해서**(수성고 실측) 다운로드 방식은 죽음. USB 배포도 가능해야 함.
- **첫 실행**: 램 감지(memory_manager) → 컨텍스트 자동 조정. llama-server는 앱이 백그라운드 자동 시작(코드 기존재).
- **패키징 작업 항목**: 파이썬 엔진(FastAPI)을 PyInstaller/Nuitka로 단일 EXE 컴파일 필요. Inline AI v0.3.1이 정확히 이 방식(Nuitka C 컴파일 워커 EXE 동봉) — 검증된 길.
- **LoRA는 UI에서 숨김**: 기본은 파이프라인이 문서 유형 판단→어댑터 자동 선택(교사는 아무것도 안 고름). llama-server 다중 어댑터 프리로드 + 요청별 on/off라 전환 즉시. 수동 보조 UI는 "✍️ 문서 스타일: [자동] [공문체] [가정통신문] [회의록] [일반]" 식 버튼 — "LoRA" 용어 미노출.
- **업데이트**: Tauri updater로 어댑터(수십 MB)만 교체. 교사는 "업데이트 → 확인" 클릭뿐.
- 12B 이상 필요 시: Desktop 5080에 llama-server 띄우고 Tailscale로 붙이기 (llm_manager의 server_url만 변경).

---

## 10. 작업 기록 — 2026-07-02 세션 (로드맵 1단계 완료 ✅)

### 🎯 헤드라인: 레벨2 벤치마크 495/495 (100%) — 최종 모델 Gemma 4 E4B
**로컬 gemma(Arc Vulkan)가 채용점수표 8개 표(러시아어·프랑스어·역사 28명·체육 12명, 1차+2차)를 전부 정확히 채웠다.** LoRA 없이, JSON 강제 + 역할 분담 설계만으로.
- 최초 gemma-3-4b로 100% 달성 → 이후 사용자 요청으로 **Gemma 4 E4B로 교체, 재검증도 495/495 (100%)**. 최종 모델 = Gemma 4 E4B (사고 OFF, `-np 1`).

### 구현 완료 (전부 검증됨)
1. **`engine/hwpml/hwpx_grid.py` (신규)** — HWPX 파일 기반 표 그리드 파서+채움 공유 모듈. COM 불필요. 셀 주소 ID `s{섹션}_t{표}_r{행}_c{열}` (파싱·채움이 같은 표 순회 공유 → ID 일관성 보장). 병합=점유 맵, 헤더 행="상단 연속 병합 구간" 휴리스틱, 빈칸 라벨=행헤더×열헤더 코드 계산, 소형 표 요약이 다음 표 맥락으로 상속(과목 감지 8/8), 그리드 렌더링(병합 `>`/`^` 마커, 빈칸 `{셀ID}` 표기).
2. **`nodes/form_extract/main.py`** — HWPX 경로를 위 모듈로 교체 (선형 스트림+직전텍스트 라벨 폐기). 누름틀 추출 유지. 노드 인터페이스 테스트 OK.
3. **`nodes/form_fill/main.py`** — 그리드 좌표 ID 경로 추가 (legacy 라벨 경로는 폴백 유지).
4. **`engine/llm_manager.py`** — ctx 캡(4096) 해제(설정 `local_ctx` 우선), llama-server 경로 `C:/Users/sinbc/llama_cpp/` + 모델 경로 `C:/Users/sinbc/models/teacherflow/` 추가, `generate(json_schema=...)` — 로컬은 llama-server 스키마 강제 디코딩, API는 소프트 강제.
5. **`engine/chat_handler.py` + `engine/routes/live.py`** — 채팅 CVD를 HWPML 우선(extract_cvd mode=auto)으로 배선, 실패 시 커서 스캔 폴백. 편집 계약 유지.
6. **`scripts/benchmark_form_fill.py` (신규)** — 자동 채점 벤치마크. 레벨1(기계 왕복): 1126/1126 (100%). 레벨1.5(완벽 LLM 시뮬): 495/495. 레벨2(`--llm local`): **495/495 (100%)**. 파생값 검증(소계·반올림 평균·공동순위·합계·관리번호): 221/221. 결과는 `scripts/benchmark_last_result.json`.

### 환경 (이 노트북) — 2026-07-02 갱신
- **llama.cpp**: `C:\Users\sinbc\llama_cpp\llama-server.exe` (b9859, Vulkan — Arc 140V GPU 가속).
- **모델 (최종)**: `C:\Users\sinbc\models\teacherflow\gemma-4-E4B-it-Q4_K_M.gguf` (4.75GB, unsloth. hf-mirror.com 경유). **Gemma 4 E4B = 온디바이스(MatFormer) 4B급.** TeacherFlow와 goe가 이 하나를 공유.
  - 기존 gemma-3-4b(2.4GB)는 삭제(교체). Ollama(.ollama 3.1GB)도 삭제 — 회수.
- **⚠️ gemma-4는 "사고(reasoning)" 모델**: 기본적으로 추론을 `reasoning_content`에 쏟아 content가 빔. **반드시 사고 OFF로 사용** — 서버 `--reasoning off` 플래그(구조화·요약 작업엔 사고 불필요, 구형 노트북엔 속도 유리).
- **llama-server 기동 플래그 (표준)**: `--host 0.0.0.0 --port 8400 -c 8192 -np 1 -ngl 99 --jinja --reasoning off`
  - **`-np 1` 필수**: Arc 8GB에서 기본 4슬롯 KV캐시가 VRAM 초과 → **Vulkan device-lost 크래시**. 슬롯 1개로 제한해야 안정. (배포 시 8GB급 GPU 공통 주의)
  - `0.0.0.0` 바인딩 = Mac1(goe)이 Tailscale로 공유. `--jinja` = gemma-4 내장 챗 템플릿.
- **llm_manager 변경**: `_generate_local`이 수동 `<start_of_turn>` 템플릿 대신 **`/v1/chat/completions`**(내장 템플릿 자동) 사용. JSON 강제는 `response_format: json_schema`. `_start_llama_server`에 위 플래그 반영.
- **⚠️ 방화벽**: Windows가 llama-server.exe에 자동 **차단 규칙** 생성 → 제거하고 `llama-server Tailscale 8400`(TCP 8400, RemoteAddress 100.64.0.0/10 허용) 규칙 추가함(관리자 UAC). 재설치 시 재적용 필요.
- **디스크**: gemma-4 4.75GB 받은 후 C: **~1.8GB 여유** (455/456GB). 빠듯 — 추가 모델 받으려면 정리 필요.

### goe 메신저 요약기: ollama → llama.cpp 전환 완료 (2026-07-02)
사용자 확인: goe는 "로컬 LLM으로 메신저 요약 + 캘린더가 되는가" 실험이자 필요 기능.
- **아키텍처**: Mac1 cmd센터 → (Tailscale) → 이 노트북 llama-server :8400 (openai_compat). ollama(:11434) 폐기.
- **끝단 검증 성공**: Mac1 `helpers.llm.call_llm_json` → 노트북 gemma-4 → 분류·요약·마감일·중요도 JSON 정상. 요약 3연속 ~3-4s/건, device-lost 없음.
- **변경 파일**:
  - `sbc_lab/013_massenger/goe_watcher.py`: `is/start/stop_gemma`를 llama-server(:8400) 기준으로 재작성. 상수 `LLAMA_SERVER_EXE/LLAMA_MODEL/LLAMA_PORT/LLAMA_CTX`.
  - Mac1 `~/shared/discussions/llm_config.json`: `openai_compat` base_url `http://100.89.219.102:8400/v1` 추가.
  - Mac1 `~/shared/goe_data/config.json`: `llm={provider:openai_compat, model:gemma-4-E4B}`.
  - (미스터리 해소: goe가 쓰던 실제 모델은 config의 `gemma3:4b`. 드롭다운 `gemma4:e2b`는 목록 옵션일 뿐이었음.)
- **⚠️ 라이프사이클 주의**: goe의 gemma 토글 OFF 시 `reconcile_gemma`가 `stop_gemma()`로 llama-server를 kill → TeacherFlow도 같은 서버라 영향. 단 llm_manager가 다음 사용 때 자동 재기동(콜드스타트 ~15s)이라 기능상 무해. 완전 분리하려면 서버를 상시 서비스로 두고 토글은 "요청 여부"만 제어하도록 후속 개선.
- **TODO(goe)**: 마감일 연도 추론(모델이 2024로 가정) — goe 분류 프롬프트에 현재 날짜 주입 필요. gemma 토글 켜기 후 백로그 요약 실측.

### 소형 모델 실측 교훈
- 문법 강제만 걸면 소형 모델이 **배열을 공백으로 채우고 비워버리는** 함정 있음 → `minItems`/`maxItems`로 문법 차원에서 항목 강제 + 출력 예시 1줄(few-shot) 필수. 이 조합으로 gemma3 4B가 28명 명단도 무결 파싱.
- LLM에게 셀ID 매핑을 직접 시키지 말 것(출력 수천 토큰) → **LLM은 "비정형 텍스트→구조화 JSON"만**, 행 배치·셀ID·계산은 코드. (실제 제품 역할 분담과 동일)

### 남은 TODO (다음 세션)
- 노드 파이프라인에서 form_extract→LLM(local)→form_fill 워크플로우를 UI로 실행하는 E2E 확인.
- 3단계(증류): API 로깅 시작 + 공문서 익명화 파이프라인.
- goe 마감일 연도 주입 (분류 프롬프트에 현재 날짜).
- HWPML blockId→COM 좌표 캘리브레이션 (§5 gap #2, 라이브 편집 신뢰성).

## 10.5 작업 기록 — 2026-07-02 오후 ("이하빈칸" 마커 + 육안 검증 ✅)

1. **git 커밋**: 1단계 구현 전체를 df79ea7로 커밋 (사용자 승인).
2. **`hwpx_grid.py`에 마커 이동 구현**:
   - `find_below_marker(grid)` — 데이터 영역에서 "이하빈칸"/"이하여백" 행 탐지. 셀 하나 통짜든 한 글자씩 분산이든 행 단위 이어붙임으로 판정. 숫자만 있는 셀(선인쇄 관리번호)은 판정 제외.
   - `relocate_below_markers(doc, fill_map)` — 마커를 채운 마지막 행+1의 첫 "빈 행"(숫자만 있는 행 포함)으로 이동하는 추가 {셀ID:값} 계산. 빈 행 없으면(표 가득) 마커 제거 — 원본 관례와 동일(역사 1차 28명·체육 1차 12명 표에 마커 없음을 실측 확인). fill_map과 겹치는 키는 데이터 우선(setdefault 병합).
   - **원본 실측 규칙**: 마커는 c3~c6에 "이/하/빈/칸" 분산, 역사 2차(t13)는 마커 행에 관리번호 "4" 선인쇄 → "숫자만=빈 행" 규칙 필요.
3. **form_fill 노드 연결**: `_fill_hwpx` 그리드 경로에서 자동 실행. 채우는 표만 이동, 안 채우는 표는 유지 확인.
4. **벤치마크 확장** (`run_marker_test`): "새 양식"(데이터 클리어+마커를 첫 데이터 행에 배치) 시뮬 → 채움+relocate → 원본과 **전체 셀** 비교. **1126/1126 (100%)** — 마커 6개 표 전부 원위치 복귀(t13 r5 포함).
5. **한/글 육안 검증 완료**: 마커이동.hwpx를 한글 2024로 열어 1p(러시아어 1차)·5p(프랑스어 2차)·7p(역사 2차) 확인 — 병합 헤더·셀 배경·테두리·폰트 전부 정상, 마커 위치 원본과 동일. **서식 손상 없음 확정.**

**참고 파일**:
- 역공학 문서: `inline structure/` (03=실행흐름, 06=실제코드, 07=v0.3.1, 09=HWPML구조, 10=API트래픽)
- 현재 구현: `engine/hwp_controller.py`, `engine/hwpml/{parser,position_engine,cvd_builder,hwpx_grid}.py`
- LLM: `engine/llm_manager.py`, `engine/memory_manager.py`
- 노드: `nodes/form_extract/`, `nodes/form_fill/`, `nodes/llm_generate/`, `nodes/md_to_hwpx/`
- 벤치마크: `scripts/benchmark_form_fill.py` (기준 파일: 바탕화면 채용점수표 hwpx)
