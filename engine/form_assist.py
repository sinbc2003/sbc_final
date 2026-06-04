"""
공문 양식 채우기 — 통합 엔드포인트.

1. 여러 파일 수신 → 모두 텍스트 추출
2. 출력 양식 파일 지정 → 빈칸 추출
3. LLM에게 전체 맥락 + 빈칸 + 교사 지시 전달
4. 양식에 값 주입 → 완성 파일 반환
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional


def run_form_assist(
    files: list[dict],           # [{"path": str, "name": str}, ...]
    instruction: str,            # 교사 지시사항
    output_file_idx: int = -1,   # 출력 양식 파일 인덱스 (-1이면 자동 감지)
    page_range: str = "",        # "2-3" 등 (빈칸이면 전체)
    llm_provider: str = "auto",
    llm_model: str = "",         # "provider/model" 형식 또는 모델명
    llm_config: dict = None,
    live_mode: bool = True,      # True면 한/글 COM으로 실시간 채우기
    progress_cb=None,
    log_cb=None,
    output_dir: str = "",        # 출력 파일 저장 경로 (빈값 = 바탕화면)
    hwp_elements: list[dict] = None,  # InitScan 스캔 결과 (셀 ID 기반 채우기용)
) -> dict:
    """통합 공문 양식 채우기."""

    def log(msg):
        if log_cb:
            log_cb(msg)

    def progress(val):
        if progress_cb:
            progress_cb(val)

    if not files:
        raise ValueError("파일이 없습니다.")

    temp_dir = tempfile.mkdtemp(prefix="tf_form_")

    # ── 1. 모든 파일 텍스트 추출 ──
    progress(0.1)
    log("파일 텍스트 추출 중...")

    extracted = []  # [{"name", "ext", "text", "path", "is_form"}]
    form_exts = {".xlsx", ".xls", ".hwpx", ".hwp"}

    for i, f in enumerate(files):
        fpath = f["path"]
        fname = f.get("name", Path(fpath).name)
        ext = Path(fpath).suffix.lower()

        text = _extract_text(fpath, ext, temp_dir, log)
        is_form = ext in form_exts

        extracted.append({
            "index": i,
            "name": fname,
            "ext": ext,
            "text": text,
            "path": fpath,
            "is_form": is_form,
        })
        log(f"  {fname} ({ext}) → {len(text)}자")

    # ── 2. 출력 양식 결정 ──
    progress(0.3)

    output_template = None
    if output_file_idx >= 0 and output_file_idx < len(extracted):
        output_template = extracted[output_file_idx]
    else:
        # 자동 감지: 양식 확장자 파일 중 마지막 것
        for e in reversed(extracted):
            if e["is_form"]:
                output_template = e
                break

    # ── 3. 빈칸 추출 (양식이 있을 때) ──
    blanks_json = ""
    if output_template:
        ext = output_template["ext"]
        if ext in (".xlsx", ".xls"):
            # Excel은 정확한 빈칸 추출 가능
            log(f"양식 빈칸 추출: {output_template['name']}")
            try:
                from nodes.form_extract.main import execute as extract_fn
                ctx = {"temp_dir": temp_dir, "progress": lambda x: None, "log": log}
                result = extract_fn(
                    inputs={"파일": output_template["path"]},
                    params={"include_filled": False},
                    context=ctx,
                )
                blanks_json = result.get("빈칸목록", "")
                blanks = json.loads(blanks_json) if blanks_json else []
                log(f"  빈칸 {len(blanks)}개 감지")
            except Exception as e:
                log(f"  빈칸 추출 실패: {e}")
                blanks_json = "[]"
        else:
            # HWP/HWPX — 전체 텍스트를 LLM에 맡김
            log(f"양식 텍스트 기반 처리: {output_template['name']}")
            blanks_json = ""  # 빈칸 목록 없이 텍스트로 처리

    # ── 4. LLM 프롬프트 구성 ──
    progress(0.5)
    log("AI에게 전달 중...")

    # 맥락 텍스트 (양식 제외한 모든 파일)
    context_parts = []
    for e in extracted:
        if e is not output_template and e["text"]:
            context_parts.append(f"### {e['name']}\n{e['text']}")

    context_text = "\n\n---\n\n".join(context_parts) if context_parts else "(참고 문서 없음)"

    prompt = f"""당신은 교사의 공문 양식을 채우는 비서입니다.

