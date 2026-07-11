# -*- coding: utf-8 -*-
"""모델×능력 매트릭스 — 여러 GGUF를 하네스에 통과시켜 비교.

각 모델마다: llama-server 재기동 → 벤치495(명단 파싱) → 그리드 채움 E2E
(가정통신문 4빈칸, COM 불필요) → tok/s. 결과를 표로 출력하고 원장에 축적.

사용:
  python scripts/model_matrix.py --models gemma:D:/models/teacherflow/gemma-4-E4B-it-Q3_K_S.gguf \\
                                          qwen:D:/models/qwen/Qwen2.5-3B-Instruct-Q4_K_M.gguf
  (name:path[:reasoning] 형식. reasoning 생략 시 off. phi처럼 비사고면 name:path:none)

모델별로 하네스는 코드 수정 0 — provider=local로 :8400에 로드된 GGUF를 잰다.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LLAMA_BIN = r"D:\models\llama_cpp\bin\llama-server.exe"
PORT = 8400


def _kill_server():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                   capture_output=True)
    time.sleep(1)


def _start_server(gguf: str, reasoning: str = "off") -> subprocess.Popen:
    _kill_server()
    cmd = [LLAMA_BIN, "-m", gguf, "--host", "127.0.0.1", "--port", str(PORT),
           "-c", "8192", "-np", "1", "-ngl", "99", "--jinja"]
    # llama.cpp --reasoning는 on|off|auto만. 비사고 모델은 auto(템플릿 자동감지).
    if reasoning in ("off", "on", "auto"):
        cmd += ["--reasoning", reasoning]
    logf = ROOT / "scripts" / "_matrix_llama.log"
    fh = open(logf, "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT)
    import requests
    for _ in range(90):
        rc = p.poll()
        if rc is not None:
            fh.flush()
            tail = logf.read_text("utf-8", errors="replace")[-400:]
            raise RuntimeError(f"llama-server 프로세스 종료(rc={rc}): {tail}")
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).ok:
                return p
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("llama-server 기동 타임아웃(90s)")


def _tok_per_s(gguf_name: str) -> float:
    """웜업 후 짧은 생성으로 tok/s 측정."""
    import requests
    payload = {"model": "local", "messages": [{"role": "user", "content": "1부터 30까지 세어줘."}],
               "max_tokens": 128, "temperature": 0}
    requests.post(f"http://127.0.0.1:{PORT}/v1/chat/completions", json=payload, timeout=120)  # warmup
    t0 = time.monotonic()
    r = requests.post(f"http://127.0.0.1:{PORT}/v1/chat/completions", json=payload, timeout=120).json()
    dt = time.monotonic() - t0
    n = (r.get("usage") or {}).get("completion_tokens", 0)
    return round(n / dt, 1) if dt else 0.0


def _run_bench(gguf_name: str) -> dict:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark_form_fill.py"),
                        "--llm", "local", "--gguf", gguf_name],
                       capture_output=True, text=True, encoding="utf-8",
                       env={**__import__("os").environ, "PYTHONUTF8": "1"})
    res = json.loads((ROOT / "scripts" / "benchmark_last_result.json").read_text("utf-8"))
    return res.get("level2", {"accuracy": 0, "correct": 0, "total": 0})


def _run_grid(gguf_name: str) -> dict:
    """그리드 채움 E2E (COM 불필요) — 가정통신문 4빈칸 정확도."""
    import tempfile
    from engine.llm_manager import LLMManager
    from engine import deps
    import engine.form_assist as fa
    from engine.hwpml.hwpx_grid import parse_hwpx
    from nodes.md_to_hwpx.main import execute as md2hwpx

    wd = Path(tempfile.mkdtemp(prefix="mtx_grid_"))
    md = ("# 가정통신문\n\n| 항목 | 내용 |\n| --- | --- |\n"
          "| 행사명 | ○○○ |\n| 일시 | ○○○ |\n| 장소 | ○○○ |\n| 대상 | ○○○ |\n")
    r = md2hwpx({"텍스트": md}, {"output_name": "안내"},
                {"temp_dir": str(wd), "progress": lambda x: None, "log": lambda m: None})
    deps.llm_manager = LLMManager(models_dir=ROOT / "models",
                                  config={"local_context_size": 8192, "local_model": gguf_name})
    res = fa.run_form_assist(files=[{"path": r["파일"], "name": "안내.hwpx"}],
                             instruction="10월 15일 오후 2시 대강당에서 전교생 대상 가을 독서 축제",
                             output_file_idx=0, llm_provider="local",
                             output_dir=str(wd), log_cb=lambda m: None)
    doc = parse_hwpx(res["file"]) if res.get("file") else None
    vals = {c.text for g in (doc.tables if doc else []) for c in g.cells.values()}
    checks = [any("가을 독서" in v for v in vals),
              any("10월 15일" in v or "오후 2시" in v for v in vals),
              any("대강당" in v for v in vals),
              any("전교생" in v for v in vals)]
    return {"grid_ok": sum(checks), "grid_total": 4, "verified": res.get("verified", 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True,
                    help="name:path[:reasoning] (reasoning=off|on|none, 기본 off)")
    args = ap.parse_args()

    rows = []
    for spec in args.models:
        parts = spec.split(":")
        # 경로에 콜론(C:) 포함 대비 — 첫 토큰=name, 마지막이 reasoning 키워드면 분리
        name = parts[0]
        rest = spec[len(name) + 1:]
        reasoning = "off"
        if rest.endswith((":off", ":on", ":auto")):
            reasoning = rest.rsplit(":", 1)[1]
            path = rest.rsplit(":", 1)[0]
        else:
            path = rest
        r_flag = reasoning
        gguf_name = Path(path).name
        print(f"\n{'='*60}\n[{name}] {gguf_name} (reasoning={reasoning})\n{'='*60}")
        try:
            _start_server(path, r_flag)
            tps = _tok_per_s(gguf_name)
            print(f"  tok/s: {tps}")
            bench = _run_bench(gguf_name)
            print(f"  벤치495: {bench.get('correct')}/{bench.get('total')} ({bench.get('accuracy')}%)")
            grid = _run_grid(gguf_name)
            print(f"  그리드: {grid['grid_ok']}/4")
            rows.append({"name": name, "gguf": gguf_name, "tok_s": tps,
                         "bench": f"{bench.get('correct')}/{bench.get('total')}",
                         "bench_pct": bench.get("accuracy"),
                         "grid": f"{grid['grid_ok']}/4"})
        except Exception as e:
            print(f"  실패: {e}")
            rows.append({"name": name, "gguf": gguf_name, "error": str(e)[:60]})

    _kill_server()

    # 매트릭스 표
    print(f"\n{'='*60}\n모델 × 능력 매트릭스\n{'='*60}")
    print(f"{'모델':<12}{'벤치495':<12}{'그리드':<8}{'tok/s':<8}")
    for r in rows:
        if r.get("error"):
            print(f"{r['name']:<12}ERROR: {r['error']}")
        else:
            bench_cell = f"{r['bench']}({r['bench_pct']}%)"
            print(f"{r['name']:<12}{bench_cell:<12}{r['grid']:<8}{r['tok_s']:<8}")
    out = ROOT / "scripts" / "model_matrix_result.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
