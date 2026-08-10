# -*- coding: utf-8 -*-
"""엄정 채움 벤치 (§41b 프로토콜) — dataset_v10 val 채움형 8문서/90필드.

- 분모 = 전 문서 gold 필드 전체. 파싱 실패 문서 = 해당 필드 전부 0점.
- 스키마 강제(json_schema, 셀ID enum + maxItems) + enable_thinking:false.
- 사용: python strict_fill_bench.py <port> <label>
"""
import json, sys, re, urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else "8402"
LABEL = sys.argv[2] if len(sys.argv) > 2 else "model"
LORA_SCALE = float(sys.argv[3]) if len(sys.argv) > 3 else None  # None=서버 기본

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()

docs = []
for line in open("D:/lora_data/dataset_v10/val.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["completion"].lstrip().startswith("{") and '"id"' in r["completion"]:
        docs.append(r)

total_gold = 0
correct = 0
parse_fail = 0
rows = []
for i, s in enumerate(docs):
    gold = json.loads(s["completion"])
    key = list(gold.keys())[0]
    items = [it for it in gold[key] if isinstance(it, dict) and "id" in it]
    vkey = [k for k in items[0].keys() if k != "id"][0]
    gold_map = {it["id"]: norm(it[vkey]) for it in items}
    total_gold += len(gold_map)
    ids = list(gold_map.keys())
    schema = {"type": "object", "properties": {key: {"type": "array",
        "maxItems": len(ids), "items": {"type": "object", "properties": {
            "id": {"type": "string", "enum": ids}, vkey: {"type": "string"}},
            "required": ["id", vkey]}}}, "required": [key]}
    payload = {"model": "m", "temperature": 0, "max_tokens": 3000,
        "messages": [{"role": "user", "content": s["prompt"]}],
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema",
            "json_schema": {"name": "fill", "schema": schema}}}
    if LORA_SCALE is not None:
        payload["lora"] = [{"id": 0, "scale": LORA_SCALE}]
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            out = json.load(resp)
        content = out["choices"][0]["message"].get("content") or ""
        pred = json.loads(content)
        seen = {}
        for it in pred.get(key, []):
            if isinstance(it, dict) and "id" in it and it["id"] not in seen:
                seen[it["id"]] = norm(it.get(vkey, ""))
        doc_ok = sum(1 for cid, gv in gold_map.items() if seen.get(cid) == gv)
        correct += doc_ok
        rows.append((i, len(gold_map), doc_ok, "OK"))
    except Exception as e:
        parse_fail += 1
        rows.append((i, len(gold_map), 0, f"FAIL:{type(e).__name__}"))

for i, n, ok, st in rows:
    print(f"  doc{i}: {ok}/{n} {st}")
print(f"\n[{LABEL}] 엄정 정확도 {correct}/{total_gold} = {100*correct/total_gold:.0f}% | 파싱실패 {parse_fail}/{len(docs)}")
