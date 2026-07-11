# -*- coding: utf-8 -*-
"""테스트 러너 — 티어별 실행.

  python tests/run_tests.py            # offline (기본, 빠름)
  python tests/run_tests.py com        # + COM (한/글 필요)
  python tests/run_tests.py all        # offline + com
  python tests/run_tests.py e2e        # E2E (엔진 :8407 + llama :8400 필요)

각 티어는 전제(픽스처/COM/서버) 미충족 시 자동 skip.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIERS = {"offline": "test_offline.py", "com": "test_com.py", "e2e": "test_e2e.py"}


def run(name):
    script = HERE / TIERS[name]
    if not script.exists():
        print(f"[{name}] 스크립트 없음 — skip")
        return 0
    print(f"\n{'='*50}\n[{name}] {script.name}\n{'='*50}")
    r = subprocess.run([sys.executable, str(script)], cwd=str(HERE),
                       env={**__import__("os").environ, "PYTHONUTF8": "1", "PYTHONPATH": str(HERE)})
    return r.returncode


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "offline"
    order = {"offline": ["offline"], "com": ["com"], "e2e": ["e2e"],
             "all": ["offline", "com"], "full": ["offline", "com", "e2e"]}.get(arg, [arg])
    rc = 0
    for t in order:
        rc |= run(t)
    print(f"\n{'='*50}\n전체 결과: {'PASS' if rc == 0 else 'FAIL'}\n{'='*50}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