## 참고 문서
{context_text}

## 교사 지시사항
{instruction if instruction else "(없음)"}
"""

    if output_template and blanks_json:
        # Excel 양식 — 정확한 셀 참조로 채우기
        prompt += f"""
## 출력 양식: {output_template['name']}
### 빈칸 목록
{blanks_json}

{f'### 작성 범위: {page_range}' if page_range else ''}

위 참고 문서와 교사 지시를 바탕으로 각 빈칸에 적절한 값을 채우세요.
반드시 JSON으로만 답하세요: {{"셀참조": "값", ...}}
설명 없이 JSON만 반환.
빈칸 목록의 cell_ref를 키로 사용하세요.
"""
    elif output_template and not blanks_json and hwp_elements:
        # HWP/HWPX 양식 — 셀 ID 기반 채우기 (InitScan 스캔 결과)
        cell_desc = _format_hwp_elements(hwp_elements)
        prompt += f"""
## 출력 양식: {output_template['name']}
### 문서 구조 (셀 ID + 현재 내용)
{cell_desc}

{f'### 작성 범위: {page_range}' if page_range else ''}

위 참고 문서와 교사 지시를 바탕으로, 빈칸이 있는 셀을 채우세요.

반드시 JSON으로만 답하세요: {{"셀ID": "채울내용", ...}}
- 빈칸(○○○, ___, 공란, 빈 값, 미입력)이거나 채워야 할 셀만 포함하세요.
- 이미 올바른 값이 들어있는 셀은 건드리지 마세요.
- 셀 ID는 위 구조의 id 값(숫자 문자열)을 그대로 사용하세요.
- 설명 없이 JSON만 반환하세요.
"""
    elif output_template and not blanks_json:
        # HWP/HWPX fallback — 텍스트 기반 (스캔 없이)
        prompt += f"""
## 출력 양식: {output_template['name']}
### 양식 텍스트
{output_template['text'][:5000]}

{f'### 작성 범위: {page_range}' if page_range else ''}

위 참고 문서와 교사 지시를 바탕으로, 이 양식의 빈칸을 채우세요.

반드시 JSON으로만 답하세요: {{"찾을텍스트": "바꿀텍스트", ...}}
- 양식에서 빈칸(○○○, ___, 공란, 예시 텍스트 등)을 찾아 실제 값으로 바꾸세요.
- 표의 빈 셀이나 미완성 내용도 포함하세요.
- 설명 없이 JSON만 반환하세요.
"""
    else:
        prompt += """
