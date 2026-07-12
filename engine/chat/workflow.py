"""워크플로우 자동 생성 + 양식(form) assist 채팅."""

from __future__ import annotations

import json
import logging
import re
import math
from pathlib import Path
from typing import Any

_log = logging.getLogger("chat_handler")

from engine.chat.intake import (
    FORM_EXTENSIONS, detect_form_intent, extract_file_paths, extract_user_instruction,
)


def build_system_prompt(registry, presets_dir: Path) -> str:
    """노드 카탈로그 + 예시 워크플로우로 시스템 프롬프트 구성."""
    # 노드 카탈로그
    lines = ["사용 가능한 노드 목록:\n"]
    for nd in registry.list_nodes():
        inputs_str = ", ".join(f"{p.name}({p.type})" for p in nd.inputs) or "(없음)"
        outputs_str = ", ".join(f"{p.name}({p.type})" for p in nd.outputs) or "(없음)"
        use_when_str = "; ".join(nd.use_when) if nd.use_when else ""
        lines.append(
            f"- id: {nd.id}\n"
            f"  name: {nd.name}\n"
            f"  category: {nd.category}\n"
            f"  inputs: [{inputs_str}]\n"
            f"  outputs: [{outputs_str}]\n"
            f"  use_when: {use_when_str}"
        )

    catalog = "\n".join(lines)

    # 프리셋 예시 (few-shot)
    examples = []
    if presets_dir.exists():
        for f in sorted(presets_dir.glob("*.json"))[:3]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                compact = {
                    "name": data.get("name", ""),
                    "nodes": [
                        {"id": n["id"], "type": n["type"], "params": n.get("params", {})}
                        for n in data.get("nodes", [])
                    ],
                    "edges": data.get("edges", []),
                }
                examples.append(json.dumps(compact, ensure_ascii=False))
            except Exception:
                pass

    examples_section = ""
    if examples:
        examples_section = "\n\n예시 워크플로우:\n" + "\n---\n".join(examples)

    return (
        "당신은 TeacherFlow 워크플로우 생성 AI입니다.\n"
        "사용자의 요청을 분석하여 노드와 엣지로 구성된 워크플로우 JSON을 생성합니다.\n\n"
        f"{catalog}\n"
        f"{examples_section}\n\n"
        "규칙:\n"
        "1. 반드시 위 노드 목록에 있는 id만 사용하라.\n"
        "2. 출력 JSON 형식:\n"
        '   ```json\n'
        '   {\n'
        '     "name": "워크플로우 이름",\n'
        '     "description": "설명",\n'
        '     "nodes": [\n'
        '       {"id": "고유id", "type": "노드id", "params": {}, "position": {"x": 100, "y": 200}}\n'
        '     ],\n'
        '     "edges": [\n'
        '       {"from": "소스노드id", "from_port": "출력포트명", "to": "대상노드id", "to_port": "입력포트명"}\n'
        '     ]\n'
        '   }\n'
        '   ```\n'
        "3. 노드 id는 type + 번호로 (예: file_input_1, llm_generate_1)\n"
        "4. position은 트리 레이아웃으로 배치하라 (입력 x=100, 처리 x=350, 분기 x=600, 출력 x=900).\n"
        "5. params에는 적절한 한국어 프롬프트/설정을 넣어라.\n"
        "6. 워크플로우 JSON 앞뒤에 간단한 설명을 추가해도 된다.\n"
        "7. 워크플로우가 필요 없는 일반 질문에는 텍스트로만 답하라.\n"
        "8. file_input 노드의 params에 반드시 auto_convert: true를 포함하라. 이러면 텍스트 출력 포트가 자동으로 생긴다.\n"
        "9. file_input의 텍스트 출력을 LLM 노드에 직접 연결할 수 있다 (변환 노드 불필요).\n"
        "10. 사용자가 첨부한 파일 경로가 있으면 file_input의 path에 넣어라.\n"
        "11. edge의 from_port/to_port는 반드시 해당 노드의 입출력 포트 이름과 정확히 일치해야 한다.\n"
        "12. PDF 출력이 필요하면 md_to_pdf 노드를 사용하라.\n"
    )



def parse_workflow_response(text: str) -> dict | None:
    """LLM 응답에서 WorkflowJSON 추출. Returns dict or None."""
    # ```json ... ``` 블록 추출
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
    else:
        # JSON 객체 직접 탐색
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start == -1 or brace_end == -1:
            return None
        candidate = text[brace_start:brace_end + 1]

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    # 필수 필드 검증
    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        return None

    if len(data["nodes"]) == 0:
        return None

    # position 자동 할당 (없는 노드에만)
    _auto_layout(data)

    return data


