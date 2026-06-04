# TeacherFlow

교사들이 **코딩 없이** 자신의 업무를 자동화할 수 있는 데스크톱 앱.
Orange3 / ComfyUI처럼 노드를 드래그&드롭으로 연결해 워크플로우를 만들고,
문서 변환·데이터 처리·AI 작문, 그리고 HWP/HWPX 한글 문서 편집을 자동으로 처리한다.

- **무료 배포**: 전국 교사 대상
- **오프라인 동작**: 로컬 LLM으로 인터넷 없이 사용 가능 (선택)
- **한국 교육 특화**: HWP/HWPX, 공문 양식 등 네이티브 지원

## 구조

```
00_sbc_final/
├── engine/        Python 백엔드 (FastAPI) — 노드 실행 엔진 / LLM / RAG / HWP 제어
│   ├── server.py      API 서버 엔트리포인트 (port 8406)
│   ├── routes/        REST 라우터 (system, workflows, execution, chat, rag, hwp ...)
│   ├── runner.py      DAG 위상정렬 → 노드 순차 실행
│   └── ...
├── src/           React + Vite 프론트엔드 (노드 에디터 UI)
├── nodes/         노드 정의 (node.yaml + execute 함수)
├── src-tauri/     Tauri(Rust) 데스크톱 셸
├── scripts/       PPT 생성 등 유틸 스크립트
└── data/          런타임 데이터 (설정·샘플) — 개인 데이터/캐시는 .gitignore
```

## 요구 사항

- Python 3.11+
- Node.js 18+ (pnpm 권장)

## 설치

```bash
# 1) 백엔드 의존성
pip install -r engine/requirements.txt
pip install fastapi uvicorn          # 서버 구동에 필요

# 2) 프론트엔드 의존성
pnpm install        # 또는: npm install

# 3) API 키 설정 (선택 — Claude/OpenAI/Gemini 사용 시)
cp data/.secrets.json.example data/.secrets.json
#   그 후 data/.secrets.json 에 본인 키를 입력. 이 파일은 절대 커밋되지 않음.
```

## 실행

```bash
# 백엔드 엔진 (port 8406)
python -m engine.server

# 프론트엔드 (port 1420) — 별도 터미널, /api 는 8406으로 프록시됨
pnpm exec vite      # 또는: npx vite
```

브라우저에서 http://localhost:1420 접속.
API 단독 확인: http://127.0.0.1:8406/docs (FastAPI 자동 문서).

## 비고

- `models/` (로컬 LLM 가중치/HF 캐시), `node_modules/`, 빌드 산출물은 저장소에 포함되지 않는다 — 직접 설치/다운로드.
- API 키 등 비밀값은 `data/.secrets.json` (gitignore)에만 보관한다.

## 라이선스

MIT
