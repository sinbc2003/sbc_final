# -*- coding: utf-8 -*-
"""v10 밤샘 학습 체인 — E2B bf16 → GGUF → E4B QLoRA → GGUF (자율 재시도).

- 스필 감지: 학습 로그의 s/it가 임계 초과면 킬 → 대기 → 재시도 (데스크톱 유휴 대기).
- VRAM 게이트: 시도 전 여유 확인 (worker llama-server 부활 방어).
- 체크포인트 재개: 재시도 시 checkpoint-* 있으면 --resume.
- 산출: D:/models/loras/gongmun_g4e2b_v10.gguf, gongmun_g4e4b_v10.gguf
- 로그: E:/sbc_lab/tf_build/v10_chain/chain.log (+ 단계별 train 로그)
- 마커: DONE.txt / FAIL.txt
"""
import msvcrt
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(r"E:/sbc_lab/tf_build/v10_chain")
BASE_DIR.mkdir(parents=True, exist_ok=True)

# ── 싱글턴 락: 어떤 경로(수동·타 세션·봇)로 띄워도 인스턴스 1개만 ──
_LOCK = open(BASE_DIR / "chain.lock", "a+")
try:
    msvcrt.locking(_LOCK.fileno(), msvcrt.LK_NBLCK, 1)
except OSError:
    sys.exit(0)  # 이미 실행 중 — 조용히 종료
CHAIN_LOG = BASE_DIR / "chain.log"
PY = r"D:/lora_train/venv/Scripts/python.exe"
TRAIN = str(Path(__file__).resolve().parent / "train_lora.py")
CONVERT = r"D:/lora_train/llama.cpp/convert_lora_to_gguf.py"
DATA = r"D:/lora_data/dataset_v10"

ENV = dict(os.environ)
ENV.update({"TMP": "D:/tmp", "TEMP": "D:/tmp", "HF_HOME": "D:/hf_home",
            "PYTHONUTF8": "1",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})

STEP_RE = re.compile(r"(\d+)/(\d+) \[[^\]]*?([\d.]+)s/it\]")


