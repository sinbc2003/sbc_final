"""PyInstaller frozen 전용 엔트리포인트.

engine/server.py의 __main__ 블록(dev: reload=True)과 달리
앱 객체를 직접 전달하고 reload를 끈다 — frozen에서 uvicorn reloader는
sys.executable(=EXE 자신)을 재스폰해 무한 루프에 빠진다(§28 정찰).

빌드: pyinstaller packaging/engine.spec
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> None:
    multiprocessing.freeze_support()

    # 교사 PC 콘솔/파이프는 cp949 — 로그의 em-dash 한 글자가
    # UnicodeEncodeError로 노드 실패를 만든다(실측). 전 출력 UTF-8 고정.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 외부 리소스 루트(nodes/의 부모)를 sys.path에 추가 —
    # file_input의 importlib.import_module("nodes.X.main") namespace 폴백 안전망.
    from engine.paths import ROOT, DATA_DIR
    root_s = str(ROOT)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 부모(Tauri) 감시 — 정상 종료는 RunEvent::Exit이 kill하지만, 크래시나
    # 강제 종료(taskkill)는 그 경로를 안 타서 엔진+llama-server가 고아로
    # 남는다(실측). 부모가 사라지면 자식 정리 후 스스로 내려간다.
    parent_pid = os.environ.get("TEACHERFLOW_PARENT_PID")
    if parent_pid:
        import threading
        import time

        def _watch_parent(pid: int) -> None:
            import psutil
            while True:
                time.sleep(5)
                if not psutil.pid_exists(pid):
                    try:
                        from engine import deps
                        deps.shutdown()
                    except Exception:
                        pass
                    os._exit(0)

        try:
            threading.Thread(
                target=_watch_parent, args=(int(parent_pid),), daemon=True
            ).start()
        except ValueError:
            pass

    from engine.server import app
    import uvicorn

    port = int(os.environ.get("ENGINE_PORT", "8406"))
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
