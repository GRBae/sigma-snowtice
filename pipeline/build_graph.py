"""
⑤ 그래프 만들기 — 원본은 이 그래프 하나다. 위키 md와 웹 API는 전부 여기서 나온다.

  python pipeline/build_graph.py

입력
  data/graph/notice_clusters.csv   ⓪ 제목 묶기 결과 (모든 공지 493건, 같은 글 묶음)
  data/raw/graduation_index_all.csv 공지 목록 메타 (학과·게시판·조회수)
  data/extracted/*.json + _verify.json  ③④ 추출·검증 결과 (본문을 읽은 공지)
  pipeline/entities.yaml           학과·부서·경로 사전
출력
  data/graph/graph_nodes.jsonl, graph_edges.jsonl  → load_mysql.py가 graph_node·graph_edge 표에 적재

ID 규칙
  notice:{source}:{no}  예) notice:main:94905, notice:math:146958, notice:static:graduate01
  dept:{code} · office:{code} · college:{code} · route:{code} · interest:{code} · term:{yyyy-s}
  proc:grad:{term}  (본부 절차)   proc:grad:{term}:{dept}  (학과 하위 절차, PART_OF 본부 절차)
  stage:{term}:{key}  (본부 단계) stage:{term}:{key}:{dept}  (학과 단계)
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import networkx as nx
import yaml

ROOT = Path(__file__).resolve().parent.parent
G_OUT = ROOT / "data/graph"
ENT = yaml.safe_load((ROOT / "pipeline/entities.yaml").read_text(encoding="utf-8"))

# 본부 절차의 단계 순서 (정렬·PRECEDES에 사용)
CENTRAL_ORDER = ["폭력예방교육", "졸업계획제출", "전공선택", "이수현황정리", "논문제신청", "수료생졸업신청", "논문제결과물제출",
                 "정보인증제등록", "교원자격검정", "인증제결과확인", "영문성명확인", "계속수학신청", "최종사정결과조회", "학위수여식"]
STAGE_NAME = {"폭력예방교육": "폭력예방교육 이수(졸업계획 제출 선행 요건)", "졸업계획제출": "졸업계획 제출(재학생 졸업신청)", "전공선택": "전공선택(희망자)",
              "이수현황정리": "졸업학점 이수현황 확인·과목 정리", "논문제신청": "졸업논문제 신청", "수료생졸업신청": "수료생 졸업신청",
              "논문제결과물제출": "졸업논문제 결과물 제출", "정보인증제등록": "정보인증제 등록", "교원자격검정": "교원자격무시험검정원서 제출(교직 이수자)",
              "인증제결과확인": "졸업인증제 합격여부 확인", "영문성명확인": "졸업예정자 영문성명 확인", "계속수학신청": "계속수학 신청",
              "최종사정결과조회": "최종 졸업심사결과 조회", "학위수여식": "학위수여식", "조기졸업신청": "조기졸업 신청"}
# ⓪ 제목 단계 유형 → 표준 단계 키
TYPE2KEYS = {"졸업계획제출": ["졸업계획제출", "전공선택"], "이수현황정리": ["이수현황정리"], "논문제신청": ["논문제신청"],
             "수료생졸업신청": ["수료생졸업신청"], "인증제제출": ["논문제결과물제출", "정보인증제등록"], "인증제결과": ["인증제결과확인"],
             "영문성명": ["영문성명확인"], "계속수학": ["계속수학신청"], "최종사정결과": ["최종사정결과조회"], "학위수여식": ["학위수여식"],
             "조기졸업": ["조기졸업신청"], "교원자격검정": ["교원자격검정"], "폭력예방교육": ["폭력예방교육"], "일정표": []}
DEPT_TYPES = {"졸업시험", "지도교수", "졸업작품·프로젝트", "대체시험·어학", "양식·규정", "논문제제출", "콜로키움", "학위증배부", "기타"}
PRECISION_RANK = {"minute": 5, "day": 4, "week": 3, "month": 2, "rule": 1, "tbd": 0}
TERM_END = {"2025-2": "2026-02-28", "2026-1": "2026-08-31", "2026-2": "2027-02-28", "2027-1": "2027-08-31"}


def code_of(host: str) -> str:
    return host.split(".")[0] if host else "unknown"


def main():
    g = nx.MultiDiGraph()
    node = lambda nid, typ, **a: g.add_node(nid, type=typ, **a)  # 이미 있으면 속성만 덧붙음
    edge = lambda s, t, typ, **a: g.add_edge(s, t, key=typ, type=typ, **a)

    # 0) 사전 엔티티
    for k, v in ENT["colleges"].items():
        node(k, "College", label=v)
    for k, v in ENT["depts"].items():
        node(k, "Dept", label=v["name"], field=v["field"], host=v["host"])
        edge(k, v["college"], "IN_COLLEGE")
    for k, v in ENT["offices"].items():
        node(k, "Office", label=v["name"])
    for k, v in ENT["routes"].items():
        node(k, "Route", label=v)
    for k, v in ENT["interests"].items():
        node(k, "Interest", label=v)
    for k, v in ENT["templates"].items():
        node(k, "Template", label=v)
        edge(k, "interest:grad-req", "IN_INTEREST")
    boards = {}  # (host, 게시판 이름) → (경로, 엔진)
    for k, v in ENT["depts"].items():
        for b in v["boards"]:
            p = b.split("|")
            if len(p) >= 3:
                boards[(v["host"], p[0])] = (p[1], p[2])

    # 1) 모든 공지 (⓪ 묶음 결과)
    meta = {}
    for r in csv.DictReader((ROOT / "data/raw/graduation_index_all.csv").open(encoding="utf-8-sig")):
        src = code_of(r["host"])
        meta[f"notice:{'main' if src == 'www' else src}:{r['id']}"] = r
    clusters = list(csv.DictReader((G_OUT / "notice_clusters.csv").open(encoding="utf-8-sig")))
    rep_of = {c["nid"]: c["rep"] for c in clusters}
    extracted = {}
    for f in sorted((ROOT / "data/extracted").glob("*.json")):
        if not f.name.startswith("_"):
            ex = json.loads(f.read_text(encoding="utf-8"))
            extracted[ex["notice"]["id"]] = ex
    verify = json.loads((ROOT / "data/extracted/_verify.json").read_text(encoding="utf-8"))

    def notice_url(nid, m):
        src, no = nid.split(":")[1:]
        if src == "main":
            return f"https://www.sookmyung.ac.kr/kr/news/important-notice.do?mode=view&articleNo={no}"
        path, eng = boards.get((m["host"], m["board"]), ("", ""))
        if eng.startswith("sm_cms"):
            return f"https://{m['host']}{path}?mode=view&articleNo={no}"
        if eng.startswith("k2web"):
            return f"https://{m['host']}{path.replace('artclList.do', '')}{no}/artclView.do"
        return f"https://{m['host']}{path}"  # 그누보드·KBoard 등: 게시판 주소까지만

    for c in clusters:
        nid, m = c["nid"], meta.get(c["nid"], {})
        src = nid.split(":")[1]
        dept_id = "office:comm" if src == "main" else f"dept:{src}"
        has_ex = nid in extracted
        node(nid, "Notice", title=c["title"], posted=c["posted"], term=c["term"], stage_type=c["stage"], hits=m.get("hits") or None,
             url=notice_url(nid, m) if m else None, cluster=c["cluster"],
             body="extracted" if has_ex else ("duplicate" if c["rep"] != nid else "pending"))
        edge(nid, dept_id, "POSTED_BY")
        if c["rep"] != nid:
            edge(nid, c["rep"], "DUPLICATE_OF", basis="제목+게시일+학기 유사도, H0 임계값")
    for nid, ex in extracted.items():  # 목록에 없던 공지(고정 안내 페이지 등)
        if nid not in g:
            n = ex["notice"]
            node(nid, "Notice", title=n["title"], posted=n.get("posted"), term=(ex.get("procedure") or {}).get("term"),
                 url=n["url"], body="extracted", stage_type="고정안내" if n["source"] == "static" else None)
            if n.get("posted_by"):
                edge(nid, n["posted_by"], "POSTED_BY")
        if ex.get("issued_by"):
            edge(nid, ex["issued_by"], "ISSUED_BY")
        for r in ex.get("refers_to", []):
            if r in g:
                edge(nid, r, "REFERS_TO")

    # 2) 학기·절차
    terms = sorted({c["term"] for c in clusters if c["term"] != "?"})
    for t in terms:
        node(f"term:{t}", "Term", label=t, ends=TERM_END.get(t))
        for tmpl, pid in (("tmpl:grad", f"proc:grad:{t}"), ("tmpl:early-grad", f"proc:early-grad:{t}")):
            node(pid, "Procedure", term=t, scope="본부", template=tmpl, valid_until=TERM_END.get(t),
                 label=f"{t} {ENT['templates'][tmpl]}")
            edge(pid, tmpl, "INSTANCE_OF")
            edge(pid, f"term:{t}", "IN_TERM")
            edge(pid, "office:haksa", "ISSUED_BY")

    def dept_proc(t, dcode):
        pid = f"proc:grad:{t}:{dcode}"
        if pid not in g:
            node(pid, "Procedure", term=t, scope=dcode, template="tmpl:grad", valid_until=TERM_END.get(t),
                 label=f"{t} 학부 정기졸업 — {ENT['depts'].get('dept:' + dcode, {}).get('name', dcode)}")
            edge(pid, f"proc:grad:{t}", "PART_OF")
            edge(pid, f"dept:{dcode}", "ISSUED_BY")
            edge(pid, f"term:{t}", "IN_TERM")
        return pid

    def stage(t, key, dcode=None, name=None):
        sid = f"stage:{t}:{key}" + (f":{dcode}" if dcode else "")
        if sid not in g:
            node(sid, "Stage", key=key, term=t, scope=dcode or "본부", label=name or STAGE_NAME.get(key, key),
                 lo=None, hi=None, precision="tbd", date_sources=[], verified=None)
            proc = (f"proc:early-grad:{t}" if key == "조기졸업신청" else f"proc:grad:{t}") if not dcode else dept_proc(t, dcode)
            order = CENTRAL_ORDER.index(key) if key in CENTRAL_ORDER else 50
            edge(proc, sid, "HAS_STAGE", order=order)
        return sid

    # 3) 추출된 단계 → 날짜 채우기 (여러 공지가 같은 단계를 말하면 더 구체적인 값 채택)
    for nid, ex in extracted.items():
        proc_info = ex.get("procedure") or {}
        t = proc_info.get("term")
        for s in ex["stages"]:
            t = s.get("term") or proc_info.get("term")  # 한 공지가 다음 학기 단계도 말하는 경우
            dcode = None if s["scope"] == "본부" else s["scope"]
            ok = verify.get(nid, {}).get("stages", {}).get(s["key"], False)
            if t is None:  # 학기 무관 규칙(고정 안내) → 템플릿에 규칙으로
                rid = f"tmplstage:{s['key']}"
                node(rid, "StageRule", key=s["key"], rule=s["date"].get("rule") if s.get("date") else None, evidence=s["evidence"])
                edge(proc_info.get("template", "tmpl:grad"), rid, "HAS_STAGE_RULE")
                edge(nid, rid, "DESCRIBES")
                continue
            sid = stage(t, s["key"], dcode, s.get("name"))
            a = g.nodes[sid]
            edge(nid, sid, "DESCRIBES" if s.get("date") else "MENTIONS", evidence=s["evidence"], verified=ok, date=s.get("date"))
            for k in ("route", "place", "target", "required"):
                if s.get(k) is not None and a.get(k) is None:
                    a[k] = s[k]
            if s.get("documents"):
                a["documents"] = sorted(set(a.get("documents", []) + s["documents"]))
            if s.get("requires"):
                a["requires"] = sorted(set(a.get("requires", []) + s["requires"]))
            if s.get("route"):
                edge(sid, s["route"], "VIA")
            d = s.get("date")
            if d:
                rank_new = (PRECISION_RANK.get(d["precision"], 0), not d.get("tentative", False), ok, ex["notice"].get("posted") or "")
                rank_old = (PRECISION_RANK.get(a["precision"], 0), not a.get("tentative", False), bool(a.get("verified")), a.get("date_posted") or "")  # 같으면 나중 공지가 이김
                a["date_sources"] = a["date_sources"] + [nid]
                if rank_new > rank_old:
                    a.update(lo=d.get("lo"), hi=d.get("hi"), precision=d["precision"], tentative=d.get("tentative", False),
                             year_inferred=d.get("year_inferred", False), verified=ok, date_from=nid, date_posted=ex["notice"].get("posted") or "")
            if dcode and s.get("overrides") == "본부":
                edge(sid, stage(t, s["key"]), "OVERRIDES")
        for r in ex["rules"]:
            node(r["id"], "Rule", tree=r["tree"], evidence=r.get("evidence"), subjects=r.get("subjects"), exemption=r.get("exemption"),
                 lookup_tables=r.get("lookup_tables"))
            tgt = {"tmpl:grad": "tmpl:grad", "proc:early-grad:2026-2": "proc:early-grad:2026-2",
                   "proc:math-thesis:2026-2": dept_proc("2026-2", "math"), "stg:grad:2026-2:04": stage("2026-2", "논문제신청")}.get(r["applies_to"], r["applies_to"])
            edge(tgt, r["id"], "ELIGIBLE_IF")
            edge(nid, r["id"], "DEFINES")
        for c in ex["cautions"]:
            node(c["id"], "Caution", label=c["text"], evidence=c["evidence"])
            owner = "tmpl:grad" if nid.startswith("notice:static") else (dept_proc(t, proc_info["scope"]) if proc_info.get("scope") not in (None, "본부") else f"proc:grad:{t}")
            edge(owner, c["id"], "HAS_CAUTION")
            edge(nid, c["id"], "DEFINES")
        for o in ex["outcomes"]:
            node(o["id"], "Outcome", label=o["name"], rule_text=o["rule_text"])
            edge("tmpl:grad", o["id"], "HAS_OUTCOME")
        for i, c in enumerate(ex["contacts"]):
            cid = f"contact:{c['topic']}:{c['college']}:{c['phone'] or c['office']}"
            node(cid, "Contact", topic=c["topic"], college=c["college"], office=c["office"], phone=c["phone"])
            edge(nid, cid, "DEFINES", evidence=c["evidence"])
            edge(f"proc:grad:{t}" if t else "tmpl:grad", cid, "CONTACT_FOR")

    # 4) 본문 전 공지(대표 공지) → 제목 단계 유형으로 단계에 연결 (날짜는 비어 있음)
    for c in clusters:
        nid = c["nid"]
        if c["rep"] != nid or nid in extracted or c["term"] == "?" or c["stage"] == "대학원":
            continue
        t, st = c["term"], c["stage"]
        dcode = None if nid.startswith("notice:main") else nid.split(":")[1]
        if st in TYPE2KEYS:
            keys = TYPE2KEYS[st]
            if not keys:  # 일정표 → 절차 전체를 설명
                edge(nid, f"proc:grad:{t}", "DESCRIBES", pending=True)
            for k in keys:
                edge(nid, stage(t, k), "DESCRIBES", pending=True)
        else:
            edge(nid, stage(t, st, dcode or "unknown"), "DESCRIBES", pending=True)

    # 5) 단계 순서 (본부)
    for t in terms:
        seq = [f"stage:{t}:{k}" for k in CENTRAL_ORDER if f"stage:{t}:{k}" in g]
        for a, b in zip(seq, seq[1:]):
            edge(a, b, "PRECEDES")
        if f"stage:{t}:조기졸업신청" in g and f"stage:{t}:졸업계획제출" in g:
            edge(f"stage:{t}:조기졸업신청", f"stage:{t}:졸업계획제출", "PRECEDES")
    # 학과 단계는 학과 절차 안에서 날짜순, 마지막은 본부 '논문제결과물제출'로 이어짐
    for pid, a in list(g.nodes(data=True)):
        if a.get("type") == "Procedure" and a.get("scope") not in ("본부", None):
            st = [v for _, v, k in g.out_edges(pid, keys=True) if k == "HAS_STAGE"]
            st.sort(key=lambda s: (g.nodes[s].get("hi") or "9999", s))
            for x, y in zip(st, st[1:]):
                edge(x, y, "PRECEDES")
            tgt = f"stage:{a['term']}:논문제결과물제출"
            if st and tgt in g and not any(k == "OVERRIDES" for _, _, k in g.out_edges(st[-1], keys=True)):
                edge(st[-1], tgt, "PRECEDES")

    # 6) 저장
    G_OUT.mkdir(parents=True, exist_ok=True)
    with (G_OUT / "graph_nodes.jsonl").open("w", encoding="utf-8") as f:
        for n, a in g.nodes(data=True):
            f.write(json.dumps({"id": n, **a}, ensure_ascii=False, default=str) + "\n")
    with (G_OUT / "graph_edges.jsonl").open("w", encoding="utf-8") as f:
        for u, v, k, a in g.edges(keys=True, data=True):
            f.write(json.dumps({"src": u, "dst": v, **a}, ensure_ascii=False, default=str) + "\n")
    cnt = defaultdict(int)
    for _, a in g.nodes(data=True):
        cnt[a.get("type")] += 1
    ecnt = defaultdict(int)
    for *_, k in g.edges(keys=True):
        ecnt[k] += 1
    dated = sum(1 for _, a in g.nodes(data=True) if a.get("type") == "Stage" and a.get("hi"))
    stages = sum(1 for _, a in g.nodes(data=True) if a.get("type") == "Stage")
    print(f"노드 {g.number_of_nodes()}개: {dict(cnt)}")
    print(f"간선 {g.number_of_edges()}개: {dict(ecnt)}")
    print(f"단계 {stages}개 중 날짜 채워진 것 {dated}개 (나머지는 본문 추출 대기)")
    missing = [n for n, a in g.nodes(data=True) if "type" not in a]
    print("정의 안 된 노드:", missing[:10] or "없음")


if __name__ == "__main__":
    main()