출력 양식이 지정되지 않았습니다.
참고 문서와 교사 지시를 바탕으로 요청된 내용을 작성하세요.
마크다운 형식으로 답하세요.
"""

    # ── 5. LLM 호출 ──
    progress(0.6)

    llm_response = _call_llm(prompt, llm_provider, llm_model, llm_config or {})
    log(f"AI 응답: {len(llm_response)}자")

    # ── 6. 양식 주입 또는 텍스트 반환 ──
    progress(0.8)

    result = {"text": llm_response, "file": None}

    # JSON 파싱 가능 여부 확인 (Excel blanks_json 케이스 또는 HWP JSON 케이스)
    has_json = output_template is not None
    if has_json:
        try:
            fill_data = _extract_json_from_response(llm_response)
            if fill_data is None:
                raise json.JSONDecodeError("JSON not found", llm_response, 0)
            log(f"양식 주입: {len(fill_data)}개 항목")

            ext = output_template["ext"]

            # 출력 디렉토리 결정 (설정 > 바탕화면 > temp)
            save_dir = output_dir
            if not save_dir:
                desktop = Path.home() / "Desktop"
                if desktop.exists():
                    save_dir = str(desktop)
                else:
                    # OneDrive 바탕화면
                    for p in Path.home().glob("OneDrive*/바탕*화면"):
                        if p.is_dir():
                            save_dir = str(p)
                            break
            if not save_dir:
                save_dir = temp_dir

            if ext in (".hwp", ".hwpx") and _is_windows():
                # HWP: COM 전용 스레드 필요 → 데이터만 반환 (서버에서 처리)
                result["fill_data"] = fill_data
                result["template_path"] = output_template["path"]
                result["save_dir"] = save_dir
                log(f"HWP 채우기 데이터 {len(fill_data)}개 항목 준비")
            else:
                # Excel 등: 파일 기반 채우기
                from nodes.form_fill.main import execute as fill_fn
                output_name = Path(output_template["name"]).stem + "_완성"
                fill_result = fill_fn(
                    inputs={
                        "양식파일": output_template["path"],
                        "채울내용": json.dumps(fill_data, ensure_ascii=False),
                    },
                    params={"output_name": output_name},
                    context={"temp_dir": save_dir, "progress": lambda x: None, "log": log},
                )
                result["file"] = fill_result.get("파일")

            if result["file"]:
                log(f"완성 파일: {result['file']}")
        except json.JSONDecodeError:
            log("JSON 파싱 실패 — AI가 JSON 형식으로 답하지 않았습니다")
            log(f"  응답 앞 200자: {llm_response[:200]}")
        except Exception as e:
            import traceback
            log(f"양식 주입 실패: {e}")
            log(f"  {traceback.format_exc().splitlines()[-1]}")

    progress(1.0)
    return result


# ── 라이브 HWP 채우기 ──

def _is_windows():
    import platform
    return platform.system() == "Windows"

def _connect_hwp(form_path: str, log) -> "tuple[any, bool]":
    """한/글 인스턴스에 연결. 이미 열린 문서면 활성화만. (COM 스레드 전용)"""
    import pythoncom
    pythoncom.CoInitialize()
    from pyhwpx import Hwp

    hwp = Hwp(visible=True)
    target_name = Path(form_path).name
    abs_path = os.path.abspath(form_path)

    need_open = True
    try:
        xdocs = hwp.XHwpDocuments
        for i in range(xdocs.Count):
            doc = xdocs.Item(i)
            full = getattr(doc, 'FullName', '') or ''
            if target_name.lower() in full.lower():
                doc.SetActive_XHwpDocument()
                need_open = False
                log(f"이미 열린 문서에서 작업: {target_name}")
                break
    except Exception:
        pass

    if need_open:
        import time
        log(f"한/글에서 파일 열기: {target_name}")
        hwp.Open(abs_path)
        time.sleep(0.5)

    return hwp, need_open


def scan_hwp_structure(form_path: str, log) -> list[dict]:
    """한/글 문서를 InitScan으로 스캔하여 셀/문단 구조 반환. (COM 스레드 전용)

    Inline AI 역공학 기반: init_scan → get_text → get_pos 패턴.
    list_id > 0 이면 표 셀 내부.
    """
    import pythoncom
    pythoncom.CoInitialize()

    hwp, _ = _connect_hwp(form_path, log)

    elements = []
    block_id = 0

    log("문서 구조 스캔 (InitScan)...")
    try:
        import time as _time
        hwp.init_scan(option=4, range=0x0077)

        prev_pos = None
        scan_start = _time.monotonic()
        for _ in range(10000):  # 무한루프 방지
            if _time.monotonic() - scan_start > 15:
                log("스캔 타임아웃 (15초)")
                break
            state, text = hwp.get_text()
            if state <= 1:
                break

            hwp.move_pos(201)
            pos = hwp.get_pos()

            clean = (text or "").replace("\r\n", "").replace("\r", "")
            if prev_pos == pos and not clean.strip():
                continue
            prev_pos = pos

            list_id, para_id, char_pos = pos
            elem_type = "td" if list_id > 0 else "text"

            elements.append({
                "id": str(block_id),
                "type": elem_type,
                "text": clean,
                "pos": [list_id, para_id, char_pos],
                "list_id": list_id,
            })
            block_id += 1

        hwp.release_scan()
        log(f"  스캔 완료: {len(elements)}개 요소 ({sum(1 for e in elements if e['type']=='td')}개 표 셀)")
    except Exception as e:
        log(f"  스캔 실패: {e}")

    return elements


def fill_hwp_by_cells(form_path: str, fill_data: dict, elements: list[dict],
                      log, output_dir: str = "") -> str:
    """셀 ID 기반 커서 이동 → SelectAll → insert_text 로 채우기. (COM 스레드 전용)

    Inline AI 역공학 기반: set_pos → is_cell → SelectAll → insert_text 패턴.
    """
    import pythoncom
    pythoncom.CoInitialize()
    import time

    try:
        hwp, _ = _connect_hwp(form_path, log)

        # 위치 맵: id → [list, para, pos]
        pos_map = {str(e["id"]): e for e in elements}

        filled = 0
        log(f"채우기 시작: {len(fill_data)}개 항목")

        for cell_id, new_text in fill_data.items():
            val = str(new_text).strip() if not isinstance(new_text, dict) else str(new_text.get("value", "")).strip()
            if not val:
                continue

            elem = pos_map.get(str(cell_id))
            if not elem:
                log(f"  #{cell_id}: 위치 없음, 건너뜀")
                continue

            list_id, para_id, char_pos = elem["pos"]

            try:
                hwp.set_pos(list_id, para_id, char_pos)

                if list_id > 0 and hwp.is_cell():
                    # 표 셀: 전체 선택 후 삽입
                    hwp.SelectAll()
                    hwp.insert_text(val)
                else:
                    # 본문 문단: 시작~끝 선택 후 삽입
                    hwp.MoveParaBegin()
                    hwp.MoveSelParaEnd()
                    hwp.insert_text(val)

                filled += 1
                log(f"  셀 #{cell_id} → {val[:40]}")
                time.sleep(0.03)
            except Exception as e:
                log(f"  셀 #{cell_id} 실패: {e}")

        log(f"한/글 {filled}개 항목 채우기 완료")

        # 다른 이름으로 저장
        output_name = Path(form_path).stem + "_완성"
        save_dir = output_dir or ""
        if not save_dir:
            desktop = Path.home() / "Desktop"
            if desktop.exists():
                save_dir = str(desktop)
            else:
                for p in Path.home().glob("OneDrive*/바탕*화면"):
                    if p.is_dir():
                        save_dir = str(p)
                        break
        if not save_dir:
            save_dir = os.path.dirname(form_path)

        ext = Path(form_path).suffix.lower()
        output_path = os.path.join(save_dir, f"{output_name}{ext}")
        hwp.SaveAs(os.path.abspath(output_path))
        log(f"저장: {output_path}")

        return output_path

    except Exception as e:
        log(f"pyhwpx 채우기 실패: {e}")
        import traceback
        log(f"  {traceback.format_exc().splitlines()[-1]}")
        return ""


# ── HWP 요소 포매팅 ──

def _format_hwp_elements(elements: list[dict]) -> str:
    """스캔된 HWP 요소를 LLM 프롬프트용 텍스트로 변환."""
    lines = []
    for e in elements:
        eid = e["id"]
        etype = "표셀" if e["type"] == "td" else "본문"
        text = e.get("text", "").strip()
        label = f"(빈칸)" if not text else text[:200]
        lines.append(f'<cell id="{eid}" type="{etype}">{label}</cell>')
    return "\n".join(lines)


# ── JSON 추출 (LLM 응답에서) ──

def _extract_json_from_response(text: str) -> dict | None:
    """LLM 응답에서 JSON dict를 추출. 여러 방법으로 시도."""
    import re

    # 1. ```json ... ``` 블록
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 2. 전체가 JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 3. { ... } 블록 찾기 (가장 바깥 중괄호)
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ── 텍스트 추출 ──

def _extract_text(path: str, ext: str, temp_dir: str, log) -> str:
    """파일에서 텍스트 추출."""
    try:
        if ext == ".pdf":
            import pymupdf
            doc = pymupdf.open(path)
            return "\n\n".join(page.get_text() for page in doc)

        if ext in (".hwpx",):
            from nodes.hwpx_to_md.main import execute as hwpx_fn
            r = hwpx_fn({"파일": path}, {}, {"temp_dir": temp_dir, "progress": lambda x: None, "log": log})
            return r.get("텍스트", "")

        if ext in (".docx",):
            from nodes.docx_to_md.main import execute as docx_fn
            r = docx_fn({"파일": path}, {}, {"temp_dir": temp_dir, "progress": lambda x: None, "log": log})
            return r.get("텍스트", "")

        if ext in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(path, data_only=True)
                parts = []
                for ws in wb:
                    parts.append(f"=== 시트: {ws.title} ===")
                    for row in ws.iter_rows(max_row=min(ws.max_row or 0, 200), values_only=False):
                        cells = [str(c.value) for c in row if c.value is not None]
                        if cells:
                            parts.append(" | ".join(cells))
                wb.close()
                return "\n".join(parts)
            except (IndexError, Exception):
                # openpyxl 스타일 파싱 실패 → pandas fallback
                log(f"openpyxl 실패, pandas로 텍스트 추출")
                try:
                    import pandas as pd
                    dfs = pd.read_excel(path, sheet_name=None, header=None)
                    parts = []
                    for name, df in dfs.items():
                        parts.append(f"=== 시트: {name} ===")
                        for _, row in df.iterrows():
                            cells = [str(v) for v in row if pd.notna(v)]
                            if cells:
                                parts.append(" | ".join(cells))
                    return "\n".join(parts)
                except Exception as e2:
                    log(f"pandas 추출도 실패: {e2}")
                    return f"[엑셀 텍스트 추출 실패: {Path(path).name}]"

        if ext in (".txt", ".md", ".csv"):
            return Path(path).read_text(encoding="utf-8", errors="ignore")

        # ODT, PPT 등 — 간단한 텍스트 추출 시도
        if ext == ".odt":
            import zipfile
            from lxml import etree
            with zipfile.ZipFile(path) as zf:
                content = zf.read("content.xml")
                root = etree.fromstring(content)
                texts = root.itertext()
                return "\n".join(t.strip() for t in texts if t.strip())

        if ext in (".pptx",):
            from nodes.pptx_to_md.main import execute as pptx_fn
            r = pptx_fn({"파일": path}, {}, {"temp_dir": temp_dir, "progress": lambda x: None, "log": log})
            return r.get("텍스트", "")

        if ext == ".hwp":
            # HWP 바이너리 — olefile/pyhwp로 텍스트 추출 (COM 불필요)
            try:
                import olefile
                ole = olefile.OleFileIO(path)
                if ole.exists("PrvText"):
                    data = ole.openstream("PrvText").read()
                    return data.decode("utf-16-le", errors="ignore")
                # BodyText 스트림에서 추출 시도
                texts = []
                for stream in ole.listdir():
                    name = "/".join(stream)
                    if "BodyText" in name or "PrvText" in name:
                        raw = ole.openstream(stream).read()
                        text = raw.decode("utf-16-le", errors="ignore")
                        # 제어 문자 제거
                        text = "".join(c for c in text if c.isprintable() or c in "\n\r\t")
                        if text.strip():
                            texts.append(text.strip())
                ole.close()
                if texts:
                    return "\n\n".join(texts)
            except Exception as e2:
                log(f"  olefile 추출 실패: {e2}")
            # fallback: pyhwp
            try:
                from hwp5.hwp5txt import extract_text
                import io
                buf = io.StringIO()
                extract_text(path, buf)
                return buf.getvalue()
            except Exception:
                pass
            return f"[HWP 텍스트 추출 실패: {Path(path).name}]"

        return f"[지원하지 않는 형식: {ext}]"

    except Exception as e:
        log(f"  텍스트 추출 실패 ({Path(path).name}): {e}")
        return f"[추출 실패: {Path(path).name}]"


# ── LLM 호출 ──

def _call_llm(prompt: str, provider: str, model: str, config: dict) -> str:
    """llm_manager를 통한 멀티 프로바이더 LLM 호출."""
    from engine import deps

    mgr = deps.llm_manager
    if not mgr:
        raise RuntimeError("LLM Manager가 초기화되지 않았습니다.")

    # model 파라미터에서 provider/model 분리 (예: "openai/gpt-4.1")
    if model and "/" in model:
        provider, model_name = model.split("/", 1)
    elif model:
        model_name = model
    else:
        model_name = ""

    # provider가 auto이면 llm_manager에게 위임
    if provider == "auto":
        provider = mgr._pick_provider()

    # 프로바이더별 기본 모델
    if not model_name:
        defaults = {
            "openai": "gpt-4.1",
            "claude": "claude-sonnet-4-6",
            "gemini": "gemini-2.5-flash",
        }
        model_name = defaults.get(provider, "gpt-4.1")

    messages = [
        {"role": "system", "content": "공문 양식을 채우는 비서입니다. 지시에 정확히 따릅니다."},
        {"role": "user", "content": prompt},
    ]

    return mgr.generate_chat(
        messages,
        max_tokens=config.get("max_tokens", 4000),
        temperature=config.get("temperature", 0.2),
        provider=provider,
        model=model_name,
    )
