# -*- coding: utf-8 -*-
"""v10 체인 무인 리포터+자동벤치 — 텔레그램 보고 (사용자 24h 부재 대응).

- 5분 폴링: chain.log·train 로그·마커 감시.
- ~2시간 간격 진행보고(단계·스텝·s/it·ETA·VRAM) 텔레그램 발송.
- E2B v10 GGUF 등장 → 자동 채움 벤치(베이스/v9/v10) + 공문 생성 A/B → 발송.
- 체인 DONE → E4B 동일 벤치 → 최종 종합보고 → 종료.
- FAIL.txt → 즉시 경보.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(r"E:/sbc_lab/tf_build/v10_chain")
sys.path.insert(0, str(BASE))
from send_tg import api  # noqa: E402

LOG = BASE / "reporter.log"
STATE_F = BASE / "reporter_state.json"
LLAMA_DIR = Path(r"E:/sbc_lab/llama_test/b10338")
LORAS = Path(r"D:/models/loras")
E2B_GGUF = Path(r"D:/models/teacherflow/e2b/gemma-4-E2B-it-Q4_K_M.gguf")
E4B_GGUF = Path(r"E:/sbc_lab/gguf_work/gemma-4-E4B-it-Q4_K_M.gguf")
VAL = Path(r"D:/lora_data/dataset_v10/val.jsonl")
PORT = 8409
STEP_RE = re.compile(r"(\d+)/(\d+) \[[^\]]*?([\d.]+)s/it\]")
PROGRESS_EVERY = 7200


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}\n")


def tg(text):
    """4096자 청킹, parse_mode 없는 플레인 텍스트."""
    try:
        for i in range(0, len(text), 3900):
            api("sendMessage", {"chat_id": "8518696668",
                                "text": text[i:i + 3900]})
        return True
    except Exception as e:
        log(f"TG 실패: {e}")
        return False


def state():
    if STATE_F.exists():
        return json.loads(STATE_F.read_text(encoding="utf-8"))
    return {}


def save_state(st):
    STATE_F.write_text(json.dumps(st), encoding="utf-8")


def vram_free():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free",
             "--format=csv,noheader,nounits"], text=True, timeout=30)
        return int(out.strip().splitlines()[0])
    except Exception:
        return -1


def train_status(tag):
    """(step, total, s/it) — 로그 없으면 (0,0,0)."""
    p = BASE / f"train_{tag}.log"
    if not p.exists():
        return 0, 0, 0.0
    try:
        data = p.read_bytes()[-6000:].decode("utf-8", "replace")
    except OSError:
        return 0, 0, 0.0
    m = STEP_RE.findall(data.replace("\r", "\n"))
    if not m:
        return 0, 0, 0.0
    s, t, sit = m[-1]
    return int(s), int(t), float(sit)


def progress_text():
    lines = ["📊 [v10 체인] 진행 상황"]
    for tag, name in [("e2b", "E2B bf16"), ("e4b", "E4B QLoRA")]:
        s, t, sit = train_status(tag)
        if t:
            eta_h = (t - s) * sit / 3600
            lines.append(f"- {name}: {s}/{t}스텝 ({100*s//t}%) "
                         f"{sit:.0f}s/it ETA {eta_h:.1f}h")
    for gg in ["gongmun_g4e2b_v10.gguf", "gongmun_g4e4b_v10.gguf"]:
        if (LORAS / gg).exists():
            lines.append(f"- ✅ {gg} 생성됨")
    try:
        tail = (BASE / "chain.log").read_text(encoding="utf-8").splitlines()[-3:]
        lines += ["- 최근: " + t.split("] ", 1)[-1] for t in tail]
    except Exception:
        pass
    lines.append(f"- VRAM 여유 {vram_free()}MiB")
    return "\n".join(lines)


# ── 벤치 ──

def load_val():
    fills, gens = [], []
    for line in open(VAL, encoding="utf-8"):
        r = json.loads(line)
        c = r["completion"].lstrip()
        if c.startswith("{") and '"id"' in c:
            fills.append(r)
        elif not c.startswith("{"):
            gens.append(r)
    return fills, gens[:3]


def chat(payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def fill_bench(fills, lora_pair):
    """lora_pair=[(id,scale),...] 엄정 채점 → (correct, total, parse_fail)."""
    correct = total = pf = 0
    for s in fills:
        gold = json.loads(s["completion"])
        key = list(gold.keys())[0]
        items = [it for it in gold[key] if isinstance(it, dict) and "id" in it]
        vkey = [k for k in items[0].keys() if k != "id"][0]
        gm = {it["id"]: norm(it[vkey]) for it in items}
        total += len(gm)
        ids = list(gm.keys())
        schema = {"type": "object", "properties": {key: {"type": "array",
            "maxItems": len(ids), "items": {"type": "object", "properties": {
                "id": {"type": "string", "enum": ids},
                vkey: {"type": "string"}}, "required": ["id", vkey]}}},
            "required": [key]}
        try:
            out = chat({"model": "m", "temperature": 0, "max_tokens": 3000,
                "messages": [{"role": "user", "content": s["prompt"]}],
                "chat_template_kwargs": {"enable_thinking": False},
                "lora": [{"id": i, "scale": sc} for i, sc in lora_pair],
                "response_format": {"type": "json_schema",
                    "json_schema": {"name": "fill", "schema": schema}}})
            pred = json.loads(out["choices"][0]["message"].get("content") or "")
            seen = {}
            for it in pred.get(key, []):
                if isinstance(it, dict) and it.get("id") not in seen:
                    seen[it["id"]] = norm(it.get(vkey, ""))
            correct += sum(1 for cid, gv in gm.items() if seen.get(cid) == gv)
        except Exception:
            pf += 1
    return correct, total, pf


def gen_check(text):
    """공문 자동 점검: placeholder·결문·항목수."""
    ph = bool(re.search(r"\{기관명\}|\{문서번호\}|\{관련일자\}", text))
    end_ok = text.rstrip().endswith("끝.")
    items = len(re.findall(r"^\s*\d+\.", text, re.M))
    return f"PH{'✓' if ph else '✗'} 결문{'✓' if end_ok else '✗'} 항목{items} {len(text)}자"


def gen_bench(gens, lora_pair, label):
    outs = []
    for i, s in enumerate(gens):
        try:
            out = chat({"model": "m", "temperature": 0, "max_tokens": 900,
                "messages": [{"role": "user", "content": s["prompt"]}],
                "chat_template_kwargs": {"enable_thinking": False},
                "lora": [{"id": j, "scale": sc} for j, sc in lora_pair]})
            c = out["choices"][0]["message"].get("content") or ""
            outs.append(f"--- {label} 샘플{i} [{gen_check(c)}]\n{c[:700]}")
        except Exception as e:
            outs.append(f"--- {label} 샘플{i} 오류: {e}")
    return outs


def wait_vram_soft(need, max_s):
    t0 = time.time()
    while time.time() - t0 < max_s:
        if vram_free() >= need:
            return True
        time.sleep(600)
    return False


def run_suite(model_path, adapters, tag):
    """adapters=[(파일명, 라벨)] — id 순서대로 프리로드. 결과 텍스트 반환."""
    for fn, _ in adapters:
        src = LORAS / fn
        if src.exists():
            (LLAMA_DIR / fn).write_bytes(src.read_bytes())
    lora_arg = ",".join(f"{fn}:0.0" for fn, _ in adapters)
    proc = subprocess.Popen(
        [str(LLAMA_DIR / "llama-server.exe"), "-m", str(model_path),
         "--lora-scaled", lora_arg, "--port", str(PORT), "-ngl", "99",
         "-c", "4096", "--parallel", "1", "--jinja",
         "--reasoning", "off", "--reasoning-budget", "0"],
        cwd=str(LLAMA_DIR), stdout=open(BASE / f"bench_{tag}_server.log", "w"),
        stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/health", timeout=3)
                break
            except Exception:
                if proc.poll() is not None:
                    return f"[{tag}] 벤치 서버 기동 실패"
                time.sleep(3)
        fills, gens = load_val()
        n_ad = len(adapters)
        report = [f"🧪 [{tag}] 채움 엄정 벤치 (8문서/90필드)"]
        base_pair = [(i, 0.0) for i in range(n_ad)]
        c, t, pf = fill_bench(fills, base_pair)
        report.append(f"- 베이스: {c}/{t} = {100*c//t}% (파싱실패 {pf}/8)")
        for idx, (_, label) in enumerate(adapters):
            pair = [(i, 1.0 if i == idx else 0.0) for i in range(n_ad)]
            c, t, pf = fill_bench(fills, pair)
            report.append(f"- {label}: {c}/{t} = {100*c//t}% (파싱실패 {pf}/8)")
        gen_out = []
        for idx, (_, label) in enumerate(adapters):
            pair = [(i, 1.0 if i == idx else 0.0) for i in range(n_ad)]
            gen_out += gen_bench(gens, pair, label)
        return "\n".join(report) + "\n\n📝 공문 생성 A/B:\n" + "\n\n".join(gen_out)
    finally:
        proc.kill()
        proc.wait()


def main():
    log("리포터 시작")
    st = state()
    st.setdefault("start", time.time())
    st.setdefault("last_progress", 0)
    save_state(st)
    while True:
        try:
            st = state()
            now = time.time()
            # 실패 경보
            if (BASE / "FAIL.txt").exists() and not st.get("fail_sent"):
                txt = (BASE / "FAIL.txt").read_text(encoding="utf-8")
                tail = (BASE / "chain.log").read_text(
                    encoding="utf-8").splitlines()[-6:]
                tg("🔴 [v10 체인] 실패!\n" + txt + "\n최근 로그:\n"
                   + "\n".join(tail))
                st["fail_sent"] = True
                save_state(st)
            # 정기 진행보고
            if now - st.get("last_progress", 0) >= PROGRESS_EVERY:
                tg(progress_text())
                st["last_progress"] = now
                save_state(st)
            # E2B 벤치 (v10 gguf 등장 시, E4B 학습과 병행 — VRAM 소프트 대기)
            if ((LORAS / "gongmun_g4e2b_v10.gguf").exists()
                    and not st.get("bench_e2b")):
                tg("🔬 [v10 체인] E2B v10 GGUF 생성 확인 — 자동 벤치 시작")
                if wait_vram_soft(4800, 3 * 3600):
                    r = run_suite(E2B_GGUF,
                                  [("gongmun_g4e2b_v9.gguf", "v9 어댑터"),
                                   ("gongmun_g4e2b_v10.gguf", "v10 어댑터")],
                                  "E2B")
                    tg(r)
                else:
                    tg("[E2B 벤치] VRAM 대기 3h 초과 — E4B 완료 후로 연기")
                st["bench_e2b"] = True
                save_state(st)
            # E4B 벤치 + 최종보고 (체인 DONE 시)
            if (BASE / "DONE.txt").exists() and not st.get("bench_e4b"):
                tg("🏁 [v10 체인] 학습 전체 완료 — E4B 벤치 시작")
                r = run_suite(E4B_GGUF,
                              [("gongmun_g4e4b_v9.gguf", "v9 어댑터"),
                               ("gongmun_g4e4b_v10.gguf", "v10 어댑터")],
                              "E4B")
                tg(r)
                tg("✅ [v10 체인] 무인 운영 완료. 판정 기준:\n"
                   "- 채움: v10 어댑터가 베이스(E2B 56%/E4B 69%)를 넘으면 승,"
                   " 못 넘으면 채움=베이스 유지(손해 없음)\n"
                   "- 공문: v10이 PH✓·결문✓·항목수 유지하면 v9 대체 후보\n"
                   "- 다음: 접속 후 배포 반영 여부 결정")
                st["bench_e4b"] = True
                save_state(st)
                log("전체 완료 — 종료")
                return
            # 타임아웃 백스톱
            if now - st["start"] > 40 * 3600:
                tg("⏰ [v10 체인] 리포터 40h 타임아웃 — 상태:\n"
                   + progress_text())
                return
        except Exception as e:
            log(f"루프 오류: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
