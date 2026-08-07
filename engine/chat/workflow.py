"""워크플로우 자동 생성 채팅.

양식(form) assist는 `routes/chat.py`의 async 판이 유일한 진입점이다 —
여기에도 같은 로직이 있었으나 두 판이 갈라져(스캔 범위·자동 열기) 제거했다.
"""

from __future__ import annotations

import json
import logging
import re
import math
from pathlib import Path
from typing import Any

_log = logging.getLogger("chat_handler")

# 채팅 history 상한 — 노드 카탈로그(시스템 프롬프트)가 이미 크므로
# 무제한 누적은 소형모델 컨텍스트를 넘긴다. 최근 N개 메시지만 보낸다.
_HISTORY_TURNS = 12

# 하위 호환 재수출 — `from engine.chat_handler import detect_form_intent` 등이
# 이 모듈을 거쳐 접근한다(패키지 facade가 intake에서 직접 가져오지만, 기존
# import 경로를 깨지 않기 위해 유지).
from engine.chat.intake import (  # noqa: F401
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
        "    from_port는 출발 노드의 **출력** 포트, to_port는 도착 노드의 **입력** 포트다.\n"
        "12. PDF 출력이 필요하면 md_to_pdf 노드를 사용하라.\n"
        "13. **노드를 자기 자신에 연결하지 마라.** 연결은 서로 다른 두 노드 사이에만 만든다.\n"
        "    노드가 하나뿐이면 edges는 빈 배열 []로 두어라.\n"
        "14. 파일을 다루는 워크플로우는 반드시 file_input 노드에서 시작하고, 그 '파일' 출력을\n"
        "    변환 노드(xlsx_to_md·pdf_to_md 등)의 '파일' 입력에 연결하라.\n"
        "15. 연결하는 두 포트의 타입은 같아야 한다(text↔text, file↔file). "
        "'텍스트'(text) 출력을 '파일'(file) 입력에 연결하면 안 된다.\n"
    )



def build_workflow_envelope_schema(registry) -> dict:
    """로컬 모델용 워크플로우 생성 스키마 — {응답, 워크플로우|null}.

    live_chat.build_live_envelope_schema와 같은 계약. llama-server가 GBNF로
    강제 디코딩하므로 **노드 type 환각이 원천 차단**된다(enum=레지스트리 실제 id).
    일반 질문은 워크플로우=null로 답하게 해 규칙7(텍스트 답변)을 보존.
    params는 노드마다 구조가 달라 자유 객체로 두고 few-shot·카탈로그가 담당.
    """
    node_ids = list(registry.list_ids())
    # 포트명도 enum으로 묶는다 — 실측(gemma E2B)에서 노드 type은 맞히지만
    # 포트명을 영어로 지어내(text/input_text) 검증에서 전부 걸렸다.
    # 어휘가 12·15개뿐이라 enum 비용이 거의 없다.
    out_ports = sorted({p.name for nd in registry.list_nodes() for p in nd.outputs})
    in_ports = sorted({p.name for nd in registry.list_nodes() for p in nd.inputs})
    workflow_obj = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": node_ids},
                        "params": {"type": "object"},
                        "position": {
                            "type": "object",
                            "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                            "required": ["x", "y"],
                        },
                    },
                    "required": ["id", "type", "params"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "from_port": ({"type": "string", "enum": out_ports}
                                      if out_ports else {"type": "string"}),
                        "to": {"type": "string"},
                        "to_port": ({"type": "string", "enum": in_ports}
                                    if in_ports else {"type": "string"}),
                    },
                    "required": ["from", "from_port", "to", "to_port"],
                },
            },
        },
        "required": ["name", "nodes", "edges"],
    }
    return {
        "type": "object",
        "properties": {
            "응답": {"type": "string"},
            # anyOf(객체|null) — llama.cpp 문법 변환이 확실히 지원하는 형태.
            "워크플로우": {"anyOf": [workflow_obj, {"type": "null"}]},
        },
        "required": ["응답", "워크플로우"],
    }


def build_workflow_envelope_note() -> str:
    """envelope 형식 지시 — 시스템 프롬프트의 ```json 블록 지시를 명시적으로 대체."""
    return (
        "\n\n## 응답 형식 (반드시 준수 — 위 규칙 2·6의 형식 지시보다 우선한다)\n"
        "코드펜스나 설명 없이, 아래 형태의 JSON 객체 하나로만 답하라:\n"
        '{"응답": "사용자에게 보여줄 설명", "워크플로우": {"name": "...", "description": "...", '
        '"nodes": [{"id": "...", "type": "...", "params": {}, "position": {"x": 100, "y": 200}}], '
        '"edges": [{"from": "...", "from_port": "...", "to": "...", "to_port": "..."}]}}\n'
        '- 워크플로우가 필요 없는 일반 질문이면 "워크플로우"를 null로 두고 "응답"에만 답하라.\n'
        '- 예(질문): {"응답": "PDF 요약은 pdf_to_md → llm_summarize 순서입니다.", "워크플로우": null}\n'
    )