def log(msg: str) -> None:
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    with open(CHAIN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def vram_free_mib() -> int:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"], text=True, timeout=30)
        return int(out.strip().splitlines()[0])
    except Exception:
        return -1


def wait_vram(need_mib: int, poll_s: int = 600) -> None:
    while True:
        free = vram_free_mib()
        if free >= need_mib:
            log(f"VRAM 게이트 통과: 여유 {free}MiB >= {need_mib}MiB")
            return
        log(f"VRAM 부족(여유 {free}MiB < {need_mib}MiB) — {poll_s}초 대기")
        time.sleep(poll_s)


def latest_checkpoint(out_dir: Path) -> Path | None:
    cps = sorted(out_dir.glob("checkpoint-*"),
                 key=lambda p: int(p.name.split("-")[1]))
    return cps[-1] if cps else None


def tail_steps(log_path: Path) -> tuple[int, float]:
    """로그 마지막 부분에서 (현재 스텝, 최근 s/it) 추출."""
    try:
        data = log_path.read_bytes()[-6000:].decode("utf-8", "replace")
    except OSError:
        return 0, 0.0
    matches = STEP_RE.findall(data.replace("\r", "\n"))
    if not matches:
        return 0, 0.0
    step, _, sit = matches[-1]
    return int(step), float(sit)


def run_train(tag: str, model: str, out_dir: str, extra: list[str],
              slow_sit: float, need_vram: int, max_attempts: int,
              probe_after_step: int = 4, probe_timeout_s: int = 1800,
              maxlen_schedule: list | None = None) -> bool:
    """학습 1종을 스필-감지 재시도 루프로 완주시킨다.

    maxlen_schedule: [(시도상한, max_len)] — 반복 스필 시 단계적으로 낮춰
    완주를 보장(로짓 피크 = vocab 262K × seq 이므로 seq를 줄이면 GB 단위 절감).
    스필 킬은 항상 checkpoint(step 28) 이전이라 재개-혼합 위험 없음.
    """
    out_path = Path(out_dir)
    train_log = BASE_DIR / f"train_{tag}.log"
    for attempt in range(1, max_attempts + 1):
        wait_vram(need_vram)
        max_len = "2048"
        if maxlen_schedule:
            for thr, ml in maxlen_schedule:
                if attempt <= thr:
                    max_len = ml
                    break
        cmd = [PY, TRAIN, "--model", model, "--data", DATA, "--out", out_dir,
               "--max-len", max_len, "--batch", "1", "--grad-accum", "16",
               "--no-eval"] + extra
        cp = latest_checkpoint(out_path)
        if cp is not None:
            cmd += ["--resume", str(cp)]
            log(f"[{tag}] 시도 {attempt}: {cp.name}에서 재개 (max-len {max_len})")
        else:
            log(f"[{tag}] 시도 {attempt}: 처음부터 (max-len {max_len})")
        with open(train_log, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                    env=ENV)
        # ── 프로브: 초기 스텝 s/it로 스필 판정 ──
        t0 = time.time()
        verdict = None  # None=진행중 / True=건강 / False=스필
        while verdict is None:
            if proc.poll() is not None:
                break  # 조기 종료(완료 or 크래시)는 아래서 판정
            step, sit = tail_steps(train_log)
            if step >= probe_after_step and sit > 0:
                verdict = sit <= slow_sit
                log(f"[{tag}] 프로브: step {step}, {sit}s/it → "
                    f"{'건강' if verdict else '스필'}")
            elif time.time() - t0 > probe_timeout_s:
                verdict = False
                log(f"[{tag}] 프로브 타임아웃({probe_timeout_s}s, step {step}) → 스필 취급")
            else:
                time.sleep(60)
        if verdict is False:
            proc.kill()
            proc.wait()
            log(f"[{tag}] 스필 킬 — 1800초 후 재시도")
            time.sleep(1800)
            continue
        # ── 건강 판정 후 완주 대기 ──
        rc = proc.wait()
        txt = train_log.read_text(encoding="utf-8", errors="replace")
        if rc == 0 and "어댑터 저장" in txt:
            log(f"[{tag}] 학습 완료 (시도 {attempt})")
            return True
        log(f"[{tag}] 비정상 종료 rc={rc} — 마지막 500자:\n{txt[-500:]}")
        time.sleep(600)
    log(f"[{tag}] {max_attempts}회 시도 모두 실패")
    return False


def convert(tag: str, adapter_dir: str, base: str, outfile: str) -> bool:
    log(f"[{tag}] GGUF 변환 시작")
    r = subprocess.run([PY, CONVERT, f"{adapter_dir}/final", "--base", base,
                        "--outfile", outfile],
                       capture_output=True, text=True, env=ENV, timeout=3600)
    ok = r.returncode == 0 and Path(outfile).exists()
    log(f"[{tag}] 변환 {'완료: ' + outfile if ok else '실패: ' + (r.stderr or '')[-400:]}")
    return ok


def main() -> int:
    log("=== v10 밤샘 체인 시작 ===")
    # 1) E2B bf16 (레시피 순수 — v9와 동일 조건 A/B용). 건강 ~9s/it, 스필 20s/it+.
    ok = run_train("e2b", r"D:/models/hf/gemma-4-E2B-it",
                   r"D:/lora_train/out/gongmun_g4e2b_v10",
                   extra=["--no-4bit"], slow_sit=15.0, need_vram=15300,
                   max_attempts=12,
                   # 초반은 v9 레시피 순수(2048), 반복 스필 시 단계 하향:
                   # 1792 = 초과 7샘플(0.26%) 추가 손실, 1536 = 26샘플(0.95%)
                   maxlen_schedule=[(4, "2048"), (7, "1792"), (99, "1536")])
    if not ok:
        (BASE_DIR / "FAIL.txt").write_text("E2B 학습 실패", encoding="utf-8")
        return 1
    if not convert("e2b", r"D:/lora_train/out/gongmun_g4e2b_v10",
                   r"D:/models/hf/gemma-4-E2B-it",
                   r"D:/models/loras/gongmun_g4e2b_v10.gguf"):
        (BASE_DIR / "FAIL.txt").write_text("E2B 변환 실패", encoding="utf-8")
        return 1
    # 2) E4B QLoRA 4bit (v9 E4B와 동일 레시피). 건강 100~127s/it (§41).
    ok = run_train("e4b", r"D:/models/hf/gemma-4-E4B-it",
                   r"D:/lora_train/out/gongmun_g4e4b_v10",
                   extra=[], slow_sit=180.0, need_vram=10000,
                   max_attempts=6, probe_timeout_s=3600)
    if not ok:
        (BASE_DIR / "FAIL.txt").write_text("E4B 학습 실패(E2B는 완료)",
                                           encoding="utf-8")
        return 1
    if not convert("e4b", r"D:/lora_train/out/gongmun_g4e4b_v10",
                   r"D:/models/hf/gemma-4-E4B-it",
                   r"D:/models/loras/gongmun_g4e4b_v10.gguf"):
        (BASE_DIR / "FAIL.txt").write_text("E4B 변환 실패(어댑터는 저장됨)",
                                           encoding="utf-8")
        return 1
    (BASE_DIR / "DONE.txt").write_text(
        "E2B v10 + E4B v10 학습·변환 완료", encoding="utf-8")
    log("=== 체인 전체 완료 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
