# 테스트

로컬 gemma 문서 제어 파이프라인의 회귀 안전망. 티어별로 전제가 다르며, 전제 미충족 시 자동 skip.

## 티어

| 티어 | 전제 | 커버 |
|------|------|------|
| **offline** | 없음 (COM·LLM 불필요) | placeholder 데이터손실 방어, fill 응답 파싱, envelope 스키마/파서(3앱), 셀 좌표 캘리브레이션, 본문 밑줄 추출, 그리드 채움 라운드트립 |
| **com** | 한/글 설치 | 그리드↔InitScan 정렬(병합 16표 1126셀), 라이브 기록+마커 이동, 본문 밑줄 라이브 |
| **e2e** | 엔진(:8407) + llama-server(:8400) | 채팅 스트림 3종(채움/편집/질문), form-assist, fill-live |

`bench_score.hwpx`(PII, .gitignore) 픽스처가 있으면 병합표 검증까지, 없으면 그 부분만 skip.

## 실행

```bash
python tests/run_tests.py            # offline (빠름, CI 적합)
python tests/run_tests.py com        # + 한/글 COM
python tests/run_tests.py all        # offline + com
python tests/run_tests.py e2e        # E2E (서버 사전 기동 필요)
```

E2E 사전 기동:
```bash
# llama-server (엔진이 자동 기동하나 수동도 가능)
D:\models\llama_cpp\bin\llama-server.exe -m <gguf> --host 127.0.0.1 --port 8400 -c 8192 -np 1 -ngl 99 --jinja --reasoning off
# 엔진
set ENGINE_PORT=8407 && python -m engine.server
```

## 메모

- COM 이슈(핸드오프 §20): 같은 프로세스 EnsureDispatch 2회째 실패 → 작업당 서브프로세스(`hwp_op.py`) + 전용 gen_py. 한/글 콜드스타트 실패 시 `hwp.exe`를 먼저 실행해 두면 확실.
- 경로는 `helpers.ROOT` 기준 상대 — 다른 장비/경로로 옮겨도 동작.