def parse_workflow_envelope(text: str) -> tuple[str, dict | None] | None:
    """{응답, 워크플로우} envelope 파싱. 실패 시 None (호출측이 legacy 파서 폴백)."""
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    data = _loads_lenient(s)
    if data is None or "응답" not in data or "워크플로우" not in data:
        return None

    reply = str(data.get("응답") or "")
    wf = data.get("워크플로우")
    if not isinstance(wf, dict):
        return reply, None
    if not isinstance(wf.get("nodes"), list) or not isinstance(wf.get("edges"), list):
        return reply, None
    if not wf["nodes"]:
        return reply, None

    _auto_layout(wf)
    return reply, wf


_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _close_unterminated(s: str) -> str | None:
    """max_tokens 절단으로 끊긴 JSON을 **완성된 원소까지만** 살려 닫는다.

    마지막으로 정상 종료된 괄호 위치까지 자르고, 그 시점의 열린 괄호를 닫는다.
    반쯤 쓰인 원소(문자열 중간 절단 포함)는 버린다. 살린 결과가 워크플로우로서
    부족하면(예: edges 키 자체가 잘려나감) 상위 파서가 None을 내고 재시도로 간다.
    """
    stack: list[str] = []
    in_str = False
    esc = False
    last_close = -1              # 문자열 밖에서 괄호가 닫힌 마지막 위치
    stack_at_last_close: list[str] = []
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                return None      # 구조가 깨짐 — 손대지 않는다
            stack.pop()
            last_close = i
            stack_at_last_close = list(stack)
    if not stack:
        return None              # 이미 닫혀 있음 (다른 원인의 실패)
    if last_close < 0:
        return None
    return s[:last_close + 1] + "".join(reversed(stack_at_last_close))


def _loads_lenient(candidate: str) -> dict | None:
    """소형모델·API가 흔히 내는 사소한 JSON 흠을 교정해 파싱한다."""
    attempts = [candidate]
    # 후행 콤마 + 스마트 따옴표
    fixed = _TRAILING_COMMA.sub(r"\1", candidate)
    fixed = (fixed.replace("“", '"').replace("”", '"')
                  .replace("‘", "'").replace("’", "'"))
    attempts.append(fixed)
    # 토큰 한도로 끊긴 경우
    closed = _close_unterminated(fixed)
    if closed:
        attempts.append(_TRAILING_COMMA.sub(r"\1", closed))

    for a in attempts:
        try:
            data = json.loads(a)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def looks_like_workflow_attempt(text: str) -> bool:
    """워크플로우를 만들려다 형식이 깨진 응답인가 (일반 텍스트 답변과 구분)."""
    t = text or ""
    return ("```" in t or "{" in t) and ('"nodes"' in t or "'nodes'" in t or '"edges"' in t)


def parse_workflow_response(text: str) -> dict | None:
    """LLM 응답에서 WorkflowJSON 추출. Returns dict or None."""
    # ```json ... ``` 블록 추출 (닫는 펜스가 잘렸을 수도 있어 폴백 포함)
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
    else:
        open_fence = re.search(r"```(?:json)?\s*\n?", text)
        if open_fence and "{" in text[open_fence.end():]:
            candidate = text[open_fence.end():].strip()
        else:
            # JSON 객체 직접 탐색
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start == -1:
                return None
            candidate = (text[brace_start:brace_end + 1] if brace_end > brace_start
                         else text[brace_start:])

    data = _loads_lenient(candidate)
    if data is None:
        return None

    # 필수 필드 검증
    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        return None

    if len(data["nodes"]) == 0:
        return None

    # position 자동 할당 (없는 노드에만)
    _auto_layout(data)

    return data


