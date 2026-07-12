# TeacherFlow — 작업 현황

> 최종 갱신: 2026-04-13

## 프로젝트 구조

```
00_sbc_final/
│
├── engine/                           # Python 백엔드 엔진 (13개 모듈)
│   ├── __init__.py                   #   버전 정보
│   ├── types.py                      #   데이터 타입 시스템 (file/text/table/image/list/any)
│   ├── loader.py                     #   nodes/ 스캔 → node.yaml 파싱 → execute 함수 동적 로드
│   ├── runner.py                     #   DAG 위상정렬 → 순차 execute() 호출
│   ├── memory_manager.py             #   RAM 프로필 → 양자화/컨텍스트 자동 선택
│   ├── llm_manager.py                #   local(llama.cpp)/claude/openai/gemini 통합
│   ├── server.py                     #   FastAPI 서버 (포트 8406, API 34개+, ENV ENGINE_PORT로 변경 가능)
│   ├── storage.py                    #   데이터 저장소 (워크플로우 CRUD, 히스토리, 자동저장, 프리셋)
│   ├── settings.py                   #   설정 관리 (settings.json + .secrets.json)
│   ├── node_marketplace.py           #   노드 마켓플레이스 (다운로드/설치/검증)
│   ├── vector_store.py               #   ChromaDB 벡터 스토어 (RAG 임베딩/검색/공유)
│   ├── chat_handler.py               #   GPT-4.1 채팅 워크플로우 자동 생성
│   ├── live_controller.py            #   라이브 문서 제어 (HWP/Excel/PPT COM API)
│   ├── form_assist.py                #   공문 양식 통합 처리 (InitScan→LLM→셀ID기반주입)
│   └── skills/                       #   LLM 스킬 프롬프트 (앱별)
│       ├── excel.md                  #     Excel 제어 (10 액션)
│       ├── ppt.md                    #     PPT 제어 (6 액션)
│       └── hwp.md                    #     한/글 제어 (9 액션 + 공문 규칙)
│
├── nodes/                            # 노드 저장소 — ROM 폴더 구조 (31개)
│   ├── file_input/                   #   파일 입력 v2 (자동 텍스트 변환)
│   ├── text_input/                   #   텍스트 입력
│   ├── text_template/                #   텍스트 템플릿 ({{변수}} 치환)
│   ├── pdf_to_md/                    #   PDF→마크다운 (pymupdf)
│   ├── hwpx_to_md/                   #   HWPX→마크다운 (ZIP+XML)
│   ├── hwp_to_md/                    #   HWP→마크다운
│   ├── docx_to_md/                   #   DOCX→마크다운
│   ├── xlsx_to_md/                   #   엑셀→마크다운
│   ├── pptx_to_md/                   #   PPT→마크다운
│   ├── url_to_md/                    #   URL→마크다운
│   ├── image_to_text/                #   이미지→텍스트 (OCR)
│   ├── form_extract/                 #   양식 빈칸 추출 (XLSX/HWPX/HWP)
│   ├── table_extract/                #   표 추출
│   ├── text_split/                   #   텍스트 분할
│   ├── data_merge/                   #   데이터 병합
│   ├── column_mapping/               #   컬럼명 매핑
│   ├── image_extract/                #   이미지 추출
│   ├── hwp_to_hwpx/                  #   HWP→HWPX 변환 (COM API)
│   ├── llm_generate/                 #   LLM 생성 (자동 청킹)
│   ├── llm_summarize/                #   LLM 요약
│   ├── llm_translate/                #   LLM 번역
│   ├── llm_classify/                 #   LLM 분류
│   ├── llm_extract/                  #   LLM 정보 추출
│   ├── rag_ingest/                   #   RAG 임베딩 저장
│   ├── rag_query/                    #   RAG 검색 + LLM
│   ├── md_to_hwpx/                   #   마크다운→HWPX (pypandoc-hwpx)
│   ├── form_fill/                    #   양식 값 주입 (서식 보존)
│   ├── md_to_docx/                   #   마크다운→DOCX
│   ├── md_to_pdf/                    #   마크다운→PDF (reportlab)
│   ├── save_xlsx/                    #   엑셀 저장
│   └── hwpx_fill/                    #   HWPX 양식 채우기
│
├── src/                              # React 프론트엔드 (14개)
│   ├── main.tsx                      #   진입점
│   ├── App.tsx                       #   루트 (노드 정의 로드 + fallback 12개)
│   ├── index.css                     #   Tailwind + React Flow 커스텀 스타일
│   ├── types.ts                      #   TS 타입 (PortSpec, NodeDefinition, FlowNodeData 등)
│   ├── constants.ts                  #   디자인 토큰 (카테고리/포트 색상, Orange3 스타일)
│   ├── store.ts                      #   Zustand 상태관리 (노드/엣지/실행/저장/자동저장)
│   ├── components/
│   │   ├── Layout.tsx                #     메인 레이아웃 (Toolbar + 3패널 or 채팅)
│   │   ├── Toolbar.tsx               #     상단 바 (실행/저장/Ctrl+S/이름/모드토글)
│   │   ├── NodePalette.tsx           #     좌측 도구 상자 (카테고리/검색/드래그)
│   │   ├── FlowCanvas.tsx            #     React Flow 캔버스 (미니맵/컨트롤/연결검증)
│   │   ├── PropertiesPanel.tsx       #     우측 속성 패널 (파라미터 폼)
│   │   ├── ChatMode.tsx              #     채팅 모드 UI
│   │   ├── StatusBar.tsx             #     하단 상태 바 (엔진 상태 실시간 표시)
│   │   ├── SettingsModal.tsx         #     설정 모달 (API 키/LLM/RAG/업데이트/저장경로)
│   │   ├── ErrorBoundary.tsx         #     React Error Boundary
│   │   ├── WorkflowManagerPage.tsx   #     워크플로우 관리 전체 페이지
│   │   ├── MiniFlowChart.tsx         #     SVG 미니 노드 연결 시각화
│   │   ├── ChatWorkflowPreview.tsx   #     채팅 워크플로우 프리뷰
│   │   ├── ContextMenu.tsx           #     우클릭 컨텍스트 메뉴
│   │   ├── HomeScreen.tsx            #     홈 화면 (프리셋 카드)
│   │   ├── TaskRunner.tsx            #     간소화 실행 UI
│   │   ├── FormAssist.tsx            #     공문 양식 채우기 UI (다중파일+지시+양식선택)
│   │   ├── WorkflowManager.tsx       #     (레거시 모달, 미사용)
│   │   └── nodes/
│   │       ├── CustomNode.tsx        #       커스텀 노드 (카테고리 바/타입 배지/포트 호버)
│   │       └── CustomEdge.tsx        #       커스텀 엣지 (타입 기반 색상/애니메이션)
│   ├── store/                        #   Zustand 스토어 모듈
│   │   ├── helpers.ts                #     nextId, definitionToFlowData
│   │   └── index.ts                  #     re-export hub
│   ├── defaultNodes.ts               #   fallback 노드 정의 27개
│   ├── iconMap.ts                    #   공유 아이콘 맵 22개
│   └── hooks/                        #   (확장용)
│
├── src-tauri/                        # Tauri v2 설정
│   ├── Cargo.toml                    #   Rust 의존성 (tauri 2, tauri-plugin-shell 2)
│   ├── tauri.conf.json               #   앱 설정 (1400x900, 프론트 프록시)
│   ├── capabilities/default.json     #   권한 (core, shell)
│   └── src/ (lib.rs, main.rs)        #   Rust 진입점
│
├── data/                             # 사용자 데이터 (런타임 생성)
│   ├── workflows/                    #   저장된 워크플로우
│   ├── history/                      #   실행 히스토리 (최대 100개)
│   ├── autosave/                     #   자동저장 (최근 5개)
│   ├── presets/                      #   프리셋 (분기형 워크플로우 5개)
│   ├── uploads/                      #   업로드된 파일
│   ├── settings.json                 #   앱 설정
│   └── .secrets.json                 #   API 키 (gitignore)
│
├── vendor/                           # 내장 외부 라이브러리
│   └── pdf2hwpx/                    #   pdf2hwpx (365KB, core+extractor)
├── models/                           # LLM 모델 (base/*.gguf, loras/)
├── develop.md                        # 설계 문서 (전체 스펙 + 로드맵)
├── work.md                           # 이 파일 — 작업 현황
├── sample_workflow.json              # 샘플: PDF→LLM→HWPX
├── run_pipeline.py                   # CLI 파이프라인 러너
├── package.json                      # npm 의존성
├── vite.config.ts                    # Vite 설정 (/api → 8406 프록시)
├── tailwind.config.js                # Tailwind (Orange3 라이트 테마)
├── tsconfig.json                     # TypeScript 설정
├── postcss.config.js                 # PostCSS
└── index.html                        # SPA 진입점
```

