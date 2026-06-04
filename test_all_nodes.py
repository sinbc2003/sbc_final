"""모든 노드 개별 테스트."""
import requests, json, os, time

BASE = "http://127.0.0.1:8321"
PDF = os.path.abspath("data/uploads/test_exam.pdf")
HWPX = None
for f in os.listdir("data/uploads"):
    if f.endswith(".hwpx") and "test" not in f and "_" not in f:
        HWPX = os.path.abspath(f"data/uploads/{f}")
        break

TXT = "2024학년도 수학 시험. 이차방정식, 역함수, 코사인법칙 등을 다룬다. 총 5문항, 각 20점."
MD_TABLE = "| 이름 | 점수 |\n|------|------|\n| 김철수 | 95 |\n| 이영희 | 88 |"

results = []
def run(name, nodes, edges=None, inputs=None):
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/api/run", json={
            "id": "t", "name": name, "version": "1.0.0",
            "nodes": nodes, "edges": edges or [],
            "user_inputs": [], "initial_inputs": inputs or {},
        }, timeout=60)
        d = r.json()
        ok = d.get("success", False)
        errs = d.get("errors", [])
        outs = d.get("outputs", {})
        results.append((name, ok, time.time()-t0, errs[:1], outs))
    except Exception as e:
        results.append((name, False, time.time()-t0, [str(e)[:80]], {}))

N = lambda t, p={}: {"id": "n1", "type": t, "position": {"x": 0, "y": 0}, "params": p}

# 변환 노드
run("pdf_to_md", [N("pdf_to_md", {"pages": "전체"})], inputs={"n1": {"파일": PDF}})
run("hwpx_to_md", [N("hwpx_to_md")], inputs={"n1": {"파일": HWPX}} if HWPX else {})
run("xlsx_to_md (no file)", [N("xlsx_to_md")], inputs={"n1": {"파일": "none.xlsx"}})
run("pptx_to_md (no file)", [N("pptx_to_md")], inputs={"n1": {"파일": "none.pptx"}})
run("docx_to_md (no file)", [N("docx_to_md")], inputs={"n1": {"파일": "none.docx"}})
run("image_to_text (no file)", [N("image_to_text")], inputs={"n1": {"파일": "none.png"}})
run("url_to_md", [N("url_to_md")], inputs={"n1": {"URL": "https://example.com"}})

# 전처리 노드
run("table_extract", [N("table_extract", {"table_index": 0})], inputs={"n1": {"텍스트": MD_TABLE}})
run("text_split", [N("text_split", {"chunk_size": 50, "overlap": 10})], inputs={"n1": {"텍스트": TXT}})
run("data_merge", [N("data_merge", {"join_type": "concat"})], inputs={"n1": {"표목록": '[{"a":1}]'}})
run("column_mapping", [N("column_mapping", {"mapping_rules": "이름->name"})], inputs={"n1": {"표데이터": '[{"이름":"김철수","점수":95}]'}})
run("image_extract (no file)", [N("image_extract")], inputs={"n1": {"파일": "none.pdf"}})

# LLM 노드
run("llm_generate", [N("llm_generate", {"prompt_template": "1+1=?", "provider": "openai", "max_tokens": 20})], inputs={"n1": {"입력텍스트": "test"}})
run("llm_summarize", [N("llm_summarize", {"style": "bullet", "max_length": 100})], inputs={"n1": {"입력텍스트": TXT}})
run("llm_translate", [N("llm_translate", {"target_lang": "영어"})], inputs={"n1": {"입력텍스트": "안녕하세요"}})
run("llm_classify", [N("llm_classify", {"categories": "수학, 과학, 국어"})], inputs={"n1": {"입력텍스트": "이차방정식"}})
run("llm_extract", [N("llm_extract", {"fields": "과목, 문항수"})], inputs={"n1": {"입력텍스트": TXT}})

# 출력 노드
run("md_to_hwpx", [N("md_to_hwpx", {"output_name": "t"})], inputs={"n1": {"텍스트": "# 제목\n본문"}})
run("md_to_docx", [N("md_to_docx", {"output_name": "t"})], inputs={"n1": {"텍스트": "# 제목\n본문"}})
run("save_xlsx", [N("save_xlsx", {"output_name": "t"})], inputs={"n1": {"표데이터": '[{"이름":"김철수","점수":95}]'}})

# 유틸 노드
run("file_input", [N("file_input", {"path": PDF})], inputs={})
run("text_input", [N("text_input", {"content": "테스트"})], inputs={})
run("text_template", [N("text_template", {"template": "A={{입력1}} B={{입력2}}"})], inputs={"n1": {"입력1": "X", "입력2": "Y"}})

# 결과 출력
with open("data/uploads/_node_test_all.txt", "w", encoding="utf-8") as f:
    ok_count = sum(1 for _, ok, _, _, _ in results if ok)
    fail_expected = sum(1 for name, _, _, _, _ in results if "no file" in name)
    f.write(f"=== 노드 개별 테스트: {ok_count}/{len(results)} 성공 ({fail_expected}개는 파일 없어 예상 실패) ===\n\n")
    for name, ok, elapsed, errs, outs in results:
        marker = "OK" if ok else "FAIL"
        f.write(f"[{marker}] {name} ({elapsed:.1f}s)\n")
        for e in errs:
            f.write(f"  ERR: {str(e)[:150]}\n")
        f.write("\n")

print(f"{ok_count}/{len(results)} passed")
