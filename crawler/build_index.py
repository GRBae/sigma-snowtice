"""
목록 합치기 → data/raw/graduation_index_all.csv (pipeline/group.py의 입력)

  python crawler/build_index.py

  - 오늘 크롤링한 목록(data/raw/list_today.jsonl)이 있는 사이트는 그걸 쓴다 (학교 CMS·k2web 37곳 + 대표 홈페이지·수학과)
  - 어댑터가 없는 사이트(그누보드·KBoard·자체 CMS 9곳)는 브라우저 스캔 결과(data/raw/dept_scan/*.txt)를 쓴다
    → 이 9곳은 어댑터를 만들기 전까지 매일 갱신되지 않는다 (lint에 표시)
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from aggregate_dept_scan import NOISE, classify, infer_term  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw"
FIELDS = ["dept", "kind", "term", "posted", "title", "board", "id", "hits", "host", "source"]


def from_scan() -> list[dict]:
    rows = []
    for f in sorted((RAW / "dept_scan").glob("*.txt")):
        host = dept = board0 = None
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("#site "):
                host, dept = line[6:].split("|", 1)
                dept = re.sub(r"\s*\(.*", "", dept)
                board0 = None
            elif line.startswith("#board ") and board0 is None:
                board0 = line[7:].split("|")[0]
            elif line.strip() and not line.startswith("#"):
                p = line.split("|", 4)
                no, posted, hits, board, title = (p[0], p[1], p[2], board0, p[3]) if len(p) == 4 else p
                rows.append({"source": "학과", "dept": dept, "host": host, "board": board, "id": no, "posted": posted, "hits": hits, "title": title})
    for line in (RAW / "list_index_graduation.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        main = r["site_id"] == "main_notice"
        rows.append({"source": "대표 홈페이지" if main else "학과", "dept": "대표 홈페이지 주요공지" if main else "수학과",
                     "host": "www.sookmyung.ac.kr" if main else "math.sookmyung.ac.kr", "board": "주요공지" if main else "공지사항",
                     "id": r["article_no"], "posted": r.get("posted") or "", "hits": r.get("hits_list_2026_11_24", ""), "title": r["title"]})
    return rows


def main():
    scan = from_scan()
    live, live_hosts = [], set()
    lt = RAW / "list_today.jsonl"
    if lt.exists():
        for line in lt.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            live_hosts.add(d["host"])
            live.append({"source": "대표 홈페이지" if d["source"] == "main" else "학과", "dept": d.get("dept") or d["source"], "host": d["host"],
                         "board": d["board"], "id": d["article_no"], "posted": (d.get("posted") or "").replace(".", "-"), "hits": "", "title": d["title"]})
    rows = live + [r for r in scan if r["host"] not in live_hosts]
    # 목록 화면에서 조회수를 못 읽은 글은 본문 수집 때 저장한 meta.json의 조회수로 채운다 (수집 시점 값)
    for r in rows:
        if r.get("hits"):
            continue
        sid = "main" if r["host"].startswith("www.") else r["host"].split(".")[0]
        mf = RAW / f"{sid}_{r['id']}" / "meta.json"
        if mf.exists():
            try:
                h = json.loads(mf.read_text(encoding="utf-8")).get("hits")
                if h is not None:
                    r["hits"] = str(h)
            except (ValueError, OSError):
                pass
    seen, out = set(), []
    for r in rows:
        key = (r["host"], r["id"])
        if key in seen or re.search(NOISE, r["title"]) or not r["posted"]:
            continue
        seen.add(key)
        r["kind"] = "대표 홈페이지 원본" if r["source"] == "대표 홈페이지" else classify(r["title"])
        r["term"] = infer_term(r["title"], r["posted"])
        out.append(r)
    with (RAW / "graduation_index_all.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(out, key=lambda r: (r["dept"] != "대표 홈페이지 주요공지", r["dept"], r["posted"])))
    stale = sorted({r["dept"] for r in out if r["host"] not in live_hosts})
    print(f"목록 {len(out)}건 (오늘 크롤링 {len(live)} · 브라우저 스캔 {len(out) - len([r for r in out if r['host'] in live_hosts])})")
    if lt.exists():
        print("매일 갱신 안 되는 사이트:", ", ".join(stale))


if __name__ == "__main__":
    main()
