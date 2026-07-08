# 로컬 LLM 전환 설계 — 핸드오프 문서

> 작성: 2026-07-02 / 프로젝트: TeacherFlow (`C:\Users\sinbc\OneDrive\바탕 화면\00_sbc_final`)
> 목적: 이 문서만 읽고 새 세션에서 바로 이어서 작업할 수 있게 정리.

> ## ⏩ 다음 세션은 여기부터 (2026-07-08 Desktop 갱신)
> **다음 작업 = §14 「노드/엣지/워크플로우 전면 점검·개선」** (사용자 지시, 새 세션 시작). 환경·실행법은 §11, 최근 완료는 §12·13.
> ⚠️ 이 프로젝트는 이제 **Desktop(`C:\Users\PC\Desktop\inline structure - 복사본\00_sbc_final\00_sbc_final`, RTX5080)** 에서 작업. 노트북(sinbc) 경로/§10.6 goe_watcher 이슈는 Desktop엔 **해당 없음**.
>
> **Desktop에서 완료 (2026-07-08)**:
> - 로컬 gemma(E4B Q3) 벤치 495/495 Desktop 재현 + 엔진 부팅 (§11)
> - 라이브 COM 실증: 한/글 문단편집·엑셀 수식표·복잡 병합표(신병철 채용1위) (§11 데모)
> - `llm_manager.generate_chat` 로컬 분기 추가 → 라이브 로컬 LLM 성공 (§11)
> - 코드 모듈화: `live_controller`→`engine/live/`, `hwp_controller`→`engine/hwp/`, `chat_handler`→`engine/chat/` (무중단 facade) (§12)
> - 새 문서 생성 검증 + md_to_hwpx 표드롭 버그 수정 + 표 디자인(헤더음영·열너비) 개선 (§13)
>
> **테스트 모델**: Gemma 3n **E4B**(유효 4B). E2B(2B) 미검증 — §13 끝 참고.
> **Git**: 원격 `github.com/sinbc2003/sbc_final`. `data/fixtures/`(PII·데모)는 .gitignore.
> **환경 주의**: C: 꽉 참(모델·llama.cpp는 D:). llama-server는 엔진이 자동기동. 공유 GPU라 작업 후 종료로 VRAM 반납.

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
- 노드 파이프라인에서 form_extract→LLM(local)→form_fill 워크플로우를 UI로 실행하는 E2E 확인. ※ 로컬 LLM 필요 — 메모리 여유 시.
- 라이브 채팅(로컬 gemma) 실전 검증 재시도 — §10.6의 3가지 차단 요인 해소 후.
- 3단계(증류): API 로깅 시작 + 공문서 익명화 파이프라인. ※ 익명화 원본 문서 위치는 사용자에게 확인.
- ~~goe 마감일 연도 주입~~ → **§10.8에서 해결** (Mac1 배포 완료).
- HWPML blockId→COM 좌표 캘리브레이션 (§5 gap #2, 라이브 편집 신뢰성).
- ~~md_to_hwpx 내장 빌더 버그~~ → **§10.7에서 해결** (python-hwpx 경로 추가).

## 10.7 작업 기록 — 2026-07-02 저녁 (md_to_hwpx "파일 손상" 버그 해결 ✅)

**증상**: md_to_hwpx 내장 빌더(3순위 폴백) 산출물을 한글 2024가 "파일이 손상되었습니다"로 거부.
**원인 (실측)**: 내장 빌더의 XML 구조 위반 — `hp:secPr`·`hp:tbl`을 `hs:sec` 직속에 배치 (실제 HWPX는 첫 문단 run 안에 있어야 함). 추가로 `_preprocess_md_for_hwpx`가 **빈 표 셀을 "."으로 치환**(pypandoc-hwpx 버그 회피용)해 양식 빈칸을 파괴하는 문제도 발견.
**해결**: 이미 설치돼 있던 **python-hwpx 2.10.0 라이브러리의 builder API** 사용 경로를 3순위로 추가 (내장 빌더는 4순위 최후 수단으로 강등). 새 우선순위: pypandoc-hwpx → kordoc → **python-hwpx** → 내장 빌더.
- `_md_to_builder_children`: md 블록 파서 (헤딩·문단·표·불릿·번호 리스트). **원본 md 사용** (전처리의 "." 치환 미적용 → 빈 셀 보존, 양식 생성 가능).
- 표 병합: `>`(왼쪽과 병합)·`^`(위와 병합) 마커 → "A1:B2" 범위 변환 (`_compute_table_merges`). 빈 셀은 병합으로 취급 안 함 (legacy와 다름 — 의도적).
- **bold run 함정**: 라이브러리 bold 기본 charPr이 18pt → `size=10` 명시로 본문 크기 유지.
- 라이브러리 저장 시 자체 검증(패키지·스키마·재열기 hard gates) 수행 — gates 실패 시 내장 빌더로 폴백.
**검증**: 한글 2024 실제 열기 (제목·표·병합·bold 정상, 손상 경고 없음) + hwpx_grid 파싱 + extract_blank_fields 빈칸 6개 라벨 정상 + 엣지(표만/수식/리스트 혼합) 통과. ※ test_all_nodes.py는 엔진 서버(:8321) 필요해 이 환경에선 원래 전부 skip — 회귀 아님.
**의의**: "양식 없음 → LLM 생성 md → hwpx 출력" 경로가 이제 실제로 한/글에서 열리는 문서를 만든다. 로컬 LLM 불필요 작업이라 메모리 부족 상황에서 수행.

## 10.8 작업 기록 — 2026-07-02 저녁 (goe 마감일 연도 오류 해결 ✅, Mac1 배포)

**대상**: Mac1 `~/shared/command-center/helpers/goe.py` (백업: `goe.py.bak_20260702`).
**문제**: 소형 모델(gemma)이 deadline을 학습데이터 연도(2024)로 가정. 기존 구조는 파이썬 해석기(`resolve_deadline`) 우선 + 상대 표현 불신까지 돼 있었으나, **파이썬이 못 푼 절대형 표현은 LLM 날짜를 그대로 신뢰**하는 구멍.
**수정 2건 (최소 diff)**:
1. `CLASSIFY_SYSTEM` 프롬프트에 "deadline 연도는 발신일과 같은 해 또는 이후, 과거 연도 금지" 지시 추가.
2. `_final_deadline`에 결정적 연도 보정: LLM 날짜의 연도 < 발신일 연도면 월·일 유지 + 발신일 연도로 재계산, 그 날짜가 발신일보다 182일 이상 과거면 +1년 롤 (`resolve_deadline`의 roll()과 동일 규칙).
**검증**: Mac1에서 단위 테스트 6/6 통과 (파이썬 우선·상대 불신 기존 동작 유지 + 신규 보정 2케이스 + 프롬프트 포함). cmd센터 재시작(KeepAlive 자동 재기동, PID 91728) 후 `/api/goe/stats` 정상.
**실측 검증 잔여**: gemma 켜진 상태에서 새 쪽지 요약 시 연도 확인 (메모리 여유 시).

## 10.6 작업 기록 — 2026-07-02 저녁 (라이브 채팅 실전 데모 시도 → 중단, 원인 3개 확보)

**목표였던 것**: 한/글 열어두고 `/api/chat/live`(preview=false, model=local)로 로컬 gemma가 실시간 문서 편집하는 모습 확인. **사용자 질문 "실시간 스트리밍 제어 볼 수 있나"에 대한 답 = 구조상 가능** (COM 캐럿·선택 이동이 화면에 그대로 보임, Inline AI와 같은 원리).

**확인된 것 (동작함)**:
- 엔진(uvicorn :8406) 기동, `/api/live/connect/hwp` COM 연결, `/api/live/execute/hwp` insert_text 실전 성공 — 화면에서 텍스트 삽입 확인.
- `/api/chat/live` 파이프라인 진입: CVD 스캔(캐럿 훑기)까지 화면에서 관찰됨.

**라이브 로컬 LLM이 실패한 원인 3개 (전부 실측)**:
1. **goe_watcher가 llama-server를 계속 kill**: CC gemma 토글 off 상태에서 `reconcile_gemma`가 매 틱 `taskkill /F /IM llama-server.exe` — TeacherFlow가 띄운 서버도 무차별 종료. §10 "라이프사이클 주의"의 실증. **근본 해결 = llama-server 상시 서비스 분리, goe 토글은 '요청 여부'만 제어**.
2. **goe_watcher 중복 2개 실행 발견** → 동시 기동 경합. 중복 1개 정리함(PID 25468 kill, 10544 유지). **자동시작 등록이 2개인지 확인 필요**.
3. **VRAM 부족 (Vulkan ErrorOutOfDeviceMemory)**: 다른 작업(run_fig 4샤드) 상주 중엔 4.75GB 모델 로드 실패. Arc 140V는 공유 메모리라 램 여유 = VRAM 여유. **로컬 LLM 작업은 무거운 배치 작업과 동시 실행 불가** — 배포 설계에도 반영할 것 (램 감지 후 로드 시점 결정).

**추가 발견**:
- `generate_chat`의 local 분기 부재 → 폴백이 messages를 `[role] content` 문자열로 합쳐 `generate()`에 전달. 로컬용 채팅 경로(`/v1/chat/completions` messages 직통)를 llm_manager에 추가하는 게 맞음 (2단계 작업에 포함).
- **md_to_hwpx 내장 빌더 산출물 손상**: pypandoc-hwpx/kordoc 미설치라 내장 빌더로 폴백됐고, 그 hwpx를 한글 2024가 "파일이 손상되었습니다"로 거부. 별도 수정 필요 (또는 pdf2hwpx(#008) 연동).
- 데모 종료 시 원상복구 완료: CC 토글 off, 엔진·데모 한/글 종료, run_fig 등 사용자 작업 무접촉.

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

---

## 11. 작업 기록 — 2026-07-08 (Desktop 이식·검증 ✅ + inline-ai v0.4.4 관찰)

> 이 프로젝트를 노트북 → **Desktop(coka_desktop, Ryzen 9800X3D 64GB, RTX5080 16GB)** 으로 복사해온 뒤, 로컬 gemma 파이프라인이 이 데스크톱에서 동작하는지 검증. 경로: `C:\Users\PC\Desktop\inline structure - 복사본\00_sbc_final\00_sbc_final`.

### 🎯 헤드라인: Desktop에서 로컬 gemma 벤치마크 495/495 (100%) 재현 + 엔진 제품 부팅 확인
노트북(Arc 140V)에서만 검증됐던 파이프라인이 **Desktop RTX5080 CUDA에서도 100% 동일 재현**. Q3_K_S(노트북 Q4_K_M보다 더 공격적인 양자화)로도 495/495.

### Desktop 환경 (실측)
- **llama.cpp**: `D:\models\llama_cpp\bin\llama-server.exe` (CUDA 빌드, ggml-cuda.dll). RTX5080 = compute capability 12.0(Blackwell/sm_120) 정상 인식·로드. 43/43 레이어 GPU 오프로드, VRAM ~7.7GB.
- **모델**: `D:\models\teacherflow\gemma-4-E4B-it-Q3_K_S.gguf` (3.68GB). ※ 노트북은 Q4_K_M. **llm_manager 검색경로에 `D:/models/teacherflow` + `D:/models/llama_cpp/bin/llama-server.exe`가 이미 있어 코드 수정 없이 인식됨.**
- **속도**: 웜업 후 **110~131 tok/s** (첫 요청은 CUDA 그래프 웜업으로 ~24s 콜드스타트). 노트북 대비 압도적.
- **Python**: 3.10.11 (`C:\Users\PC\AppData\Local\Programs\Python\Python310`). 핵심 의존성 전부 설치됨(fastapi 0.129, uvicorn, pymupdf, pandas, python-hwpx 2.10.3, tabulate, psutil, pyyaml). requirements.txt엔 fastapi/uvicorn/python-hwpx 누락 — 별도 설치 상태.
- **한/글**: Office 2018/2020/2024 설치됨 → 라이브 COM 제어 가능. `WOW6432Node\HNC\Hwp` 등록됨.
- **디스크**: C: 3.8GB만 여유(꽉 참) → 모델·llama.cpp는 반드시 D:(59GB)/E:(357GB)에. C:에 큰 파일 금지.

### 검증 결과
- **스모크**: `/v1/chat/completions` + `response_format:json_schema` → 한글 이름·점수 4개 배열 정확 추출(홍길동/김철수/이영희). 콘솔 표시만 cp949로 깨지고 파일(UTF-8)은 정상.
- **벤치마크** (`scripts/benchmark_form_fill.py --llm local`): 레벨1 왕복 1126/1126, 마커 1126/1126, **레벨2 로컬 gemma 495/495 (100%)**. 8개 표(러시아어·프랑스어·역사 28명·체육 12명, 1·2차) 전부 정확.
- **엔진 제품 부팅** (`python -m engine.server`, ENGINE_PORT=8407): uvicorn 정상, 58개 라우트, `/api/models`가 로컬 gemma 인식, `/api/system` recommended_quant=Q6(RAM 61.6GB) 보고.

### 이식 수정 (최소 diff)
- `scripts/benchmark_form_fill.py`: `ORIGINAL` 하드코딩(노트북 바탕화면 경로) → `_resolve_original()`로 교체. 우선순위 **환경변수 `BENCH_HWPX` > `data/fixtures/bench_score.hwpx` > 노트북 원본**. `import os` 추가. → 노트북/데스크톱 어디서나 동작.
- 기준 hwpx는 노트북에서 scp로 가져와 `data/fixtures/bench_score.hwpx`에 배치(81555B). (노트북 100.89.219.102 SSH 접근 확인됨.)
- **`engine/llm_manager.py`: `generate_chat`에 로컬 분기 신규 추가** (§10.6·2단계 TODO 해결). 기존엔 provider=local이 fallback으로 빠져 messages를 `[role] content` 문자열로 뭉개 단일 user로 보냄 → 스킬 시스템 프롬프트의 역할 소실. 이제 `_generate_local_chat()`이 messages 역할 배열을 `/v1/chat/completions`에 직통 → 내장 chat 템플릿이 system/user 정확 적용. 서버기동/호출 로직은 `_ensure_local_server()`/`_local_chat_completion()`로 공통화(기존 `_generate_local` 동작 불변). **이 수정이 라이브 로컬 LLM 성공의 핵심.**

### 라이브 COM 데모 ✅ (로컬 gemma가 실제 한/글 편집 — §10.6 미검증 항목 해결)
**노트북에서 3대 차단요인(goe_watcher kill / watcher 중복 / VRAM)으로 못 했던 라이브 로컬 LLM 편집을 Desktop에서 성공.**
- 흐름(실제 코드 경로 `chat_handler.handle_live_chat` 그대로): 한/글에 안내문 3문단 초안 생성 → `_read_with_cvd`가 스캔→block_id CVD 매핑(`<1>여름방학 안내` …) → 로컬 gemma가 편집 지시 이해 → 액션 JSON 생성 → COM 실행 → 검증.
- 지시 "제목을 '2026학년도 여름방학 생활 안내 가정통신문'으로 바꿔줘" → gemma 출력 `[{"action":"replace_paragraph","params":{"block_id":"1","new_text":"2026학년도 여름방학 생활 안내 가정통신문"}}]` (block_id 정확 식별) → 실행 성공("문단 교체 완료") → 편집 후 제목 실제 변경 확인.
- 결과 파일: `data/fixtures/live_demo_result.hwpx` (재파싱 검증: 편집 제목 포함 True, 원제목 잔존 False). 데모 스크립트: 세션 scratchpad `live_demo.py`.
- **의의**: inline-ai의 "포인터 훑기 → blockId → 정확히 채우기" 라이브 편집을 **소형 로컬 gemma(Q3)로 재현**. blockId 시스템이 모델에게 떠먹여 주므로 Q3로도 액션 JSON 정확 생성(§2 설계 가설 실증). HWP 자동화 보안모듈 `FilePathCheckerModule`(pyhwpx) 등록돼 있어 대화상자 없음.

### Desktop에서 실행법 (다음 세션용)
```
# 1) 로컬 LLM 서버 (엔진이 자동 기동하나 수동도 가능)
D:\models\llama_cpp\bin\llama-server.exe -m D:\models\teacherflow\gemma-4-E4B-it-Q3_K_S.gguf \
  --host 127.0.0.1 --port 8400 -c 8192 -np 1 -ngl 99 --jinja --reasoning off
# 2) 벤치마크(로컬 gemma)
set PYTHONUTF8=1 && python scripts\benchmark_form_fill.py --llm local
# 3) 엔진 서버
set PYTHONUTF8=1 && set ENGINE_PORT=8407 && python -m engine.server   # http://127.0.0.1:8407/docs
```
- RTX5080은 전용 16GB VRAM → 노트북 §10.6의 라이브 로컬 LLM 3대 차단요인(goe_watcher kill / watcher 중복 / VRAM부족) **전부 해당 없음**. 라이브 COM 데모의 최적 환경.

### 라이브 다중액션·엑셀·복잡표 데모 ✅ (2026-07-08 추가 — 로컬 gemma)
- **엑셀 라이브(win32com)**: `LiveController.connect("excel")`(pywin32) + `handle_live_chat(app_type="excel", provider=local)`. gemma가 "성적표 만들어줘(3명·총점/평균)" → 8액션(set_cell/set_cells×3/format_range/border/auto_fit) 생성, **총점=`=SUM(B3:D3)`·평균=`=AVERAGE(B3:D3)` 수식 사용**(계산은 Excel에 위임 = 설계 철학 그대로) → 8/8 실행 성공, Excel이 255/273/245 실계산. 결과 `D:\성적표_엑셀라이브데모.xlsx`. ※ xlwings 0.36.8 설치했으나 실제 라이브 경로는 win32com. (설치 inline-ai v0.4.4는 xlwings 사용 — 열린 엑셀 실시간엔 어느 쪽이든 가능.)
- **복잡 병합표 채우기(신병철 데모)**: `D:\2024...채용점수표.hwpx`의 역사 2차 최종표(t13)에 가상인물 '신병철'을 채용 1위로 완성. gemma가 자연어 점수설명→JSON 파싱(의미 매칭), 코드가 소계/평균/합계 계산·순위 재산정(신1·김화평2·이진숙3·오승택4)·최종선정자 교체·이하빈칸 마커 이동. `fill_hwpx_cells`(결정적 그리드, COM-free) 18/18 주입, 재파싱 검증 True. 결과 `D:\신병철_역사_채용1위.hwpx`(한/글 정상 열림). → **복잡 병합표는 라이브 COM(§5 약점)이 아니라 검증된 그리드 경로로 채우는 게 정답**(벤치 495/495와 동일 경로). 라이브 COM은 단순 인플레이스 편집용.
- 데모 스크립트(세션 scratchpad): `live_demo.py`(HWP 문단), `build_shin.py`(신병철 표), `excel_demo.py`(엑셀).

### 권장 다음 작업 (Desktop 우위 활용)
- **모델 품질 업그레이드**: Q3_K_S(현재) → Q4_K_M(벤치 검증본) 또는 Q6(RAM 프로필 권장). 16GB VRAM 여유 충분. 어려운 실전 문서 대비 헤드룸. (`-np`는 전용 GPU라 2~4로 올려도 안전.)
- **HTTP E2E**: 위 데모는 `handle_live_chat` 직호출(단일 COM 스레드). `/api/chat/live` HTTP 엔드포인트로 프론트 연결 E2E 검증 남음.
- **3단계 LoRA 증류**: RTX5080이 학습 장비(§8 3단계). 이 데스크톱이 그 작업의 본진.

### inline-ai v0.4.4 관찰 (리버싱 아님 — 설치본 구조만 확인)
설치본 `C:\Users\PC\AppData\Local\Programs\inline-ai\` = **v0.4.4** (RE 문서는 v0.2.12/v0.3.1 기준, 2버전 최신). 워커 4개로 재편(파일/폴더 구조 관찰):
| 워커 | 포함 라이브러리 | 역할(추정) |
|---|---|---|
| `agent_document_tool_executor` | pyhwpx, **xlwings**, pandas, calamine, PIL | 라이브 문서 편집(HWP+Excel COM) |
| `document_interaction_worker` | pyhwpx, xlwings, calamine | 열린 문서 상태감지·읽기 |
| `local_file_tool_executor` | docx, pptx, pypdfium2, calamine | 업로드 파일 읽기(any→text) |
| `local_search_index_worker` | (단독) | 작업폴더 로컬 검색 인덱싱(RAG) |
- **시사점**: v0.4.4는 Excel을 **xlwings로 라이브 제어**(openpyxl 파일주입 아님). 우리 form_fill의 XLSX는 openpyxl 좌표주입 — "열린 엑셀 실시간 제어"가 필요하면 xlwings 경로 검토. 나머지(2단계 읽기·blockId·code-as-action)는 07/10 문서 그대로. code-as-action은 소형 모델 부적합이라 우리 선언형 JSON 유지 판단 그대로 유효.

---

## 12. 작업 기록 — 2026-07-08 (한/글 느림 진단 + 코드 모듈화 ✅)

### 한/글 열기 느림 — 원인 규명 (재설치 불필요)
증상: 모든 한/글 파일이 열 때 오래 걸림. **실측: 콜드스타트 ~54초, 웜(이미 실행 중)은 0.1초.** 즉 시작 과정이 느린 것이지 문서/엔진 문제 아님.
- **주원인 = AhnLab V3 Lite 실시간 검사**(`v3l4sp` 상주, Windows Defender는 이 때문에 passive). 콜드 실행 시 한/글의 수백 개 DLL을 매번 스캔.
- **부원인 = USB Canon 프린터가 기본 프린터**(한/글 시작 시 용지정보 조회 → 프린터 꺼져있으면 대기). 프린터를 Print-to-PDF로 바꾸니 COM 콜드 83s→51s(약 30s 단축).
- **한컴 빠른실행(preloader) 미실행** → 매번 콜드.
- **해결(임팩트순)**: ① V3 예외에 `C:\Program Files (x86)\Hnc` 폴더 추가(관리자 V3 UI) ② 한컴 빠른실행 상주 켜기(첫 실행 후 즉시) ③ 기본 프린터 → "Microsoft Print to PDF". (테스트 시 기본 프린터는 원상 복원해 둠.)

### 코드 모듈화 — 거대 단일 파일 2개 → 패키지 (무중단 facade, 행위보존)
전체는 이미 모듈화(engine/·nodes/·hwpml/·routes/)돼 있었고, 남은 monolith 2개만 분할:
- **`live_controller.py`(1182줄) → `engine/live/`** (9파일): base(데이터클래스·HWP싱글턴·유틸)/schemas/controller(감지·연결·디스패치) + 앱별 mixin `{hwp,excel,ppt,word}.py`. `LiveController(HwpMixin,ExcelMixin,PptMixin,WordMixin)`.
- **`hwp_controller.py`(1768줄) → `engine/hwp/`** (7파일): models(Block/DocumentInfo)/blocks(BlockManager)/scanner(DocumentScanner)/editor(HwpEditor)/controller(HwpController)/schemas. AST로 클래스 줄범위 정확 슬라이스(기계적 분할, 전사오류 0).
- **`chat_handler.py`(770줄) → `engine/chat/`** (4파일): intake(양식의도·파일/지시문 추출)/workflow(handle_chat·양식 assist)/live_chat(handle_live_chat·_read_with_cvd·parse_actions_response). AST 슬라이스.
- **무중단**: `live_controller.py`·`hwp_controller.py`·`chat_handler.py`는 각각 27·23·25줄 facade로 남아 기존 심볼 재노출 → 기존 import 전부 무수정.
- **검증**: 컴파일·메서드완전성·교차모듈배선·다운스트림import·싱글턴 + 벤치마크 1126/1126 + Excel COM 스모크(connect→set_cell/formula→get_cell=30) + **HWP 라이브 데모 3회 재실행**(각 리팩터 후 스캔→gemma→편집→제목교체·본문보존 확인) + FastAPI 앱 조립(66 라우트).
- **⚠️ 교훈(chat 분할 시 실제 발생)**: `handle_live_chat`의 `Path(__file__).parent/"skills"`가 `engine/chat/live_chat.py`로 내려가며 `engine/chat/skills`(없음)를 가리켜 "스킬 없음: hwp" 리그레션 → `.parent.parent`로 수정. **import 검사로는 안 잡히고 라이브 데모(런타임)로만 잡힘.** 서브패키지로 함수 이동 시 `__file__` 상대경로 전수 점검 필수.
- **남은 큰 파일은 분할 보류 권장**: `hwpml/parser.py`(826)·`form_assist.py`(634)는 **단일 관심사(파싱/양식처리)라 응집적** — 쪼개면 간접참조만 늘고 이득 적음. 컨트롤러·chat_handler(여러 관심사 혼재)와 성격 다름.

---

## 13. 작업 기록 — 2026-07-08 (새 문서 '지가 만들기' 생성 검증 ✅ + md_to_hwpx 표 드롭 버그 수정)

목표의 나머지 절반(빈칸채우기 외 "새 양식 지가 만들기") 로컬 검증. 로컬 gemma가 가정통신문을 백지에서 작성 → hwpx.
- **생성 품질: 양호**. 스캐폴드 시스템 프롬프트(개조식 섹션·표틀 제시)에 gemma가 내용만 채움(지능의 코드화). "여름방학 안전 가정통신문"(제목·인사말·안내표·당부3·마무리·날짜·학교장) **~5초, 511자, 구조 정확·내용 적절**. → 반정형 문서(가정통신문·공문)는 **LoRA 없이도 로컬 생성 가능**. LoRA는 품질 상향·장문(10p+ 계획서)용, 필수 아님.
- **발견 1 (소형모델 약점) — 연도**: gemma가 날짜 연도를 학습기본값 **2024**로 씀(월·일은 정확). goe §10.8과 동일. **해결책: 생성 프롬프트에 현재 날짜 주입**(코드). 데모에선 후처리 `2024년→2026년`로 교정.
- **발견 2 (실제 버그, 수정함) — pypandoc-hwpx 표 드롭**: 이 데스크톱엔 pypandoc-hwpx 설치돼 1순위로 쓰이는데, **마크다운 표를 통째로 드롭**(hp:tbl 0, 안내표·날짜 소실)했다. python-hwpx 경로(§10.7 검증)는 표 정상. **수정**: `nodes/md_to_hwpx/main.py`에 `_md_has_table`/`_hwpx_has_table`/`_table_fidelity_ok` 추가 → pypandoc/kordoc 변환 후 "표 있었는데 결과에 표 없음"이면 폴백. 검증: 로그 "pypandoc-hwpx 표 누락 감지 — python-hwpx로 폴백" → hp:tbl 1개 보존, 한/글 정상 열림. 결과 `data/fixtures/가정통신문_최종.hwpx`.
- **의의**: 생성(자유양식) 경로가 이제 표 포함 문서를 온전히 만든다. 빈칸채우기(§7)에 이어 **생성 절반도 로컬로 실증** — 목표의 두 축 모두 로컬 동작 확인.
- 데모 스크립트(scratchpad): `gen_doc.py`·`gen_fix.py`·`gen_verify.py`.
- **다음 후보**: ① 생성 프롬프트에 현재날짜 주입(연도버그 근본해결) ② 장문(계획서) 개요→절단위 생성 파이프라인(§8 4단계) ③ 다양한 문서유형(공문·회의록) 생성 품질 실측.

### 표 디자인 개선 (2026-07-08 — "표가 너무 구림" 피드백 반영 ✅)
생성 표가 밋밋(모든 셀 균등폭·헤더 음영 없음)했던 문제 수정. `nodes/md_to_hwpx/main.py` python-hwpx 경로:
- **헤더 음영**: `TABLE_HEADER_SHADE="#D9E1F2"`(연한 파랑-회색) → `Table(header_shading=...)`. borderFill 추가 확인.
- **열 너비 차등**: `_table_column_weights()`가 열별 최대 텍스트 길이(한글=2, 최소3) 비례 가중치 계산 → `column_widths=`. 실측: 라벨열 1728 vs 내용열 12672(mm 단위 내부값)로 차등. 라벨 좁게·내용 넓게.
- 검증: hard-gate 통과, 한/글 정상 열림. ※ 헤더 **볼드·가운데정렬**은 python-hwpx Table 빌더가 미노출(저수준 charPr) — 추가 폴리시 원하면 후속.
- (라이브 COM `create_table`은 이미 `style_table_row`/`set_table_widths` 등 서식 op 보유 — 이번 수정은 파일생성(md_to_hwpx) 경로 전용.)

### ⚠️ 테스트 모델 명확화
지금까지 로컬 테스트는 전부 **Gemma 3n E4B**(`gemma-4-E4B-it-Q3_K_S.gguf`, 유효 4B급, MatFormer)로 수행. **E2B(유효 2B, 8GB 구형노트북용)로는 미검증.** 배포 타깃이 8GB 노트북이면 E2B에서 벤치·생성 품질 재측정 필요(빈칸채우기는 E2B도 될 가능성 높으나 장문생성은 열화 예상).

---

## 14. ⏭️ 다음 세션 작업 지시 — 노드/엣지/워크플로우 전면 점검·개선

> 사용자 요청(2026-07-08): "sbc_final 기능 전체 검토, 노드 엣지 연결·워크플로우 설계 쉽게 되는지 치밀하게 점검·개선." **이 작업은 새 세션에서 시작.** 아래는 진입용 스코프.

**대상 시스템** (노드 에디터 = 이 제품의 '코딩 없이 자동화' 핵심 UX):
- 프론트: `src/` React 노드 에디터 (드래그&드롭 노드 연결, ComfyUI/Orange3 류).
- 백엔드: `engine/loader.py`(nodes/ 스캔→node.yaml 파싱→execute 동적로드), `engine/runner.py`(DAG 위상정렬→순차 execute), `engine/types.py`(타입: file/text/table/image/list/any), `nodes/`(31개).

**점검 항목 (권장 순서)**:
1. **타입/엣지 정합성**: node.yaml의 입출력 타입 선언 vs 실제 execute 반환. 엣지 연결 시 타입 호환 검증이 있는지(런타임/UI). 비호환 연결 차단·경고 UX.
2. **노드 계약 감사**: 31개 노드 각 node.yaml(입출력·파라미터) ↔ main.py execute 시그니처 일치, 에러 처리(누락 입력·변환 실패), 로컬 provider 지원 여부(llm_* 노드).
3. **워크플로우 E2E**: 대표 워크플로우(form_extract→llm_local→form_fill / 파일→md→생성) 실제 빌드·실행. runner의 위상정렬·에러 전파·중간 결과 확인. (엔진 :8406, 프론트 :1420.)
4. **설계 UX 마찰**: 노드 검색·추가·연결·실행·결과확인 흐름의 마찰점. 프리셋·자동배치·저장/복원.
5. **개선**: 위에서 나온 결함 수정 + '쉽게 설계' 걸림돌 제거. (facade 패턴·검증 자동화는 이번 세션 참고.)

**참고**: 이번 세션에 `engine/live/`·`engine/hwp/`·`engine/chat/` 모듈화 + md_to_hwpx 표수정/생성검증 완료(§12·13). 벤치마크(`scripts/benchmark_form_fill.py --llm local`)가 회귀 안전망. 모델·경로·실행법은 §11.

---

## 15. 작업 기록 — 2026-07-08 (§14 노드/워크플로우 전면 감사 + 결함 수정 진행 중)

> 40-에이전트 워크플로우 감사(노드 31 계약 + 엔진 4방면 + 프론트 4방면 + E2E)로 **177개 원시 발견 → 적대적 검증 → 53개 확정 결함**. (검증 도중 Anthropic 세션 한도로 일부 verify 미완 → "기각"에 미검증 포함 가능, 확정 53건은 신뢰.) 확정 결함 원문: 세션 scratchpad `confirmed_findings.md`.
> **수정 우선순위 = 소형 로컬 모델 목표 렌즈**: 추출→채우기 파이프라인, 오류 가시성, 스키마 강제부터.

### 확정 결함 분포 (high 6 / medium 23 / low 24)
- **A. table 페이로드 규약 불일치**(high, #0·1·5): 노드마다 "table"이 records/시트래퍼/헤더행리스트로 제각각 → 연결 시 조용한 데이터 오염 또는 크래시. **llm_extract→hwpx_fill(추출→양식 대량생성)이 대표 워크플로우인데 크래시**.
- **B. 필수입력 미검증 → raw KeyError**(medium/low ~15건): 노드가 `inputs["파일"]` 직접 인덱싱, 러너에 사전검증 없음 → "실행 실패: '파일'"만 노출. **러너 한 곳 수정으로 일괄 해소 가능**.
- **C. 채우기 크래시·손상**(high, #2·3·4): form_fill etree NameError(레거시 경로 항상 죽음), hwpx_fill XML 이스케이프 누락(& < > → 파일 손상), RegisterModule 인자 오류(교사 PC 배포 시 보안대화상자 블로킹).
- **D. llm_extract JSON 파싱 취약**(#20·48): 탐욕 정규식+무음 빈테이블, json_schema 강제 미사용(엔진은 지원). **소형 모델 신뢰성 직결**.
- **E. kordoc npx.cmd Windows 죽은 코드**(#15·17·31·39·42): `subprocess.run(["npx",...])`가 .cmd 실행 못해 Windows에서 1순위 변환기 항상 폴백 + cp949 인코딩.
- **F. 무음 실패**(#7·10·49): 변환 실패를 빈 출력으로 "성공" 처리.
- G. 계약 드리프트/데드코드(low 다수): .xls 미지원 선언, lora no-op(#22·51), pages 무시(#28) 등.

### ✅ 수정 완료
1. **llm_extract 소형모델 견고화** (#5·20·48) — `nodes/llm_extract/{main.py,node.yaml}`:
   - 출력을 **records(list[dict], 키=필드명)**로 표준화(생태계 규약 일치 → hwpx_fill `row.get()` 크래시 해소). 기존은 헤더행+2D리스트라 모든 소비 노드에서 크래시/오출력.
   - **json_schema 강제 디코딩 배선**: `_build_schema(fields)`(array of objects, required=필드) → `llm.generate(json_schema=...)`. 로컬 llama-server가 GBNF로 강제(벤치와 동일 메커니즘). 소형 모델이 형식을 못 틀림.
   - **견고한 파싱**: 코드펜스 제거 → 전체 JSON → 비탐욕 객체배열 → 일반배열 순. dict 래퍼(`{"결과":[...]}`)·단일객체·위치리스트 흡수. **파싱 실패는 `None`으로 구분 → 무음 빈테이블 대신 `[WARN]` 로그+원문 스니펫**. 오프라인 6케이스 검증 통과.
2. **hwpx_fill 손상·소실 수정** (#3·12·13) — `nodes/hwpx_fill/{main.py,node.yaml}`:
   - **XML 이스케이프**(`xml.sax.saxutils.escape`): 치환값의 `& < >` 이스케이프 → `진로&직업`·`<검토>` 넣어도 well-formed(합성 템플릿 검증). 미치환 `{{키}}`는 원문 유지(이스케이프 안 함).
   - **다중행 파일명에 행 인덱스 접두어**(`{idx+1:03d}_이름.hwpx`): 동명이인 덮어쓰기·ZIP 중복 방지.
   - 출력 accept `[.hwpx]`→`[.hwpx, .zip]`(다중행은 실제 .zip 반환 → 계약 일치).

3. **form_fill / hwp_to_hwpx 크래시·배포차단** (#2·4) — `nodes/form_fill/main.py`, `nodes/hwp_to_hwpx/main.py`:
   - **etree 스코프 수정**(#2): `_fill_hwpx_section`(모듈 레벨 함수)이 `_fill_hwpx`의 지역 `etree` import를 못 봐 누름틀/라벨 키 경로에서 항상 `NameError`. 함수 내 `from lxml import etree` 추가. 네임스페이스 section XML로 검증(라벨 "이름"→빈 `<hp:t>`에 값 주입 성공).
   - **RegisterModule 인자 수정**(#4): `"FilePathCheckerModuleExample"`(예제 DLL명)→`"FilePathCheckDLL"`(정식 ModuleType). 반환 False면 `[WARN]` 로그. **교사 PC 배포 시 한/글 보안 대화상자 블로킹 해소**(pyhwpx 없는 환경). form_fill:397 + hwp_to_hwpx:41 둘 다.

4. **러너 필수입력 검증** (#6·9·14·16·19·21·24·25·27·30·36·38·41·43·46 — 15건 일괄) — `engine/{types.py,loader.py,runner.py}`:
   - `PortSpec`에 `optional: bool=False` 필드 추가(loader가 yaml `optional:` 파싱). **선언된 입력은 기본 필수**.
   - 러너가 execute **전에** 필수 입력 존재를 검증 → 없거나 `None`이면 `노드 'X' (이름): 필수 입력 '포트'이(가) 연결되지 않았거나 이전 노드에서 값이 오지 않았습니다`로 건너뜀. **raw `KeyError: '파일'` → 한국어 메시지**. 15개 노드의 동일 패턴을 러너 한 곳에서 해소.
   - `text_template` 입력1/입력2는 `optional: true`(유연 조합 노드) — 검증으로 예외 처리. 검증: 미연결→명확 메시지, text_template 단일입력 실행, 정상 2노드 파이프라인 무영향 모두 확인.
   - (미채택: 출력값 `validate_value` 배선은 노이즈 경고 위험으로 보류.)

5. **table 페이로드 정규화** (#0·1·29) — `engine/table_utils.py`(신규) + column_mapping/save_xlsx/data_merge:
   - `to_records(value)`: 어떤 table 모양(records / xlsx_to_md 시트래퍼 `[{sheet,data}]` / 헤더행 2D리스트 / 단일dict / JSON문자열)이든 **records(list[dict])로 정규화**. 순수 파이썬(pandas 무관).
   - column_mapping·save_xlsx가 `to_records`로 입력 정규화 → **xlsx_to_md→column_mapping 시 sheet/rows/columns/data 4컬럼 오염·매핑 전탈락 해소**. (검증: 시트래퍼+학번→학생번호 매핑 정상, records passthrough 무영향.)
   - data_merge: 입력 타입 `list`→`table`(생태계 표 출력과 연결 가능), 항목이 시트래퍼면 `item["data"]`를 표로 병합(문서화된 "시트별 통합" 실현). merge 공통컬럼 없을 때 조용한 concat 대체에 `[WARN]` 로그(#29).

### ⏳ 수정 예정 (순서)
- E: 4개 변환노드 npx 전체경로+encoding=utf-8(#15·17·31·39·42).

**회귀 안전망**: `scripts/benchmark_form_fill.py --llm local` 495/495. (llm_extract·hwpx_fill는 벤치 경로(grid `fill_hwpx_cells`)와 무관 — 노드 단위 오프라인 검증으로 확인.)