---

## 개발 진행 상태

### Phase 1 — 엔진 + 노드 표준 ✅ 완료

| 항목 | 상태 | 파일 |
|------|------|------|
| 타입 시스템 (6종 + 호환성 검사) | ✅ | engine/types.py |
| 노드 로더 (YAML 파싱 + execute 동적 임포트) | ✅ | engine/loader.py |
| 파이프라인 러너 (DAG 위상정렬 + 순차 실행) | ✅ | engine/runner.py |
| 메모리 관리자 (RAM→양자화 자동 선택) | ✅ | engine/memory_manager.py |
| LLM 관리자 (local/claude/openai/gemini) | ✅ | engine/llm_manager.py |
| 노드 3개 (pdf_to_md, llm_generate, md_to_hwpx) | ✅ | nodes/*/ |
| CLI 러너 (--list-nodes, --info, workflow.json) | ✅ | run_pipeline.py |
| E2E 파이프라인 동작 확인 | ✅ | PDF→MD→HWPX 0.1초 |

### Phase 2 — 앱 UI 🔵 진행 중

| 항목 | 상태 | 파일/비고 |
|------|------|-----------|
| Vite + React + TS + Tailwind 셋업 | ✅ | package.json, vite.config.ts |
| React Flow 노드 에디터 (커스텀 노드/엣지) | ✅ | CustomNode.tsx, CustomEdge.tsx |
| 노드 팔레트 (카테고리/검색/드래그&드롭) | ✅ | NodePalette.tsx |
| 속성 패널 (파라미터 폼 6종 타입) | ✅ | PropertiesPanel.tsx |
| 툴바 (실행/저장/Ctrl+S/이름/모드토글) | ✅ | Toolbar.tsx |
| 채팅 모드 UI (예시 프롬프트, 버블) | ✅ | ChatMode.tsx |
| 모드 전환 (설계 ⇄ 채팅) | ✅ | store.ts, Toolbar.tsx |
| FastAPI 엔진 서버 (27개 엔드포인트) | ✅ | engine/server.py |
| 데이터 저장소 (CRUD/히스토리/자동저장/프리셋) | ✅ | engine/storage.py |
| 워크플로우 매니저 모달 (목록/검색/복제/삭제) | ✅ | WorkflowManager.tsx |
| 자동저장 (30초/localStorage+서버) | ✅ | store.ts |
| Tauri v2 설정 + 자동 업데이트 | ✅ | src-tauri/tauri.conf.json |
| Orange3 스타일 라이트 테마 | ✅ | tailwind.config.js, index.css |
| **설정 화면 (API 키, LLM, RAG, 업데이트)** | ✅ | SettingsModal.tsx, engine/settings.py |
| **드래그&드롭 위치 버그 수정** | ✅ | FlowCanvas.tsx (fitView 제거) |
| **엔진 연결 상태 실시간 표시** | ✅ | StatusBar.tsx (10초 폴링) |
| **React Error Boundary** | ✅ | ErrorBoundary.tsx |
| 빌드 성공 | ✅ | 436KB JS + 49KB CSS, 2.25초 |
| 문서 미리보기 (빈칸 하이라이트) | ⬜ | 미구현 |
| 도구 노드 확장 (현재 5/목표 30) | ⬜ | 실구현 5개, UI fallback 27개 |

### Phase 2.5 — 배포/RAG 인프라 ✅ 완료

| 항목 | 상태 | 파일/비고 |
|------|------|-----------|
| 설정 관리 시스템 (settings.json + .secrets.json) | ✅ | engine/settings.py |
| 노드 마켓플레이스 (다운로드/설치/검증/업데이트) | ✅ | engine/node_marketplace.py |
| ChromaDB 벡터 스토어 (임베딩/검색/공유) | ✅ | engine/vector_store.py |
| RAG 노드 2개 (rag_ingest, rag_query) | ✅ | nodes/rag_ingest/, nodes/rag_query/ |
| RAG API (ingest/query/export/import/stats) | ✅ | engine/server.py |
| Tauri updater 설정 | ✅ | src-tauri/tauri.conf.json |
| 설정 API (GET/PUT + API 키 마스킹) | ✅ | engine/server.py |
| 마켓플레이스 API (check-updates/install/uninstall) | ✅ | engine/server.py |

### Phase 2.8 — UX 개선 ✅ 완료

| 항목 | 상태 | 파일/비고 |
|------|------|-----------|
| 우클릭 컨텍스트 메뉴 (노드/엣지/캔버스) | ✅ | ContextMenu.tsx |
| 다중 선택 드래그 + Ctrl+A + Shift+클릭 | ✅ | FlowCanvas.tsx |
| 바탕화면 파일 드래그&드롭 → 자동 노드 생성 | ✅ | FlowCanvas.tsx, store.ts |
| 파일 업로드 UI (모든 file 입력 포트) | ✅ | PropertiesPanel.tsx |
| LLM 모델 드롭다운 (로컬+API 모델 목록) | ✅ | PropertiesPanel.tsx, /api/models |
| 출력 패널 (로그/출력 탭, 텍스트 복사, 파일 열기) | ✅ | ExecutionPanel.tsx |
| pypandoc-hwpx HWPX 변환 (한컴호환 + 버그 전처리) | ✅ | nodes/md_to_hwpx/main.py |
| 코드 모듈화 (defaultNodes, iconMap, constants) | ✅ | src/defaultNodes.ts, src/iconMap.ts |
| 실행 이중 방지 가드 | ✅ | store.ts |

### Phase 3 — 지능화 🔵 진행 중

| 항목 | 상태 | 파일/비고 |
|------|------|-----------|
| **GPT-4.1 채팅 워크플로우 자동 생성** | ✅ | engine/chat_handler.py, ChatMode.tsx |
| **워크플로우 관리 전체 페이지** | ✅ | WorkflowManagerPage.tsx (모달→풀페이지) |
| **미니 플로우차트 (SVG 노드+엣지+화살표)** | ✅ | MiniFlowChart.tsx |
| **3모드 전환 (설계/채팅/관리)** | ✅ | Layout.tsx, Toolbar.tsx |
| **분기형 프리셋 5개 (나뭇가지 워크플로우)** | ✅ | data/presets/ (6~11노드, 분기+합류) |
| **채팅 워크플로우 프리뷰 + 설계모드 열기** | ✅ | ChatWorkflowPreview.tsx |
| **LLM generate_chat 멀티턴 대화** | ✅ | engine/llm_manager.py |
| **출력 파일 바로 열기 + 폴더 열기** | ✅ | /api/files/open, ExecutionPanel.tsx |
| **출력 저장 위치 설정 (기본: 바탕화면)** | ✅ | settings.py, SettingsModal.tsx |
| **비개발자 친화적 로그 (색상+한글)** | ✅ | ExecutionPanel.tsx |
| **긴 문서 자동 청킹 (map-reduce)** | ✅ | llm_generate/main.py (8000자↑ 자동 분할) |
| **실행 이중 방지 + thumbnail_data** | ✅ | store.ts, storage.py |
| **채팅 모드 기본 화면 + 바로 실행** | ✅ | store.ts, ChatWorkflowPreview.tsx |
| **채팅 파일 드래그&드롭 + 첨부** | ✅ | ChatMode.tsx |
| **파일 입력 자동 변환 (auto_convert)** | ✅ | file_input v2 (파일+텍스트 듀얼 출력) |
| **md_to_pdf 노드** | ✅ | reportlab 기반, 한글 폰트 |
| **잘못된 provider fallback** | ✅ | llm_manager.py (auto fallback) |
| **절대 경로 의존성 제거** | ✅ | 통째로 이동 가능 |

### Phase 4 — 라이브 문서 제어 + 홈 화면 🔵 진행 중

| 항목 | 상태 | 파일/비고 |
|------|------|-----------|
| **홈 화면 (프리셋 기반 메인)** | ✅ | HomeScreen.tsx — 앱 열면 작업 선택 |
| **TaskRunner (간소화 실행 UI)** | ✅ | TaskRunner.tsx — 파일 넣고→실행→결과 |
| **4모드 전환 (홈/설계/채팅/관리)** | ✅ | types.ts, store.ts, Layout.tsx, Toolbar.tsx |
| **노드 에디터 = 설계(고급) 모드** | ✅ | Toolbar.tsx — 홈 모드에서 워크플로우 버튼 숨김 |
| **양식 빈칸 추출 노드 (form_extract)** | ✅ | XLSX/HWPX/HWP 빈칸 좌표+라벨 추출 |
| **양식 값 주입 노드 (form_fill)** | ✅ | JSON→원본 양식 주입, 서식/수식/매크로 보존 |
| **HWP→HWPX 변환 노드 (hwp_to_hwpx)** | ✅ | 한/글 COM API |
| **라이브 문서 제어 (live_controller)** | ✅ | HWP+Excel+PPT COM API, 29개 액션 |
| **앱 자동 감지 (프로세스 기반)** | ✅ | tasklist 폴링, 10초 간격 |
| **Excel/PPT 자동 COM 연결** | ✅ | 감지 시 자동 연결 |
| **HWP COM 연결 (pyhwpx)** | ✅ | pyhwpx 기반 연결 — Inline AI 역공학으로 해결 |
| **HWP 전용 컨트롤러 (hwp_controller)** | ✅ | BlockManager + DocumentScanner + HwpEditor |
| **HWP blockId 기반 정밀 편집** | ✅ | CVD 추출, 14개 편집 액션 |
| **HWP 전용 API (/api/hwp/*)** | ✅ | connect/info/cvd/tables/execute/actions |
| **라이브 API (detect/connect/read/execute)** | ✅ | 7개 엔드포인트 |
| **LLM 스킬 프롬프트 (excel/ppt/hwp)** | ✅ | engine/skills/ — 액션 목록+규칙+예시 |
| **스킬 API (/api/live/skill/{app})** | ✅ | 문서 내용 자동 주입 완성 프롬프트 반환 |
| **PPT 디자인 액션 (배경/폰트/도형)** | ✅ | set_slide_bg, format_text, add_shape, set_shape_fill |
| **StatusBar 라이브 앱 표시** | ✅ | 연결: 파랑, 실행 중: 회색 |
| **2단계 PPT 생성 (기획+실행 분리)** | ✅ | Claude 기획 → GPT-4.1 실행, 품질 검증 완료 |
| **PDF→HWPX 수식 노드 삭제** | ✅ | 별도 프로젝트로 분리 (vendor/pdf2hwpx 제거) |
| **FormAssist 모델 선택 UI** | ✅ | auto/OpenAI/Claude/Gemini 드롭다운 |
| **FormAssist HWP 텍스트 추출 (olefile)** | ✅ | COM 없이 PrvText 스트림 읽기 |
| **FormAssist HWP 텍스트 기반 처리** | ✅ | 빈칸 추출 불가 시 전체 텍스트→LLM→마크다운 반환 |
| **FormAssist HWP 3-phase (스캔→LLM→채우기)** | ✅ | InitScan 셀구조 스캔→셀ID 기반 LLM→set_pos+insert_text |
| **HWP CVD 스캔 버그 수정** | ✅ | move_pos(201) 추가, init_scan 파라미터 수정, 타임아웃 보호 |
| **채팅 스킬 block_id 자동 주입** | ✅ | /api/live/skill/hwp에 CVD 스캔 결과 자동 포함 |
| **HWP COM 자동 재연결** | ✅ | read_text/extract_cvd에서 연결 끊김 시 자동 재연결 |
| **FormAssist 출력양식 열기 API** | ✅ | /api/form-open-template — 선택 시 한/글에서 즉시 열기 |
| **live/detect 비동기화** | ✅ | asyncio.create_subprocess_exec (이벤트루프 블로킹 방지) |
| **설정에 live 모델 옵션 추가** | ✅ | plan_model, execute_model, temperature |
| 채팅+라이브 통합 (자연어→COM 실행) | ⬜ | 채팅에서 "엑셀에 넣어줘" → 라이브 제어 |
| 라이브 제어 모델 설정 UI (SettingsModal) | ⬜ | 기획/실행 모델 선택 화면 |
| **공문 양식 채우기 프리셋** | ✅ | preset_form_fill.json — e2e 검증 완료 |
| **form_fill 병합 셀 처리** | ✅ | MergedCell → 좌상단 셀에 자동 쓰기 |
| **통합 FormAssist 엔진** | ✅ | engine/form_assist.py — 다중 파일+자동 추출+LLM+주입 |
| **FormAssist API (/api/form-assist)** | ✅ | 다중 파일 업로드, 양식 자동 감지, LLM 채우기 |
| **FormAssist UI (FormAssist.tsx)** | ✅ | 다중 드래그&드롭, 지시사항, 출력양식 선택, 페이지 범위 |
| **설계 모드에서 프리셋 로드** | ✅ | 관리→프리셋→열기 → 캔버스에 노드 배치 (엣지 양포맷 지원) |
| **win32com gencache 버그 수정** | ✅ | startup시 gencache 초기화 → get_pos list_id=0 버그 해결 |
| **HWP COM 인스턴스 재활용** | ✅ | connect/cvd/read에서 기존 연결 재활용, stale 시 fresh 생성 |
| **HWP CVD E2E 검증** | ✅ | 238블록/221셀 스캔 → 셀 편집 → 텍스트 확인 → 원복 (2026-04-12) |
| **ENGINE_PORT 환경변수** | ✅ | 좀비 TCP 우회, 기본 8406 |
| **HWP read 엔드포인트 수정** | ✅ | LiveController 우회, HwpController 직접 사용 |
| **채팅 FormAssist 자동 라우팅** | ✅ | 양식 파일+의도 감지 → chat_handler에서 form_assist 자동 호출 |
| **Excel openpyxl 크래시 lxml 폴백** | ✅ | form_extract/form_fill에서 lxml 직접 XML 파싱 폴백 |
| **Excel/PPT/Word COM 유령 인스턴스 정리** | ✅ | GetActiveObject 시 Visible=False+문서0개 → Quit() 후 재연결 |
| **앱별 문서 목록 드롭다운** | ✅ | /api/live/documents/{app}, 프론트 범용 드롭다운 (HWP 전용→전체 앱) |
| **detect 죽은 연결 자동 정리** | ✅ | 프로세스 없으면 _connections 제거, RPC 오류 시 연결 해제 |
| **subprocess 기반 앱 실행** | ✅ | Dispatch 대신 subprocess→GetActiveObject (COM 참조 독립) |

---

## 실행 방법

```bash
# 엔진 서버
cd "C:/Users/sinbc/OneDrive/바탕 화면/00_sbc_final"
python -m engine.server              # → http://127.0.0.1:8406 (ENGINE_PORT 환경변수로 변경 가능)

# 프론트엔드 dev
npm run dev                           # → http://localhost:1420

# CLI 파이프라인
python run_pipeline.py --list-nodes
python run_pipeline.py sample_workflow.json --input n1:파일=문서.pdf

# Tauri 빌드 (아직 미테스트)
npm run tauri build
```

---

## API 엔드포인트 (engine/server.py → :8406)

| 경로 | 메서드 | 기능 |
|------|--------|------|
| /api/nodes | GET | 노드 정의 목록 |
| /api/system | GET | 시스템 정보 + 메모리 프로필 |
| /api/health | GET | 헬스 체크 + 통계 |
| /api/run | POST | 워크플로우 실행 + 히스토리 자동 기록 |
| /api/workflows | GET | 워크플로우 목록 (최신순) |
| /api/workflows | POST | 워크플로우 저장 (새로/업데이트) |
| /api/workflows/{id} | GET | 워크플로우 불러오기 (프리셋 포함) |
| /api/workflows/{id} | DELETE | 워크플로우 삭제 |
| /api/workflows/{id}/duplicate | POST | 복제 |
| /api/workflows/{id}/rename | PUT | 이름/설명 변경 |
| /api/workflows/{id}/tags | PUT | 태그 업데이트 |
| /api/workflows/{id}/preset | POST | 프리셋으로 저장 |
| /api/autosave | POST | 자동저장 |
| /api/autosave | GET | 최근 자동저장 불러오기 |
| /api/autosaves | GET | 자동저장 목록 |
| /api/history | GET | 실행 히스토리 (최신 30개) |
| /api/history/{id} | GET | 실행 기록 상세 |
| /api/presets | GET | 프리셋 목록 |
| /api/presets/{id} | GET | 프리셋 상세 (전체 JSON) |
| /api/stats | GET | 전체 통계 |
| /api/chat | POST | 채팅 (Phase 3 스텁) |
| /api/live/detect | GET | 실행 중인 앱 감지 (HWP/Excel/PPT) |
| /api/live/connect/{app} | POST | 앱 COM 연결 |
| /api/live/read/{app} | GET | 현재 문서 내용 읽기 |
| /api/live/execute/{app} | POST | 명령 실행 (action+params) |
| /api/live/actions | GET | 사용 가능한 액션 스키마 |
| /api/live/skill/{app} | GET | 스킬 프롬프트 (문서 내용 주입) |
| /api/form-open-template | POST | HWP 출력양식 한/글에서 열기 |
| /api/form-assist | POST | 공문 양식 통합 처리 (3-phase: 스캔→LLM→셀채우기) |
| /api/hwp/connect | POST | HWP pyhwpx COM 연결 (기존 연결 재활용) |
| /api/hwp/info | GET | 현재 문서 정보 (경로, 커서, 페이지 등) |
| /api/hwp/cvd | GET | 문서 CVD 추출 (blockId + 위치 매핑, 표 셀 감지) |
| /api/hwp/execute | POST | blockId 기반 편집 (replace_cell_content, replace_paragraph 등) |
| /api/hwp/tables | GET | 문서 내 표 구조 추출 |
| /api/hwp/actions | GET | 사용 가능 HWP 액션 스키마 |
| /api/hwp/documents | GET | 열린 HWP 문서 목록 |
| /api/hwp/switch/{idx} | POST | HWP 문서 전환 |
| /api/hwp/scan-debug | GET | CVD 스캔 디버그 (raw 결과 30개) |
| /api/live/documents/{app} | GET | 연결된 앱의 열린 문서 목록 |
| /api/live/documents/{app}/activate | POST | 특정 문서 활성화 (문서 전환) |

---

## 핵심 결정사항

- 노드 = `node.yaml + main.py`, 폴더 추가 = 노드 추가
- Python 통일 (kordoc만 CLI 호출, 추후 포팅)
- 엔진↔프론트 통신: FastAPI HTTP (Tauri에서는 sidecar)
- 프론트 fallback: 엔진 없어도 하드코딩 노드 12개로 UI 동작
- Orange3 스타일 라이트 테마 (흰 배경, 카테고리 색상 아이콘)
- 타입 안전: 연결 시 포트 타입 호환성 실시간 검증
- 데이터 저장: 파일 기반 JSON (data/ 하위), 자동저장 30초/5개, 히스토리 100개

---

## 미완성 항목

| 항목 | 상태 | 설명 |
|------|------|------|
| ~~한/글 COM 연결~~ | ✅ 해결됨 | pyhwpx + Inline AI 역공학으로 해결 (2026-04-11) |
| ~~채팅+라이브 연동~~ | ✅ 해결됨 | ChatMode에서 라이브 제어 + FormAssist 자동 라우팅 완료 |
| 라이브 모델 설정 UI | 설정값 추가 완료, UI 없음 | SettingsModal에 기획/실행 모델 선택 화면 |
| PPT 2단계 생성 UI | 검증 완료, 파이프라인 미통합 | TeacherFlow 내 UI/API 연결 필요 |
| TaskRunner e2e 테스트 | UI 완성, 미테스트 | 일반 프리셋용 (공문은 FormAssist로 분리) |

### 해결된 이슈 요약

| 이슈 | 해결일 | 핵심 |
|------|--------|------|
| HWP COM 블로킹 | 04-11 | pyhwpx ROT 탐색으로 해결, hwp_controller.py 신규 |
| gencache 버그 | 04-11 | 서버 startup 시 gen_py 캐시 초기화 |
| 좀비 TCP 포트 | 04-11 | ENGINE_PORT 환경변수로 우회 |
| Excel openpyxl 크래시 | 04-13 | lxml 직접 XML 파싱 폴백 (form_extract/form_fill) |
| COM 유령 인스턴스 | 04-13 | GetActiveObject 시 유령 감지→Quit→재연결 |
| Office 미활성 라이선스 | 04-13 | Word 자동 종료 확인, Excel은 subprocess 방식으로 우회 |

## TODO (다음 세션 우선순위)

1. **Office 라이선스 활성화** — Excel/Word가 "제품 활성화되지 않은 제품" 상태, COM 제어 제한적 (Word는 자동 종료됨)
2. **HWP 문서 스캔 HWPML 보강** — 현재 COM 커서 순회 방식은 셀 병합(rowSpan/colSpan), 표 크기(행×열), 셀 너비/높이, 글자 서식 등 구조 정보를 알 수 없음. HWPX(ZIP 내 content.xml) 파싱을 병행하는 하이브리드 방식으로 개선 필요. 양식 문서(생기부, 성적표 등) 병합 셀이 많아 현재 방식으로는 정확한 편집 불가
3. **채팅 모드 스트리밍 응답** — 현재 한번에 결과 출력 → 실시간 스트리밍으로 개선
4. **라이브 모델 설정 UI** — SettingsModal에 기획/실행 모델 선택
5. **Tauri 빌드 테스트** — cargo build + 인스톨러
6. **노드 확장** — 실구현 노드 추가 (현재 10+/31)
7. **마켓플레이스 서버** — nodes.teacherflow.com
