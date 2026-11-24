"""
⑦ 린트 — 그래프·페이지끼리 모순과 빈 곳을 찾는다.

  python pipeline/lint.py [--today 2026-11-24]   → wiki/lint_report.md (팀 내부용, SNOWCHAT에 올리지 않음)

점검
  1. 같은 단계를 여러 공지가 다른 날짜로 말함            → 충돌
  2. 학과 단계가 본부 단계를 덮어씀(OVERRIDES)            → 학과 학생에게 학과 날짜로 안내되는지 확인
  3. 같은 주제·단과대학 문의처 번호가 공지마다 다름        → 충돌
  4. 고정 안내의 '대략적 시기'와 이번 학기 실제 날짜가 다름 → 학기 공지 우선 (페이지에 고정 안내 시기를 쓰지 않음)
  5. '예정·변동 가능' 날짜, 날짜 없는 단계                 → 상세 공지 나오면 갱신
  6. 본문을 아직 못 읽은 대표 공지 수                      → 수집 대기
  7. 유효기간이 지난 절차                                  → SNOWCHAT에서 끌 파일
"""
from __future__ import annotations

import argparse
import json
import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import graphio as G

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=date.today().isoformat())
    today = date.fromisoformat(ap.parse_args().today)
    g = G.load()
    R = defaultdict(list)

    for sid, a in g.nodes(data=True):
        if a.get("type") != "Stage":
            continue
        dates = {}
        for u, _, k, e in g.in_edges(sid, keys=True, data=True):
            if k == "DESCRIBES" and e.get("date") and e["date"].get("hi"):
                dates[u] = (e["date"].get("lo"), e["date"].get("hi"))
        if len(set(dates.values())) > 1:
            R["1. 같은 단계, 다른 날짜"].append(f"{a['label']} ({sid}): " + "; ".join(f"{u} {v[0]}~{v[1]}" for u, v in dates.items()))
        for t in G.out(g, sid, "OVERRIDES"):
            R["2. 학과 마감이 본부와 다름(학과 우선)"].append(f"{a['label']}: 학과 {G.period(a)} / 본부 {G.period(g.nodes[t])}")
        if a.get("tentative"):
            R["5. 예정·변동 가능 날짜"].append(f"{a['term']} {a['label']}: {G.period(a)}")
        if not a.get("hi") and not a.get("lo") and a["term"] == "2026-2":
            R["4-1. 날짜 없는 단계 (2026-2)"].append(f"{a['label']} ({a['scope']})")

    vf = ROOT / "data/extracted/_verify.json"
    if vf.exists():
        for nid, v in json.loads(vf.read_text(encoding="utf-8")).items():
            for pr in v["problems"]:
                R["0. 검증 실패 (원문 자체 오류 가능 → 학과에 확인, 위키에는 [확인 필요])"].append(f"{nid}: {pr}")

    phones = defaultdict(set)
    for n, a in g.nodes(data=True):
        if a.get("type") == "Contact" and a.get("phone"):
            phones[(a["topic"], a["college"])].add((a["phone"], ", ".join(G.inn(g, n, "DEFINES"))))
    for (topic, col), v in phones.items():
        if len({p for p, _ in v}) > 1:
            R["3. 문의처 번호 충돌"].append(f"{topic} · {g.nodes.get(col, {}).get('label', col)}: " + " / ".join(f"{p} ({src})" for p, src in sorted(v)))

    for rid in G.out(g, "tmpl:grad", "HAS_STAGE_RULE"):
        rule = g.nodes[rid].get("rule") or ""
        m = re.search(r"2학기 (\d+)월", rule)
        if not m:
            continue
        for t in ("2026-2",):
            sid = f"stage:{t}:{g.nodes[rid]['key']}"
            if sid in g and g.nodes[sid].get("lo") and int(g.nodes[sid]["lo"][5:7]) != int(m.group(1)):
                R["4. 고정 안내 시기와 실제 날짜가 다름(학기 공지 우선)"].append(
                    f"{g.nodes[sid]['label']}: 고정 안내 '{rule}' / {t} 공지 {G.period(g.nodes[sid])}")

    fq = list(csv.DictReader((ROOT / "data/graph/fetch_queue.csv").open(encoding="utf-8-sig")))
    done = {n for n, a in g.nodes(data=True) if a.get("body") == "extracted"}
    waiting = defaultdict(int)
    for x in fq:
        if x["rep"] not in done:
            waiting[(x["term"], x["kind"])] += 1
    R["6. 본문 수집·추출 대기 (대표 공지)"] = [f"{t} {k}: {n}건" for (t, k), n in sorted(waiting.items())]

    for n, a in g.nodes(data=True):
        if a.get("type") == "Procedure" and a.get("valid_until") and date.fromisoformat(a["valid_until"]) < today and a.get("scope") == "본부":
            R["7. 유효기간 지난 절차 (SNOWCHAT에서 끄기)"].append(f"{a['label']} (~{a['valid_until']})")

    lines = [f"# 린트 결과 ({today})", ""]
    for k in sorted(R):
        lines += [f"## {k} — {len(R[k])}건", ""] + [f"- {x}" for x in R[k]] + [""]
    (ROOT / "wiki/lint_report.md").write_text("\n".join(lines), encoding="utf-8")
    for k in sorted(R):
        print(f"{k}: {len(R[k])}건")
        for x in R[k][:3]:
            print("   ", x)


if __name__ == "__main__":
    main()
