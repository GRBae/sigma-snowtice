"""
그래프 → 화면·챗봇용 JSON. 웹 API(main.py)와 SNOWCHAT용 md 생성(pipeline/agent_cards.py)이 같이 쓴다.
원칙: 날짜 비교·자격 판정은 여기(코드)에서 끝내고, LLM에는 결과만 넘긴다.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import graphio as G  # noqa: E402
from query import kleene  # noqa: E402

DEFAULT_TERM = "2026-2"


class Graph:
    """메모리에 올린 그래프 하나. reload()로 갈아 끼운다 (요청 중에도 안전하게 통째로 교체)."""

    def __init__(self):
        self.g: nx.MultiDiGraph = G.load()
        self.loaded_at = date.today().isoformat()

    def reload(self):
        new = G.load()
        self.g, self.loaded_at = new, date.today().isoformat()
        return self.stats()

    def stats(self):
        g = self.g
        types: dict[str, int] = {}
        for _, a in g.nodes(data=True):
            types[a.get("type", "?")] = types.get(a.get("type", "?"), 0) + 1
        stages = [a for _, a in g.nodes(data=True) if a.get("type") == "Stage"]
        return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(), "types": types,
                "stages": len(stages), "dated_stages": sum(1 for a in stages if a.get("hi") or a.get("lo")),
                "loaded_at": self.loaded_at}


# ---------- 작은 도우미 ----------
def label(g, n):
    return g.nodes[n].get("label") or g.nodes[n].get("title") or n if n in g else n


def sources(g, sid):
    out = []
    for u, _, k, e in g.in_edges(sid, keys=True, data=True):
        if k in ("DESCRIBES", "MENTIONS") and g.nodes[u].get("type") == "Notice":
            a = g.nodes[u]
            out.append({"notice_id": u, "title": a.get("title"), "url": a.get("url"), "posted": a.get("posted"),
                        "evidence": e.get("evidence") or [], "verified": e.get("verified"), "pending": bool(e.get("pending"))})
    return sorted(out, key=lambda x: x["posted"] or "", reverse=True)


def d_day(a, today):
    hi = G.as_date(a.get("hi"))
    return (hi - today).days if hi else None


def stage_card(g, sid, today, overridden_central=None):
    a = g.nodes[sid]
    route = a.get("route")
    return {
        "stage_id": sid, "key": a.get("key"), "label": a.get("label"), "scope": a.get("scope"), "term": a.get("term"),
        "lo": a.get("lo"), "hi": a.get("hi"), "precision": a.get("precision"), "tentative": bool(a.get("tentative")),
        "verified": a.get("verified"), "period": G.period(a), "status": G.status(a, today), "d_day": d_day(a, today),
        "required": a.get("required"), "target": a.get("target"), "place": a.get("place"),
        "route": {"id": route, "label": label(g, route)} if route else None, "documents": a.get("documents", []),
        "overrides_central": ({"stage_id": overridden_central, "period": G.period(g.nodes[overridden_central])}
                              if overridden_central else None),
        "sources": sources(g, sid),
    }


def depts(g):
    out = []
    for n, a in g.nodes(data=True):
        if a.get("type") == "Dept":
            code = n.split(":", 1)[1]
            out.append({"code": code, "name": a.get("label"), "field": a.get("field"),
                        "has_dept_schedule": f"proc:grad:{DEFAULT_TERM}:{code}" in g})
    return sorted(out, key=lambda x: x["name"] or "")


# ---------- 1) 내 할 일 (공지함·신청 가능·Agent B '뭐 남았어?') ----------
def todo(g, dept, today, term=DEFAULT_TERM, enroll_status=None, admission_year=None, advisor=None, include_closed=False):
    prof = {"enroll_status": enroll_status, "admission_year": admission_year, "dept": f"dept:{dept}"}
    central = G.out(g, f"proc:grad:{term}", "HAS_STAGE")
    dp = f"proc:grad:{term}:{dept}"
    dst = G.out(g, dp, "HAS_STAGE") if dp in g else []
    over = {}
    for s in dst:
        for t in G.out(g, s, "OVERRIDES"):
            over[t] = s
    items, advisor_items, hidden = [], [], []
    for s in [x for x in central if x not in over] + dst:
        a = g.nodes[s]
        tgt = a.get("target") or ""
        if enroll_status == "재학" and "수료생" in tgt and not any(w in tgt for w in ("재학", "졸업예정자")):
            hidden.append({"label": a["label"], "why": "수료생 대상"}); continue
        if "2001~2019학번" in tgt and admission_year and not 2001 <= admission_year <= 2019:
            hidden.append({"label": a["label"], "why": "2001~2019학번 대상"}); continue
        if tgt.endswith("교수 지도 학생"):
            if not advisor:
                if include_closed or G.status(a, today) != "마감":
                    advisor_items.append(s)
                continue
            if advisor not in tgt:
                continue
        overridden = next((c for c, d in over.items() if d == s), None)
        card = stage_card(g, s, today, overridden)
        if card["status"] == "마감" and not include_closed:
            continue
        items.append(card)
    items.sort(key=lambda c: (c["hi"] or c["lo"] or "9999", c["label"]))
    rules = {r: kleene(g.nodes[r]["tree"], prof) for r in
             G.out(g, "tmpl:grad", "ELIGIBLE_IF") + (G.out(g, dp, "ELIGIBLE_IF") if dp in g else [])}
    cautions = [{"id": c, "text": label(g, c)} for p in (f"proc:grad:{term}", dp) if p in g for c in G.out(g, p, "HAS_CAUTION")]
    contacts = []
    colleges = G.out(g, f"dept:{dept}", "IN_COLLEGE")
    for c in G.out(g, f"proc:grad:{term}", "CONTACT_FOR"):
        a = g.nodes[c]
        if a.get("college") == f"dept:{dept}" or a.get("college") in colleges:
            off = a.get("office")
            contacts.append({"topic": a["topic"], "office": label(g, off) if off in g else off, "phone": a.get("phone")})
    return {
        "dept": {"code": dept, "name": label(g, f"dept:{dept}")}, "term": term, "today": today.isoformat(),
        "has_dept_schedule": dp in g,
        "items": items,
        "advisor_specific": ({"count": len(advisor_items), "advisors_in_notices": sorted({g.nodes[s]["target"].replace(" 교수 지도 학생", "") for s in advisor_items}),
                              "hint": "지도교수를 advisor로 넘기면 그 교수님 일정만 돌려줌"} if advisor_items else None),
        "hidden_for_profile": hidden,
        "eligibility": rules,
        "cautions": cautions, "contacts": contacts,
        "note": None if dp in g else "이 학과의 학과 자체 공지는 아직 추출되지 않아 본부 일정만 보여줌",
    }


# ---------- 2) 마감 임박 (매일 12:00 알림·Agent B '이번 주 마감') ----------
def deadlines(g, today, days=14, dept=None):
    end = today + timedelta(days=days)
    out = []
    for s, a in g.nodes(data=True):
        if a.get("type") != "Stage" or not a.get("hi"):
            continue
        if dept and a["scope"] not in ("본부", dept):
            continue
        if dept and a["scope"] == "본부" and any(
                g.nodes[u].get("scope") == dept for u, _, k in g.in_edges(s, keys=True) if k == "OVERRIDES"):
            continue  # 학과가 이 본부 단계를 자기 마감으로 덮어썼으면 학과 것만
        hi = G.as_date(a["hi"])
        if today <= hi <= end:
            c = stage_card(g, s, today)
            c["dept_name"] = "본부(전체)" if a["scope"] == "본부" else label(g, f"dept:{a['scope']}")
            out.append(c)
    return {"today": today.isoformat(), "days": days, "dept": dept, "items": sorted(out, key=lambda c: c["hi"])}


# ---------- 3) 관심사 그래프 (PPR + 추천 경로) ----------
W = {"HAS_STAGE": 1.0, "PRECEDES": 0.8, "PART_OF": 1.0, "DESCRIBES": 0.6, "MENTIONS": 0.3, "ELIGIBLE_IF": 0.5,
     "HAS_CAUTION": 0.5, "OVERRIDES": 0.8, "IN_INTEREST": 1.0, "INSTANCE_OF": 0.7, "ISSUED_BY": 0.3, "CONTACT_FOR": 0.3}


def _undirected(g):
    H = nx.Graph()
    for u, v, k in g.edges(keys=True):
        if k in W:
            H.add_edge(u, v, weight=max(W[k], H[u][v]["weight"] if H.has_edge(u, v) else 0), type=k)
    # 허브 억제: 차수가 큰 노드(본부 절차·템플릿)는 전이 가중치를 낮춘다 (HippoRAG node specificity)
    for n in H.nodes:
        deg = H.degree(n)
        if deg > 40:
            for nb in H[n]:
                H[n][nb]["weight"] /= (deg / 40)
    return H


def graph_view(g, seed, today, k=25, types=("Stage", "Notice", "Caution", "Procedure")):
    if seed not in g:
        raise KeyError(seed)
    H = _undirected(g)
    if seed not in H:
        return {"seed": seed, "nodes": [], "edges": []}
    pr = nx.pagerank(H, alpha=0.75, personalization={seed: 1.0}, weight="weight")
    ranked = [n for n, _ in sorted(pr.items(), key=lambda x: -x[1]) if g.nodes[n].get("type") in types and n != seed]
    keep = [seed] + ranked[:k]
    nodes = []
    for n in keep:
        a = g.nodes[n]
        try:
            path = nx.shortest_path(H, seed, n, weight=lambda u, v, d: 1 / d["weight"])
        except nx.NetworkXNoPath:
            path = [n]
        nodes.append({"id": n, "type": a.get("type"), "label": label(g, n), "score": round(pr.get(n, 0), 5),
                      "status": G.status(a, today) if a.get("type") == "Stage" else None,
                      "url": a.get("url"), "why": " → ".join(label(g, p) for p in path)})
    ks = set(keep)
    edges = [{"src": u, "dst": v, "type": t} for u, v, t in g.edges(keys=True) if u in ks and v in ks]
    return {"seed": {"id": seed, "label": label(g, seed)}, "nodes": nodes, "edges": edges}


# ---------- 4) 공지 목록·인기 ----------
def notices(g, dept=None, term=None, q=None, only_rep=True, limit=50):
    out = []
    for n, a in g.nodes(data=True):
        if a.get("type") != "Notice":
            continue
        if only_rep and G.out(g, n, "DUPLICATE_OF"):
            continue
        src = n.split(":")[1]
        if dept and src not in (dept, "main"):
            continue
        if term and a.get("term") != term:
            continue
        if q and q not in (a.get("title") or ""):
            continue
        dup = len(G.inn(g, n, "DUPLICATE_OF"))
        out.append({"notice_id": n, "title": a.get("title"), "posted": a.get("posted"), "term": a.get("term"),
                    "board": "대표 홈페이지" if src == "main" else label(g, f"dept:{src}"), "url": a.get("url"),
                    "hits": int(a["hits"]) if str(a.get("hits") or "").isdigit() else None,
                    "body": a.get("body"), "reposts": dup,
                    "stages": [label(g, s) for s in G.out(g, n, "DESCRIBES") + G.out(g, n, "MENTIONS")
                               if g.nodes[s].get("type") == "Stage"]})
    return sorted(out, key=lambda x: x["posted"] or "", reverse=True)[:limit]


def popular(g, limit=10, term=None):
    xs = [x for x in notices(g, term=term, limit=10_000) if x["hits"]]
    return sorted(xs, key=lambda x: -x["hits"])[:limit]


# ---------- 5) 근거 카드 (SNOWCHAT Agent B에 넘길 텍스트) ----------
def todo_card_text(res) -> str:
    """todo() 결과를 LLM이 그대로 옮겨 쓰기 좋은 근거 카드로. 여기에 없는 날짜는 말하지 말라는 규칙과 함께 쓴다."""
    L = [f"[근거 카드] {res['dept']['name']} · {res['term']} 졸업 · 기준일 {res['today']}"]
    if res["note"]:
        L.append(f"- 주의: {res['note']}")
    for c in res["items"]:
        extra = []
        if c["overrides_central"]:
            extra.append(f"본부 기간({c['overrides_central']['period']})보다 학과 마감 우선")
        if c["place"]:
            extra.append(f"장소/방법: {c['place']}")
        if c["route"]:
            extra.append(f"경로: {c['route']['label']}")
        if c["target"]:
            extra.append(f"대상: {c['target']}")
        src = c["sources"][0] if c["sources"] else None
        L.append(f"- {c['label']} | {c['period']} | {c['status']}" + (" | " + " · ".join(extra) if extra else "")
                 + (f" | 출처: {src['title']} {src['url']}" if src else ""))
    if res["advisor_specific"]:
        L.append(f"- 지도교수별 일정 {res['advisor_specific']['count']}건 있음 → 지도교수를 물어볼 것")
    for c in res["cautions"]:
        L.append(f"- 유의: {c['text']}")
    for c in res["contacts"]:
        L.append(f"- 문의({c['topic']}): {c['office']} {c['phone']}")
    return "\n".join(L)