def validate_workflow(data: dict, registry) -> list[str]:
    """생성된 워크플로우를 저장 전에 코드로 검증 — '계산·검증은 코드' 철학.

    환각 노드type·유령 엣지·오타 포트를 저장 전에 걸러 실행시점 무음실패를 막는다.
    반환: 오류 메시지 리스트(빈 리스트=통과).
    """
    errors: list[str] = []
    valid_types = set(registry.list_ids())
    node_ids: set = set()
    for n in data.get("nodes", []):
        nid, ntype = n.get("id"), n.get("type")
        if not nid:
            errors.append("id가 없는 노드가 있습니다.")
            continue
        node_ids.add(nid)
        if ntype not in valid_types:
            errors.append(f"알 수 없는 노드 종류: '{ntype}' (노드 {nid})")

    for e in data.get("edges", []):
        src = e.get("from") or e.get("source", "")
        tgt = e.get("to") or e.get("target", "")
        if src not in node_ids:
            errors.append(f"연결의 출발 노드 '{src}'가 존재하지 않습니다.")
        if tgt not in node_ids:
            errors.append(f"연결의 도착 노드 '{tgt}'가 존재하지 않습니다.")
        # 포트명 검증 (노드type이 유효할 때만)
        for nid, port_key, kind in ((src, "from_port", "out"), (tgt, "to_port", "in")):
            node = next((n for n in data["nodes"] if n.get("id") == nid), None)
            if not node:
                continue
            nd = registry.get(node.get("type"))
            if nd is None:
                continue
            pname = e.get(port_key) or e.get(
                "sourceHandle" if kind == "out" else "targetHandle", "")
            ports = nd.outputs if kind == "out" else nd.inputs
            if pname and pname not in {p.name for p in ports}:
                errors.append(f"노드 '{nid}'에 '{pname}' 포트가 없습니다.")
    return errors



def _auto_layout(data: dict) -> None:
    """position이 없는 노드에 트리 레이아웃 위치를 할당."""
    nodes = data["nodes"]
    edges = data["edges"]

    # 이미 모든 노드에 position이 있으면 스킵
    missing = [n for n in nodes if "position" not in n or not n["position"]]
    if not missing:
        return

    # 인접 리스트 구축
    children: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}
    node_ids = {n["id"] for n in nodes}

    for nid in node_ids:
        children[nid] = []
        parents[nid] = []

    for e in edges:
        # LLM/runner 엣지는 from/to 형식 — source/target만 읽던 버그로
        # 인접리스트가 항상 비어 전 노드가 한 열에 겹쳐 쌓이던 문제 수정.
        src = e.get("from") or e.get("source", "")
        tgt = e.get("to") or e.get("target", "")
        if src in node_ids and tgt in node_ids:
            children[src].append(tgt)
            parents[tgt].append(src)

    # 루트 노드 (부모 없음)
    roots = [nid for nid in node_ids if not parents[nid]]
    if not roots:
        roots = [nodes[0]["id"]]

    # BFS 레벨 할당
    levels: dict[str, int] = {}
    queue = list(roots)
    for r in roots:
        levels[r] = 0

    visited = set(roots)
    while queue:
        nid = queue.pop(0)
        for child in children.get(nid, []):
            if child not in visited:
                levels[child] = levels[nid] + 1
                visited.add(child)
                queue.append(child)

    # 할당 안 된 노드 처리
    for n in nodes:
        if n["id"] not in levels:
            levels[n["id"]] = 0

    # 레벨별 노드 그룹화
    level_groups: dict[int, list[str]] = {}
    for nid, lvl in levels.items():
        level_groups.setdefault(lvl, []).append(nid)

    # position 할당
    x_spacing = 250
    y_spacing = 150
    node_map = {n["id"]: n for n in nodes}

    for lvl, nids in level_groups.items():
        x = 100 + lvl * x_spacing
        total = len(nids)
        for i, nid in enumerate(nids):
            y = 100 + i * y_spacing - (total - 1) * y_spacing / 2 + 200
            if nid in node_map:
                node_map[nid]["position"] = {"x": x, "y": round(y)}



