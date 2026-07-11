# -*- coding: utf-8 -*-
"""COM 단일 작업 헬퍼 (서브프로세스 전용) — open <path> | read <path>

같은 프로세스에서 EnsureDispatch 2회째가 깨지는 gencache 이슈 우회:
작업당 새 프로세스 + 전용 gen_py 캐시 (핸드오프 §20).
"""
import json
import sys
import tempfile
import time

import win32com
import win32com.gen_py

_g = tempfile.mkdtemp(prefix="genpy_op_")
win32com.__gen_path__ = _g
win32com.gen_py.__path__ = [_g]

import pythoncom  # noqa: E402
pythoncom.CoInitialize()
from pyhwpx import Hwp  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def main():
    cmd = sys.argv[1]
    hwp = Hwp(visible=True)

    if cmd == "open":
        hwp.Open(str(sys.argv[2]))
        time.sleep(0.8)
        print("OK")
    elif cmd == "read":
        if len(sys.argv) > 2:
            hwp.Open(str(sys.argv[2]))
            time.sleep(0.4)
        hwp.MoveDocBegin()
        hwp.init_scan(option=4, range=0x0077)
        texts = []
        for _ in range(400):
            state, text = hwp.get_text()
            if state <= 1:
                break
            if text and text.strip():
                texts.append(text.strip())
        hwp.release_scan()
        print(json.dumps(texts, ensure_ascii=False))


if __name__ == "__main__":
    main()