def repair_workflow_ports(data: dict, registry) -> list[str]:
    """엣지의 잘못된 포트명을 타입 호환성으로 코드가 고친다 — '계산·검증은 코드'.

    소형모델은 노드 종류는 맞혀도 포트명을 지어내는 경향이 있다(실측: 'text',
    'input_text'). 후보가 **하나뿐일 때만** 고치고, 애매하면 손대지 않아
    validate_workflow가 사유를 사용자에게 알리게 둔다(무음 오배선 방지).
    반환: 수정 내역 문자열 목록.
    """
    from engine.types import types_compatible

    fixes: list[str] = []
    node_map = {n.get("id"): n for n in data.get("nodes", []) if n.get("id")}

    for e in data.get("edges", []):
        src_id = e.get("from") or e.get("source", "")
        tgt_id = e.get("to") or e.get("target", "")
        if src_id == tgt_id:
            continue  # 자기 연결은 보정 대상이 아니다 — validate가 사유를 알린다
        src_node, tgt_node = node_map.get(src_id), node_map.get(tgt_id)
        if not src_node or not tgt_node:
            continue
        src_def = registry.get(src_node.get("type"))
        tgt_def = registry.get(tgt_node.get("type"))
        if not src_def or not tgt_def:
            continue

        from_port = e.get("from_port") or e.get("sourceHandle") or ""
        to_port = e.get("to_port") or e.get("targetHandle") or ""
        out_port = src_def.get_output_port(from_port)
        in_port = tgt_def.get_input_port(to_port)

        # 둘 다 실재하고 타입도 맞으면 손대지 않는다
        if out_port and in_port and types_compatible(out_port, in_port):
            continue

        # 타입이 맞는 (출력,입력) 조합만 후보. 이미 맞은 쪽을 보존하는 조합이
        # 있으면 그쪽을 우선한다(최소 수정). 후보가 유일할 때만 고친다.
        pairs = [(o, i) for o in src_def.outputs for i in tgt_def.inputs
                 if types_compatible(o, i)]
        if not pairs:
            continue
        keep = [p for p in pairs if p[0].name == from_port or p[1].name == to_port]
        cands = keep or pairs
        if len(cands) != 1:
            continue

        o, i = cands[0]
        if o.name != from_port:
            fixes.append(f"'{src_node['id']}'의 출력 포트를 '{from_port}' → '{o.name}'로 보정")
            e["from_port"] = o.name
        if i.name != to_port:
            fixes.append(f"'{tgt_node['id']}'의 입력 포트를 '{to_port}' → '{i.name}'로 보정")
            e["to_port"] = i.name

    return fixes


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

    from engine.types import types_compatible

    node_map = {n.get("id"): n for n in data.get("nodes", []) if n.get("id")}
    for e in data.get("edges", []):
        src = e.get("from") or e.get("source", "")
        tgt = e.get("to") or e.get("target", "")
        if src not in node_ids:
            errors.append(f"연결의 출발 노드 '{src}'가 존재하지 않습니다.")
        if tgt not in node_ids:
            errors.append(f"연결의 도착 노드 '{tgt}'가 존재하지 않습니다.")
        if src and src == tgt:
            # 소형모델이 단일 노드 워크플로우에서 자주 만드는 자기 연결.
            # 포트 오류로 보고하면 사용자가 원인을 못 찾는다 → 사유를 명시.
            errors.append(f"노드 '{src}'가 자기 자신에 연결되어 있습니다. "
                          f"연결은 서로 다른 두 노드 사이에만 만들 수 있습니다.")
            continue

        # 포트명 검증 (노드type이 유효할 때만)
        out_port = in_port = None
        for nid, port_key, kind in ((src, "from_port", "out"), (tgt, "to_port", "in")):
            node = node_map.get(nid)
            if not node:
                continue
            nd = registry.get(node.get("type"))
            if nd is None:
                continue
            pname = e.get(port_key) or e.get(
                "sourceHandle" if kind == "out" else "targetHandle", "")
            port = nd.get_output_port(pname) if kind == "out" else nd.get_input_port(pname)
            if pname and port is None:
                label = "출력" if kind == "out" else "입력"
                names = ", ".join(f"'{p.name}'" for p in (nd.outputs if kind == "out" else nd.inputs))
                errors.append(f"노드 '{nid}'에 '{pname}' {label} 포트가 없습니다"
                              f"{f' (가능: {names})' if names else ''}.")
            if kind == "out":
                out_port = port
            else:
                in_port = port

        # 타입 호환성 — 실행 시점에 조용히 깨지는 연결을 저장 전에 막는다
        if out_port and in_port and not types_compatible(out_port, in_port):
            errors.append(
                f"연결 타입 불일치: '{src}.{out_port.name}'({out_port.type}) → "
                f"'{tgt}.{in_port.name}'({in_port.type}).")
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
    """채팅 메시지 처리(워크플로우 생성). Returns {reply, workflow_id, workflow_json}.

    양식 파일 + 채우기 의도는 **라우트(`routes/chat.py`)가 먼저 가로채** FormAssist로
    보낸다. 여기서 같은 라우팅을 중복 구현했더니 두 판이 갈라졌고(스캔 범위·자동
    열기 차이), 이쪽 판은 COM 스캔을 run_on_com 밖에서 동기 호출하는 문제도 있었다.
    """
    presets_dir = Path(store._presets_dir) if hasattr(store, "_presets_dir") else Path("data/presets")

    # 모델 파싱 (provider/model 형식). 미지정이면 설정의 활성 프로바이더를
    # 따른다 — openai 하드코딩 폴백은 '로컬 우선' 설정을 무시하고 429를 냈다.
    if model and "/" in model:
        provider, model_name = model.split("/", 1)
    else:
        try:
            info = llm_manager.get_provider_info("auto")
            provider, model_name = info.get("provider", "openai"), info.get("model", "")
        except Exception:
            provider, model_name = "openai", "gpt-4.1"

    # 1. 시스템 프롬프트 구성 (로컬은 envelope 형식 지시를 덧붙인다)
    system_prompt = build_system_prompt(registry, presets_dir)
    envelope_schema = build_workflow_envelope_schema(registry) if provider == "local" else None
    if envelope_schema:
        system_prompt += build_workflow_envelope_note()

    # 2. 메시지 조합 — history는 최근 N턴만(소형모델 컨텍스트 보호)
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-_HISTORY_TURNS:]:
        if "role" in h and "content" in h:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # 3. LLM 호출 — 로컬은 json_schema로 GBNF 강제 디코딩(노드 type 환각 차단)
    try:
        reply = llm_manager.generate_chat(
            messages,
            max_tokens=4096,
            temperature=0.3,
            provider=provider,
            model=model_name,
            json_schema=envelope_schema,
        )
    except Exception as e:
        # 실패 시 다른 provider로 fallback
        try:
            prompt = f"시스템:\n{system_prompt}\n\n사용자:\n{message}"
            reply = llm_manager.generate(prompt, max_tokens=4096, temperature=0.3)
            envelope_schema = None  # 폴백 경로는 강제 없음 → legacy 파서로
        except Exception as e2:
            return {
                "reply": f"LLM 호출 실패: {e2}",
                "workflow_id": None,
                "workflow_json": None,
            }

    # 4. 워크플로우 파싱 — envelope 우선, 실패 시 legacy 코드펜스 파서 폴백
    workflow = None
    env = parse_workflow_envelope(reply)
    if env is not None:
        reply, workflow = env[0] or reply, env[1]
    else:
        workflow = parse_workflow_response(reply)

        # 형식이 깨졌는데(=워크플로우를 만들려던 응답) 관대한 파서로도 못 살리면
        # 온도를 낮춰 1회만 재시도한다. 그래도 실패하면 깨진 JSON 덩어리를
        # 그대로 보여주지 않고 무엇을 하면 되는지 알려준다.
        if workflow is None and looks_like_workflow_attempt(reply):
            _log.info("워크플로우 JSON 파싱 실패 — 저온 재시도 1회")
            retry_messages = messages + [
                {"role": "assistant", "content": reply[:2000]},
                {"role": "user", "content":
                 "직전 응답의 JSON 형식이 올바르지 않아 읽지 못했습니다. "
                 "설명 없이 유효한 JSON 하나만 다시 출력해 주세요."},
            ]
            try:
                reply2 = llm_manager.generate_chat(
                    retry_messages, max_tokens=4096, temperature=0.1,
                    provider=provider, model=model_name, json_schema=envelope_schema,
                )
            except Exception:
                reply2 = ""
            if reply2:
                env2 = parse_workflow_envelope(reply2)
                if env2 is not None:
                    reply, workflow = env2[0] or reply2, env2[1]
                else:
                    workflow = parse_workflow_response(reply2)
                    if workflow is not None:
                        reply = reply2
            if workflow is None:
                return {
                    "reply": ("워크플로우 형식을 만드는 데 실패했습니다. "
                              "요청을 더 짧게 나누거나(예: 단계 3개 이하), "
                              "쓰고 싶은 파일 형식을 함께 적어 다시 시도해 주세요."),
                    "workflow_id": None,
                    "workflow_json": None,
                }

    # 5. 워크플로우가 있으면 포트 보정 → 검증 후 저장
    if workflow:
        fixes = repair_workflow_ports(workflow, registry)
        if fixes:
            _log.info("포트 자동 보정 %d건: %s", len(fixes), "; ".join(fixes))
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
