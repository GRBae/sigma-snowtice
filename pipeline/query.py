"""
그래프 질의 — 웹 API와 SNOWCHAT Agent B(개인화·집계·관계)가 부르는 함수. 위키를 쓰지 않는다.

  python pipeline/query.py   # 예시 실행 (가상 페르소나)

  todo(dept, profile, today)        "나 2월 졸업인데 뭐 해야 해?"   본부+학과 단계 합치기(학과 우선) + 자격 3값 판정
  deadlines(today, days, dept)      "다음 2주 안에 마감되는 거?"    날짜 구간 필터
  related(seed, k)                  "졸업시험이랑 엮인 일정?"       Personalized PageRank + 경로 설명
"""
from __future__ import annotations

from datetime import date, timedelta

import networkx as nx

import graphio as G

T, F, U = "T", "F", "U"


def kleene(tree, prof):
    if "AND" in tree:
        v = [kleene(x, prof) for x in tree["AND"]]
        return F if F in v else (U if U in v else T)
    if "OR" in tree:
        v = [kleene(x, prof) for x in tree["OR"]]
        return T if T in v else (U if U in v else F)
    if tree.get("attr") == "other" or prof.get(tree["attr"]) is None or isinstance(tree.get("value"), dict):
        return U
    x, v, op = prof[tree["attr"]], tree["value"], tree["op"]
    ok = {"==": lambda: x == v, ">=": lambda: x >= v, "<=": lambda: x <= v, "in": lambda: x in v,
          "between": lambda: v[0] <= x <= v[1]}[op]()
    return T if ok else F


def todo(g, term, dept, prof, today):
    central = G.out(g, f"proc:grad:{term}", "HAS_STAGE")
    dp = f"proc:grad:{term}:{dept}"
    dst = G.out(g, dp, "HAS_STAGE") if dp in g else []
    over = {t for s in dst for t in G.out(g, s, "OVERRIDES")}
    rules = {r: kleene(g.nodes[r]["tree"], prof) for r in G.out(g, "tmpl:grad", "ELIGIBLE_IF") + (G.out(g, dp, "ELIGIBLE_IF") if dp in g else [])}
    rows, advisor_rows = [], []
    for s in [x for x in central if x not in over] + dst:
        a = g.nodes[s]
        tgt = a.get("target") or ""
        if prof.get("enroll_status") == "재학" and "수료생" in tgt and not any(w in tgt for w in ("재학", "졸업예정자")):
            continue
        if "2001~2019학번" in tgt and prof.get("admission_year") and not 2001 <= prof["admission_year"] <= 2019:
            continue
        st = G.status(a, today)
        if st == "마감":
            continue
        if tgt.endswith("교수 지도 학생"):  # 지도교수별 일정: 내 지도교수 것만
            adv = prof.get("advisor")
            if not adv:
                advisor_rows.append(s)
                continue
            if adv not in tgt:
                continue
        rows.append((a.get("hi") or "9999", a["label"], G.period(a), st, s))
    if advisor_rows:
        rows.append(("0000", f"지도교수별 논문 지도 일정 {len(advisor_rows)}건 — 지도교수를 알려주면 내 일정만 골라 줌", "", "확인 필요", "advisor"))
    return rules, sorted(rows)


def deadlines(g, today, days=14, dept=None):
    end = today + timedelta(days=days)
    out = []
    for s, a in g.nodes(data=True):
        if a.get("type") != "Stage" or not a.get("hi"):
            continue
        if dept and a["scope"] not in ("본부", dept):  # dept=None 이면 전체 학과
            continue
        hi = G.as_date(a["hi"])
        if today <= hi <= end:
            out.append((a["hi"], a["label"], a["scope"]))
    return sorted(out)


def related(g, seed, k=6):
    w = {"HAS_STAGE": 1.0, "PRECEDES": 0.8, "PART_OF": 1.0, "DESCRIBES": 0.6, "ELIGIBLE_IF": 0.5, "HAS_CAUTION": 0.5, "OVERRIDES": 0.8}
    H = nx.Graph()
    for u, v, key in g.edges(keys=True):
        if key in w:
            H.add_edge(u, v, weight=max(w[key], H[u][v]["weight"] if H.has_edge(u, v) else 0))
    pr = nx.pagerank(H, alpha=0.75, personalization={seed: 1.0}, weight="weight")
    res = []
    for n, s in sorted(pr.items(), key=lambda x: -x[1]):
        if n != seed and g.nodes[n].get("type") == "Stage" and g.nodes[n].get("hi"):
            res.append((round(s, 3), g.nodes[n]["label"], " → ".join(g.nodes[p].get("label", p)[:12] for p in nx.shortest_path(H, seed, n))))
        if len(res) == k:
            break
    return res


if __name__ == "__main__":
    g = G.load()
    today = date(2026, 11, 24)
    prof = {"enroll_status": "재학", "semesters_registered": 8, "admission_year": 2022, "dept": "dept:math", "gpa_total": None}  # 가상 데이터
    rules, rows = todo(g, "2026-2", "math", prof, today)
    print("[todo] 수학과 8학기 재학생(가상) — 자격:", rules)
    for r in rows:
        print("  ", r[3], r[1], r[2])
    print("\n[todo] 신소재물리학부 8학기 재학생(가상)")
    for r in todo(g, "2026-2", "physics", {**prof, "dept": "dept:physics"}, today)[1][:4]:
        print("  ", r[3], r[1], r[2])
    print("\n[deadlines] 2주 안 (수학과):", deadlines(g, today, 14, "math"))
    print("\n[related] 수학과 2026-2 절차에서:")
    for r in related(g, "proc:grad:2026-2:math"):
        print("  ", r)
