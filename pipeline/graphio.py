"""그래프 읽기 도우미 (render·lint·query가 같이 쓴다). 운영에서는 MySQL graph_node·graph_edge에서 읽도록 바꾼다."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
WD = "월화수목금토일"


def load() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for line in (ROOT / "data/graph/graph_nodes.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        g.add_node(d.pop("id"), **d)
    for line in (ROOT / "data/graph/graph_edges.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        g.add_edge(d.pop("src"), d.pop("dst"), key=d["type"], **d)
    return g


def out(g, n, typ):
    return [v for _, v, k in g.out_edges(n, keys=True) if k == typ]


def inn(g, n, typ):
    return [u for u, _, k in g.in_edges(n, keys=True) if k == typ]


def as_date(s: str | None) -> date | None:
    return datetime.fromisoformat(s).date() if s else None


def fmt_dt(s: str) -> str:
    d = datetime.fromisoformat(s)
    t = f" {d:%H:%M}" if "T" in s else ""
    return f"{d:%Y-%m-%d}({WD[d.weekday()]}){t}"


def period(a: dict) -> str:
    lo, hi = a.get("lo"), a.get("hi")
    if not lo and not hi:
        return "일정 미정 [확인 필요]"
    if lo and hi and lo == hi:
        txt = fmt_dt(lo)
    elif lo and hi and lo[:10] == hi[:10] and "T" in lo:
        txt = f"{fmt_dt(lo)}~{hi[11:16]}"
    elif lo and hi:
        txt = f"{fmt_dt(lo)} ~ {fmt_dt(hi)}"
    else:
        txt = ("~ " + fmt_dt(hi)) if hi else (fmt_dt(lo) + " ~")
    if a.get("precision") == "week":
        txt += " 이내(주 단위)"
    if a.get("tentative"):
        txt += " (예정·변동 가능)"
    if a.get("verified") is False:
        txt += " [확인 필요]"
    return txt


def status(a: dict, today: date) -> str:
    lo, hi = as_date(a.get("lo")), as_date(a.get("hi"))
    if not hi and not lo:
        return "일정 미정"
    if hi and hi < today:
        return "마감"
    if lo and lo <= today:
        return f"진행 중(D-{(hi - today).days})" if hi else "진행 중"
    return f"예정(D-{(hi - today).days})" if hi else "예정"
