"""
브라우저 수집 + Claude 직접 추출 결과(work/compact/*.json)를 표준 추출 파일(data/extracted/{key}.json)로 펼친다.
근거 문장은 브라우저에서 원문과 대조(work/meta/*.json의 check=ALL_OK)했으므로 verification에 그 기록을 남긴다.
원문 메타(길이·해시·첨부 이름)는 data/raw/{key}/meta.json 에 저장한다. 본문 텍스트는 다음 정기 수집(crawl.py)에서 저장된다.
"""
from __future__ import annotations
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W = ROOT / "work"
q = {r["rep"].split(":")[1] + "_" + r["id"]: r for r in csv.DictReader(open(ROOT / "data/graph/fetch_queue.csv", encoding="utf-8-sig"))}
idx = {(r["host"], r["id"]): r for r in csv.DictReader(open(ROOT / "data/raw/graduation_index_all.csv", encoding="utf-8-sig"))}
jobs = {x["key"]: x["url"] for v in json.load(open(W / "jobs.json")).values() for x in v}
meta, urls = {}, {}
for f in (W / "meta").glob("*.json"):
    m = json.loads(f.read_text())
    assert m["check"] == "ALL_OK", f
    meta.update(m["m"]); urls.update(m.get("urls", {}))

def date(lo, hi, o):
    if lo is None and hi is None:
        return None
    p = o.get("p") or ("minute" if "T" in (hi or lo or "") else "day")
    d = {"lo": lo, "hi": hi, "precision": p}
    if o.get("tentative"): d["tentative"] = True
    if o.get("yi"): d["year_inferred"] = True
    return d

n = 0
for f in sorted((W / "compact").glob("*.json")):
    for e in json.loads(f.read_text()):
        k = e["k"]; src, no = k.split("_", 1); r = q[k]
        ir = idx.get((r["host"], r["id"]), {})
        dept = f"dept:{src}"
        stages = []
        for key, name, lo, hi, ev, o in e["st"]:
            s = {"key": key, "name": name, "scope": o.get("scope", src), "procedure_template": "tmpl:grad",
                 "date": date(lo, hi, o), "route": o.get("route"), "place": o.get("place"), "target": o.get("target"),
                 "required": o.get("required", True), "documents": o.get("docs", []), "requires": [], "evidence": ev}
            if o.get("ov"): s["overrides"] = "본부"
            if o.get("term"): s["term"] = o["term"]
            stages.append(s)
        ex = {"notice": {"id": f"notice:{src}:{no}", "source": src, "article_no": no, "url": urls.get(k) or jobs.get(k),
                         "title": r["title"], "posted": r["posted"], "posted_by": dept, "hits": int(ir["hits"]) if ir.get("hits", "").isdigit() else None},
              "skip": False, "role": e["role"], "topic": "졸업",
              "procedure": {"template": "tmpl:grad", "term": e["term"], "scope": src},
              "issued_by": e.get("issued", dept), "stages": stages, "rules": [],
              "cautions": [{"id": f"caution:{k}:{i}", "text": t, "evidence": [ev]} for i, (t, ev) in enumerate(e.get("cau", []))],
              "outcomes": [],
              "contacts": [{"topic": t, "college": dept, "office": off, "phone": ph, "evidence": [ev]} for t, off, ph, ev in e.get("ct", [])],
              "refers_to": [],
              "verification": {"result": "근거 문장 전부 원문에 있음 (2026-11-24 브라우저 수집본과 대조)",
                               "extractor": "Claude 직접 추출 (LLM API 확정 전)"}}
        (ROOT / "data/extracted" / f"{k}.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
        ln, sha, atts = meta[k]
        rd = ROOT / "data/raw" / k; rd.mkdir(parents=True, exist_ok=True)
        (rd / "meta.json").write_text(json.dumps({"key": k, "url": ex["notice"]["url"], "title": r["title"], "posted": r["posted"],
            "fetched": "2026-11-24", "via": "built-in browser", "text_len": ln, "text_sha16": sha, "attachments": atts}, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
print("추출 파일", n, "건 생성")
