# -*- mode: python ; coding: utf-8 -*-
"""TeacherFlow 엔진 PyInstaller spec — onedir 고정.

onefile 금지 이유(§28 정찰): nodes/는 EXE 밖 실파일 트리로 유지해야 하고
(플러그인·마켓플레이스 구조), onefile은 _MEIPASS 임시폴더 휘발로 경로 체계가
깨진다.

배포 레이아웃(Tauri 리소스):
  resources/
    engine/            ← 이 spec의 dist 출력(onedir) 통째
      engine.exe
      _internal/       (engine 패키지·서드파티·engine/skills 데이터)
    nodes/             ← 리포 nodes/ 복사 (실파일)
    presets/           ← data/presets/*.json 시드
    models/base/*.gguf, models/loras/*.gguf
    llama/llama-server.exe (+DLL)

빌드: cd <리포루트> && pyinstaller packaging/engine.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

REPO = Path(SPECPATH).parent  # packaging/의 부모 = 리포 루트

hiddenimports = (
    # engine 전체 강제 수집 — table_utils 등 "노드에서만 import"되는 모듈이
    # 정적 분석에 안 잡힌다(§28 블로커 ②)
    collect_submodules("engine")
    # uvicorn 동적 로딩 모듈
    + collect_submodules("uvicorn")
    # 노드 전용 서드파티(동적 로딩이라 사각지대) — nodes/*/main.py 전수 대조
    + [
        "pandas", "tabulate", "openpyxl", "lxml", "lxml.etree",
        "pymupdf", "fitz",
        "PIL", "PIL.Image",
        "docx", "pptx", "olefile", "bs4", "requests", "yaml",
        "reportlab", "pypandoc", "pytesseract",
        "hwpx", "hwpx.builder",
        "hwp5", "hwp5.hwp5txt", "hwp5.xmlmodel",
        # pywin32 — COM 라이브 제어
        "win32com", "win32com.client", "win32com.client.gencache",
        "pythoncom", "pywintypes", "win32timezone", "win32clipboard",
        "win32gui", "win32con", "win32process", "win32api",
        # 기타 런타임 지연 import
        "engine.paths",
        "multipart",  # fastapi 업로드(python-multipart)
        "psutil",     # 엔트리 부모 감시 워치독
    ]
    + collect_submodules("reportlab")
    + collect_submodules("hwpx")
    + collect_submodules("hwp5")
)

datas = (
    # 라이브 채팅 스킬 md — Path(__file__).parent/"skills" 상대 참조(§28)
    [(str(REPO / "engine" / "skills"), "engine/skills")]
    # pyhwpx: FilePathCheckerModule.dll + fonts.json (한/글 보안승인 억제)
    + collect_data_files("pyhwpx")
    # hwp5: xsl/locale 데이터 (구식 pkg_resources 패키지)
    + collect_data_files("hwp5")
    # pandas가 optional 의존성의 배포 메타데이터로 버전을 검사한다 —
    # 메타데이터 없으면 'Invalid version: unknown'으로 표 추출이 무너짐(실측).
    + copy_metadata("openpyxl")
    + copy_metadata("tabulate")
    + copy_metadata("lxml")
)

excludes = [
    # RAG/토치 스택 — dev 환경에서 빌드해도 1.2GB 유입 금지(§28 블로커 ⑥).
    # vector_store는 ImportError 폴백이 있어 서버는 정상 기동한다.
    "torch", "torchvision", "torchaudio",
    "sentence_transformers", "transformers", "tokenizers", "sentencepiece",
    "chromadb", "onnxruntime",
    "scipy", "sklearn", "pyarrow",
    "safetensors", "huggingface_hub", "datasets", "accelerate", "peft",
    # 대형 무관 패키지
    "matplotlib", "IPython", "jupyter", "notebook", "sympy",
    "tkinter", "pythonwin",
    "unsloth", "bitsandbytes", "xformers", "triton",
    # 학습·개발 전용
    "pytest",
]

a = Analysis(
    [str(REPO / "packaging" / "engine_entry.py")],
    pathex=[str(REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    # -X utf8: 인터프리터 UTF-8 모드 — cp949 교사 PC에서 파일/스트림 기본
    # 인코딩을 UTF-8로 고정(엔트리의 reconfigure와 이중 안전망).
    [("X utf8=1", None, "OPTION")],
    exclude_binaries=True,
    name="engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 사이드카는 창 없음 — Tauri가 CREATE_NO_WINDOW로 spawn.
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="engine",
)
