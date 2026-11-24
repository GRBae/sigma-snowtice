"""
학과별 스캔 결과(data/raw/dept_scan/*.txt) + 주요공지·수학과 목록을 하나로 합치고,
제목만 보고 1차 분류한다 (본문을 읽기 전 단계라 '추정' 분류).

  python crawler/aggregate_dept_scan.py
  → data/raw/graduation_index_all.csv, data/raw/dept_registry.csv, 콘솔 요약
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "data" / "raw" / "dept_scan"

# 제목 → 분류 (위에서부터 먼저 맞는 것)
RULES = [
    ("대학원", r"\[대학원\]|학위청구|석사|박사|종합시험\(석사|아동심리치료전공"),
    ("교직(교원양성센터 재게시)", r"교원자격무시험검정"),
    ("폭력예방교육(기관 재게시)", r"폭력예방교육"),
    ("본부 재게시", r"주요\s*졸업\s*일정|졸업\s*계획\s*제출|졸업계획입력|수료생\s*졸업\s*신청|졸업\s*신청 실시|"
                 r"졸업인증제.*(제출|시행)|인증제 제출|논문/정보 능력 인증|조기\s*졸업|최종\s*졸업\s*사정|졸업\s*사정\s*결과|"
                 r"졸업인증제.*심사결과|졸업논문제 심사결과 조회|영문성명|계속수학|"
                 r"(2026학년도 전기|2025학년도 후기|2026학년도 후기)\(20\d\d년 \d월 졸업\) 졸업\s*논문제 신청 안내|"
                 r"^\[졸업\] 202[56]-[12]학기 졸업논문제 신청 안내$|졸업학점 이수현황|졸업심사결과조회$|졸업심사결과별 통지문|졸업심사기준"),
    ("학과 자체", r"."),
]
NOISE = r"졸업생 특강|졸업생만을 위한|졸업 후 진로|KCI 게재|졸업요건 test|국무총리|졸업생 인터뷰"


def classify(title: str) -> str:
    for label, pat in RULES:
        if re.search(pat, title):
            return label
    return "학과 자체"


def infer_term(title: str, posted: str) -> str:
    t = title
    if re.search(r"2027\s*[.년]\s*2\s*월|2027\.\s*2월|2026학년도\s*전기|2026-2|26-2|2026학년도\s*2학기|2026년\s*2학기", t):
        return "2026-2"
    if re.search(r"2026\s*[.년]\s*8\s*월|2025학년도\s*후기|2026-1|26-1|2026학년도\s*1학기|2026년\s*1학기|2026년도\s*1학기", t):
        return "2026-1"
    if re.search(r"2026\s*[.년]\s*2\s*월|2025학년도\s*전기|2025-2|26년 2월", t):
        return "2025-2"
    if re.search(r"2027-1", t):
        return "2027-1"
    m = posted[5:7] if posted else ""
    if not m:
        return "?"
    return "2025-2" if m == "01" else ("2026-1" if m <= "07" else "2026-2")


def main():
    rows, registry = [], []
    for f in sorted(SCAN.glob("*.txt")):
        site = dept = None
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("#site "):
                site, dept = line[6:].split("|", 1)
                registry.append({"file": f.name, "host": site, "dept": dept, "boards": [], "static": [], "notes": []})
            elif line.startswith("#board "):
                registry[-1]["boards"].append(line[7:])
            elif line.startswith("#static "):
                registry[-1]["static"].append(line[8:])
            elif line.startswith("#note "):
                registry[-1]["notes"].append(line[6:])
            elif line.strip() and not line.startswith("#"):
                parts = line.split("|", 4)
                if len(parts) == 4:  # 게시판 칸이 없는 초기 형식
                    no, posted, hits, title = parts
                    board = registry[-1]["boards"][0].split("|")[0] if registry[-1]["boards"] else ""
                else:
                    no, posted, hits, board, title = parts
                rows.append({"source": "학과", "dept": dept, "host": site, "board": board, "id": no, "posted": posted,
                             "hits": hits, "title": title})
    # 대표 홈페이지 주요공지 + 수학과 (앞서 모은 목록)
    for line in (ROOT / "data" / "raw" / "list_index_graduation.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        main_site = r["site_id"] == "main_notice"
        rows.append({"source": "대표 홈페이지" if main_site else "학과", "dept": "대표 홈페이지 주요공지" if main_site else "수학과",
                     "host": "www.sookmyung.ac.kr" if main_site else "math.sookmyung.ac.kr",
                     "board": "주요공지" if main_site else "공지사항", "id": r["article_no"], "posted": r.get("posted") or "",
                     "hits": r.get("hits_list_2026_11_24", ""), "title": r["title"]})
    registry.append({"file": "(이전 수집)", "host": "math.sookmyung.ac.kr", "dept": "수학과",
                     "boards": ["공지사항|/math/notice/notice.do|sm_cms"], "static": [], "notes": []})

    for r in rows:
        r["posted"] = r["posted"].replace(".", "-")
        r["noise"] = bool(re.search(NOISE, r["title"]))
        r["kind"] = "대표 홈페이지 원본" if r["source"] == "대표 홈페이지" else classify(r["title"])
        r["term"] = infer_term(r["title"], r["posted"])
    rows = [r for r in rows if not r["noise"]]

    out = ROOT / "data" / "raw" / "graduation_index_all.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["dept", "kind", "term", "posted", "title", "board", "id", "hits", "host", "source"])
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["dept"] != "대표 홈페이지 주요공지", r["dept"], r["posted"]), reverse=False):
            w.writerow({k: r[k] for k in w.fieldnames})

    with (ROOT / "data" / "raw" / "dept_registry.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["학과", "호스트", "게시판(이름|경로|엔진|읽은 글 수|가장 오래된 날짜)", "고정 안내 페이지", "메모"])
        for g in registry:
            w.writerow([g["dept"], g["host"], " / ".join(g["boards"]), " / ".join(g["static"]), " / ".join(g["notes"])])

    # 요약
    by_kind = Counter(r["kind"] for r in rows)
    by_dept = defaultdict(Counter)
    for r in rows:
        by_dept[r["dept"]][r["kind"]] += 1
    print(f"전체 {len(rows)}건 (잡음 제외)\n분류: {dict(by_kind)}")
    print(f"학과(사이트) 수: {len(registry)}  · 졸업 글이 있는 학과: {sum(1 for d in by_dept if d != '대표 홈페이지 주요공지')}")
    print("\n학과 자체 공지가 있는 학과:")
    for d, c in sorted(by_dept.items(), key=lambda x: -x[1]["학과 자체"]):
        if c["학과 자체"]:
            print(f"  {d}: 학과 자체 {c['학과 자체']} / 재게시 {c['본부 재게시']} / 전체 {sum(c.values())}")
    engines = Counter()
    for g in registry:
        for b in g["boards"]:
            parts = b.split("|")
            if len(parts) > 2:
                engines[re.sub(r"[-(].*", "", parts[2]).strip()] += 1
    print("\n게시판 엔진:", dict(engines))


if __name__ == "__main__":
    main()
