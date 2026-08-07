# -*- coding: utf-8 -*-
"""nodes/*/node.yaml → src/defaultNodes.ts 생성.

`src/defaultNodes.ts`는 **엔진 미연결 시에만 쓰는 폴백 사본**인데 수작업이라
진실원천(node.yaml)과 계속 어긋났다(lora 파라미터 누락, 이름·아이콘 불일치).
이 스크립트로 재생성한다.

    npm run gen:nodes          (= python scripts/gen_default_nodes.py)
    python scripts/gen_default_nodes.py --check   # 드리프트만 검사(생성 안 함)

--check는 재생성 결과가 현재 파일과 다르면 exit 1 — 테스트/CI에서 사용.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NODES_DIR = ROOT / "nodes"
OUT = ROOT / "src" / "defaultNodes.ts"

HEADER = """import type { NodeDefinition } from "./types";

/** 엔진 미연결 시 사용할 기본 노드 정의.
 *
 *  ⚠️ 이 파일은 자동 생성된다 — 직접 고치지 마라.
 *  진실원천은 `nodes/<id>/node.yaml`이고, 바꾼 뒤 `npm run gen:nodes`로 재생성한다.
 */
export const DEFAULT_NODE_DEFINITIONS: NodeDefinition[] = [
"""

# 카테고리 표시 순서 (팔레트 정렬과 맞춤)
CATEGORY_ORDER = ["변환", "전처리", "LLM", "출력", "유틸"]


def _ts(value) -> str:
    """JS 리터럴로 직렬화 (한글 그대로, JSON 호환 형태)."""
    return json.dumps(value, ensure_ascii=False)


def _port(p: dict) -> dict:
    out = {"name": p["name"], "type": p["type"]}
    if p.get("accept"):
        out["accept"] = p["accept"]
    if p.get("optional"):
        out["optional"] = True
    return out


def _param(p: dict) -> dict:
    out = {"id": p["id"], "label": p.get("label", p["id"]), "type": p.get("type", "string")}
    if "default" in p:
        out["default"] = p["default"]
    if p.get("options"):
        out["options"] = p["options"]
    if p.get("description"):
        out["description"] = p["description"]
    return out


def load_nodes() -> list[dict]:
    defs = []
    for child in sorted(NODES_DIR.iterdir()):
        yml = child / "node.yaml"
        if not child.is_dir() or not yml.exists():
            continue
        d = yaml.safe_load(yml.read_text(encoding="utf-8"))
        defs.append({
            "id": d["id"],
            "name": d.get("name", d["id"]),
            "version": str(d.get("version", "1.0.0")),
            "category": d.get("category", "유틸"),
            "icon": d.get("icon", "box"),
            "author": d.get("author", ""),
            "description": " ".join((d.get("description") or "").split()),
            "inputs": [_port(p) for p in (d.get("inputs") or [])],
            "outputs": [_port(p) for p in (d.get("outputs") or [])],
            "params": [_param(p) for p in (d.get("params") or [])],
            "resource": {k: v for k, v in (d.get("resource") or {}).items()
                         if k in ("requires_api", "max_memory_mb", "estimated_time")},
            "use_when": d.get("use_when") or [],
        })
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    defs.sort(key=lambda n: (order.get(n["category"], 99), n["id"]))
    return defs


def render(defs: list[dict]) -> str:
    lines = [HEADER]
    current_cat = None
    for n in defs:
        if n["category"] != current_cat:
            current_cat = n["category"]
            lines.append(f"  // ─── {current_cat} ───────────────────────\n")
        lines.append("  {\n")
        lines.append(f'    id: {_ts(n["id"])}, name: {_ts(n["name"])}, version: {_ts(n["version"])},\n')
        lines.append(f'    category: {_ts(n["category"])}, icon: {_ts(n["icon"])}, author: {_ts(n["author"])},\n')
        lines.append(f'    description: {_ts(n["description"])},\n')
        lines.append(f'    inputs: {_ts(n["inputs"])},\n')
        lines.append(f'    outputs: {_ts(n["outputs"])},\n')
        lines.append(f'    params: {_ts(n["params"])},\n')
        lines.append(f'    resource: {_ts(n["resource"])},\n')
        if n["use_when"]:
            lines.append(f'    use_when: {_ts(n["use_when"])},\n')
        lines.append("  },\n")
    lines.append("];\n")
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="재생성 결과가 현재 파일과 다르면 exit 1 (파일은 쓰지 않음)")
    args = ap.parse_args()

    defs = load_nodes()
    content = render(defs)

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != content:
            print(f"[DRIFT] {OUT.relative_to(ROOT)}가 node.yaml과 다릅니다 — "
                  f"`npm run gen:nodes`로 재생성하세요.")
            return 1
        print(f"[OK] defaultNodes.ts가 node.yaml {len(defs)}개와 일치합니다.")
        return 0

    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"[OK] {OUT.relative_to(ROOT)} 생성 — 노드 {len(defs)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
