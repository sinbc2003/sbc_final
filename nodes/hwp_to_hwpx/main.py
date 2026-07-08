"""
HWP → HWPX 변환 노드.

한/글 COM API (HwpObject)를 사용하여 바이너리 HWP를 HWPX로 변환.
Windows + 한/글 설치 필요.

hwp2pdf_v2.0 프로젝트의 Interop.HwpObjectLib.dll 참고.
"""

import os
import platform
from pathlib import Path


def execute(inputs: dict, params: dict, context: dict) -> dict:
    file_path = inputs["파일"]

    if not Path(file_path).exists():
        raise FileNotFoundError(f"파일 없음: {file_path}")

    if platform.system() != "Windows":
        raise RuntimeError("HWP→HWPX 변환은 Windows + 한/글 설치 환경에서만 가능합니다.")

    output_name = params.get("output_name", "").strip()
    if not output_name:
        output_name = Path(file_path).stem

    output_path = os.path.join(context["temp_dir"], f"{output_name}.hwpx")

    context["progress"](0.1)
    context["log"]("한/글 COM API로 HWP→HWPX 변환 중...")

    try:
        import win32com.client
    except ImportError:
        raise RuntimeError("pywin32가 필요합니다: pip install pywin32")

    hwp = None
    try:
        hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
        # ModuleType은 반드시 "FilePathCheckDLL" (예제 DLL 이름이 아님).
        # 등록 실패 시 Open/SaveAs에서 파일접근 승인 대화상자가 떠 무인 실행이 멈춤.
        if not hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule"):
            context["log"](
                "[WARN] 보안모듈(FilePathCheckerModule) 등록 실패 — "
                "한/글 파일접근 승인 대화상자가 뜰 수 있습니다. "
                "pyhwpx 설치로 레지스트리 등록이 필요합니다."
            )

        context["progress"](0.3)

        # 열기
        abs_path = os.path.abspath(file_path)
        if not hwp.Open(abs_path, "HWP", "forceopen:true"):
            raise RuntimeError(f"HWP 파일 열기 실패: {file_path}")

        context["progress"](0.6)

        # HWPX로 저장
        abs_output = os.path.abspath(output_path)
        if not hwp.SaveAs(abs_output, "HWPX"):
            raise RuntimeError("HWPX 저장 실패")

        context["progress"](0.9)

        if not Path(output_path).exists():
            raise RuntimeError("HWPX 파일이 생성되지 않았습니다.")

        size_kb = Path(output_path).stat().st_size / 1024
        context["log"](f"변환 완료: {output_name}.hwpx ({size_kb:.0f}KB)")

    finally:
        if hwp:
            try:
                hwp.Clear(1)
                hwp.Quit()
            except Exception:
                pass

    context["progress"](1.0)
    return {"파일": output_path}