def handle_chat(
    message: str,
    history: list[dict],
    registry,
    llm_manager,
    store,
    model: str | None = None,
) -> dict[str, Any]:
    """채팅 메시지 처리. Returns {reply, workflow_id, workflow_json}.

    양식 파일 + 수정/채우기 의도 감지 시 FormAssist 파이프라인으로 자동 라우팅.
    """
    # ── 0. FormAssist 자동 라우팅 ──
    file_paths = extract_file_paths(message)
    if detect_form_intent(message, file_paths):
        _log.info("FormAssist 라우팅 시작")
        return _handle_form_assist_chat(message, file_paths, model)

    presets_dir = Path(store._presets_dir) if hasattr(store, "_presets_dir") else Path("data/presets")

    # 모델 파싱 (provider/model 형식)
    if model and "/" in model:
        provider, model_name = model.split("/", 1)
    else:
        provider, model_name = "openai", "gpt-4.1"

    # 1. 시스템 프롬프트 구성
    system_prompt = build_system_prompt(registry, presets_dir)

    # 2. 메시지 조합
    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        if "role" in h and "content" in h:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # 3. LLM 호출
    try:
        reply = llm_manager.generate_chat(
            messages,
            max_tokens=4096,
            temperature=0.3,
            provider=provider,
            model=model_name,
        )
    except Exception as e:
        # 실패 시 다른 provider로 fallback
        try:
            prompt = f"시스템:\n{system_prompt}\n\n사용자:\n{message}"
            reply = llm_manager.generate(prompt, max_tokens=4096, temperature=0.3)
        except Exception as e2:
            return {
                "reply": f"LLM 호출 실패: {e2}",
                "workflow_id": None,
                "workflow_json": None,
            }

    # 4. 워크플로우 파싱 시도
    workflow = parse_workflow_response(reply)

    # 5. 워크플로우가 있으면 검증 후 저장
    if workflow:
        problems = validate_workflow(workflow, registry)
        if problems:
            # 환각 노드·유령 엣지 저장 방지 — 사유를 사용자에게 구체적으로 안내.
            detail = "\n".join(f"- {p}" for p in problems[:5])
            return {
                "reply": (reply + "\n\n⚠️ 생성된 워크플로우에 문제가 있어 저장하지 "
                          f"않았습니다:\n{detail}\n\n다시 시도하거나 더 구체적으로 "
                          "요청해 주세요."),
                "workflow_id": None,
                "workflow_json": None,
            }
        meta = store.save_workflow(workflow)
        return {
            "reply": reply,
            "workflow_id": meta.id,
            "workflow_json": workflow,
        }

    # 6. 텍스트만
    return {
        "reply": reply,
        "workflow_id": None,
        "workflow_json": None,
    }



def _handle_form_assist_chat(
    message: str,
    file_paths: list[str],
    model: str | None = None,
) -> dict[str, Any]:
    """채팅에서 FormAssist 파이프라인 직접 호출. 양식 파일을 셀 단위로 처리."""
    from engine.form_assist import run_form_assist

    instruction = extract_user_instruction(message)
    files = [{"path": p, "name": Path(p).name} for p in file_paths]

    # 양식 파일 인덱스: 양식 확장자 파일 중 마지막
    output_idx = -1
    for i, f in enumerate(files):
        if Path(f["path"]).suffix.lower() in FORM_EXTENSIONS:
            output_idx = i

    # LLM 모델 설정
    llm_provider = "auto"
    llm_model = model or ""

    logs: list[str] = []

    try:
        # HWP 양식일 때 InitScan 스캔 (COM 스레드 필요 → 동기 호출)
        hwp_elements = None
        if output_idx >= 0:
            tp = files[output_idx]["path"]
            ext = Path(tp).suffix.lower()
            if ext in (".hwp", ".hwpx"):
                try:
                    from engine.form_assist import scan_hwp_structure
                    hwp_elements = scan_hwp_structure(tp, lambda m: logs.append(m))
                except Exception as e:
                    _log.warning(f"HWP 스캔 실패 (채팅): {e}")

        # 출력 디렉토리
        try:
            from engine import deps
            out_dir = deps.settings_mgr.get("general", "output_dir", "")
        except Exception:
            out_dir = ""

        result = run_form_assist(
            files=files,
            instruction=instruction,
            output_file_idx=output_idx,
            llm_provider=llm_provider,
            llm_model=llm_model,
            log_cb=lambda m: logs.append(m),
            output_dir=out_dir,
            hwp_elements=hwp_elements,
        )

        # HWP COM 채우기 (fill_data가 있으면)
        output_file = result.get("file")
        fill_data = result.get("fill_data")
        template_path = result.get("template_path")
        save_dir = result.get("save_dir", out_dir)

        if fill_data and template_path and hwp_elements:
            try:
                from engine.form_assist import fill_hwp_by_cells
                output_file = fill_hwp_by_cells(
                    template_path, fill_data, hwp_elements,
                    lambda m: logs.append(m), output_dir=save_dir,
                )
                result["file"] = output_file
            except Exception as e:
                _log.warning(f"HWP 채우기 실패 (채팅): {e}")

        # 응답 구성
        file_names = [f["name"] for f in files]
        form_name = files[output_idx]["name"] if output_idx >= 0 else "양식"

        reply_parts = [f"**{form_name}** 양식을 분석하여 채웠습니다."]
        if output_file:
            reply_parts.append(f"\n완성 파일: `{Path(output_file).name}`")
        if logs:
            summary_logs = [l for l in logs if "빈칸" in l or "완료" in l or "완성" in l or "항목" in l]
            if summary_logs:
                reply_parts.append("\n" + "\n".join(f"- {l}" for l in summary_logs[-5:]))

        return {
            "reply": "\n".join(reply_parts),
            "workflow_id": None,
            "workflow_json": None,
            "form_assist": True,
            "file": output_file or result.get("file"),
            "logs": logs,
        }

    except Exception as e:
        _log.error(f"FormAssist 채팅 처리 실패: {e}", exc_info=True)
        return {
            "reply": f"양식 처리 중 오류가 발생했습니다: {e}",
            "workflow_id": None,
            "workflow_json": None,
            "form_assist": True,
            "file": None,
            "logs": logs,
        }
