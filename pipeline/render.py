"""
⑥ 위키 md 생성 — 그래프에서 템플릿으로 찍는다. 사람이나 LLM이 페이지 본문을 직접 쓰지 않는다.

  python pipeline/render.py [--today 2026-11-24]

만드는 파일 (SNOWCHAT 지식 파일, 절차 단위로 하나씩)
  wiki/pages/절차_{학기}_졸업_공통.md        본부 절차
  wiki/pages/절차_{학기}_졸업_{학과}.md      본부 절차 + 학과 단계 (학과 마감이 더 빠르면 학과 값)
  wiki/pages/절차_{학기}_조기졸업.md
  wiki/pages/규정_졸업_공통.md              학기 무관 자격·결과·유의사항
  wiki/index.md, wiki/log.md
유효기간(valid_until)이 지난 학기는 만들지 않고 index.md의 'SNOWCHAT에서 끌 파일'에 올린다.

LLM이 쓰는 곳은 '한눈에 보기' 요약 2~3줄뿐이다 (summarize()). LLM 설정 전에는 코드 요약을 쓴다.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import graphio as G

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "wiki/pages"
env = Environment(loader=FileSystemLoader(ROOT / "templates"), trim_blocks=False, lstrip_blocks=False)
ATTR = {"semesters_registered": "등록 학기", "enroll_status": "학적 상태", "admission_year": "학번(입학연도)", "gpa_total": "총 평점평균",
        "gpa_each_term": "매 정규학기 평점평균", "cert_thesis_passed": "졸업논문제 합격", "cert_info_passed": "정보인증제 합격", "dept": "학과",
        "second_major": "복수전공", "credits_completed": "이수 학점", "transfer_type": "편입 구분", "bs_ms_track": "학·석사연계과정"}
OPS = {">=": "이상", "<=": "이하", "==": "", "in": "중 하나", "between": "사이"}


def summarize(ctx: dict) -> str | None:
    """LLM 요약 자리. extract.py와 같은 LLM 설정이 정해지면 여기서 호출한다 (입력: 단계 목록 텍스트, 출력: 2~3줄)."""
    return None


def code_summary(stages, today, dept_name=None):
    upcoming = [s for s in stages if s["status"].startswith(("예정", "진행"))]
    done = sum(1 for s in stages if s["status"] == "마감")
    head = f"{'본부 일정에 ' + dept_name + ' 학과 일정을 합친' if dept_name else '교무처 학사팀이 안내한'} 단계 {len(stages)}개 중 {done}개는 마감됐고 {len(upcoming)}개가 남았어요."
    if upcoming:
        nxt = min(upcoming, key=lambda s: s["_hi"] or "9999")
        head += f" 가장 가까운 일정은 '{nxt['name']}'({nxt['period']})예요."
    return head + " (코드 요약)"


def notice_label(g, nid):
    src = nid.split(":")[1]
    return "대표 홈페이지" if src == "main" else ("고정 안내" if src == "static" else g.nodes.get(f"dept:{src}", {}).get("label", src))


def stage_rows(g, sids, today, override_note=True):
    rows = []
    for sid in sids:
        a = g.nodes[sid]
        srcs = sorted(set(a.get("date_sources") or []) | {u for u in G.inn(g, sid, "DESCRIBES") if g.nodes[u].get("body") == "extracted"})
        note = ""
        if override_note:
            ov = G.out(g, sid, "OVERRIDES")
            if ov:
                note = f"본부 기간({G.period(g.nodes[ov[0]])})보다 학과 마감이 우선"
        tgt = a.get("target") or ""
        req = a.get("required")
        name = a["label"]
        if "2001~2019학번" in tgt:
            name += " [2001~2019학번만]"
            req = None
        elif "수료생" in tgt and not any(w in tgt for w in ("재학", "졸업예정자")):
            name += " [수료생만]"
            req = None
        rows.append({"name": name, "required": req, "period": G.period(a), "place": a.get("place"),
                     "channel": g.nodes.get(a.get("route") or "", {}).get("label"), "status": G.status(a, today), "note": note,
                     "sources": [f"{notice_label(g, s)} {s.split(':')[2]}" for s in srcs] or ["원문 미추출"],
                     "_hi": a.get("hi") or a.get("lo"), "_sid": sid, "_srcs": srcs})
    rows.sort(key=lambda r: (r["_hi"] or "9999", r["name"]))
    return rows


def contacts_for(g, proc, college=None):
    out, seen = [], {}
    for c in G.out(g, proc, "CONTACT_FOR"):
        a = g.nodes[c]
        if college and a["college"] not in ("*", college):
            continue
        key = (a["topic"], a["college"])
        seen.setdefault(key, set()).add(a.get("phone") or a["office"])
    for (topic, col), vals in sorted(seen.items()):
        who = g.nodes.get(col, {}).get("label", "전체") if col != "*" else "전체"
        office = vals if all(v and v[0].isdigit() for v in vals) else vals
        txt = f"{topic} ({who}): " + " / ".join(sorted(office))
        if len(vals) > 1:
            txt += " — 공지마다 번호가 달라요 [확인 필요]"
        out.append(txt.replace("office:haksa", "교무처 학사팀"))
    return out or ["교무처 학사팀 (단과대학별 번호는 공지 원문 참고)"]


def notices_of(g, sids, extra=()):
    ns = set(extra)
    for s in sids:
        ns |= {u for u in G.inn(g, s, "DESCRIBES") + G.inn(g, s, "MENTIONS") if g.nodes[u].get("body") == "extracted"}
    return [{"source_label": notice_label(g, n), "title": g.nodes[n]["title"], "posted": g.nodes[n].get("posted") or "-",
             "url": g.nodes[n].get("url")} for n in sorted(ns, key=lambda n: g.nodes[n].get("posted") or "")]


def render_procedure(g, term, today, dept=None):
    base = f"proc:grad:{term}"
    central = sorted(G.out(g, base, "HAS_STAGE"))
    dept_proc = f"proc:grad:{term}:{dept}" if dept else None
    dstages = sorted(G.out(g, dept_proc, "HAS_STAGE")) if dept_proc else []
    overridden = {t for s in dstages for t in G.out(g, s, "OVERRIDES")}
    dated_d = [s for s in dstages if g.nodes[s].get("hi") or g.nodes[s].get("lo") or G.inn(g, s, "DESCRIBES") and any(g.nodes[u].get("body") == "extracted" for u in G.inn(g, s, "DESCRIBES"))]
    pending_d = [s for s in dstages if s not in dated_d]
    shown = [s for s in central if s not in overridden and (g.nodes[s].get("hi") or g.nodes[s].get("lo"))]
    pending_c = [s for s in central if s not in overridden and s not in shown]
    rows = stage_rows(g, shown + dated_d, today)
    dname = g.nodes[f"dept:{dept}"]["label"] if dept else None
    warnings = [g.nodes[c]["label"] for c in G.out(g, base, "HAS_CAUTION") + (G.out(g, dept_proc, "HAS_CAUTION") if dept_proc else [])]
    pending = []
    for s in pending_c + pending_d:
        for u in G.inn(g, s, "DESCRIBES"):
            pending.append({"stage": g.nodes[s]["label"], "title": g.nodes[u]["title"], "posted": g.nodes[u]["posted"], "url": g.nodes[u].get("url")})
    college = None
    if dept:
        college = [c for c in G.out(g, f"dept:{dept}", "IN_COLLEGE")][0]
    ctx_name = f"{term} 졸업" + (f" · {dname}" if dname else " · 공통")
    p = {"title": f"{term} 학부 졸업 ({'2027년 2월' if term == '2026-2' else term}) — {dname or '전체 학과 공통'}",
         "topic": "졸업", "target": f"{dname} 졸업예정자" if dname else "8학기 이상 재학생, 조기졸업 신청자, 졸업 희망 수료생",
         "status": "진행 중" if any(r["status"].startswith(("예정", "진행")) for r in rows) else "종료",
         "valid_until": g.nodes[base].get("valid_until"), "context": ctx_name, "stages": rows, "pending": pending,
         "warnings": warnings,
         "notices": notices_of(g, shown + dstages + sorted(overridden)),
         "contacts": contacts_for(g, base, college)}
    p["summary"] = summarize(p) or code_summary(rows, today, dname)
    return env.get_template("procedure.md.j2").render(p=p, today=today.isoformat())


def render_early(g, term, today):
    pid = f"proc:early-grad:{term}"
    sids = G.out(g, pid, "HAS_STAGE")
    rows = stage_rows(g, sids, today)
    rules = G.out(g, pid, "ELIGIBLE_IF")
    warnings = [f"자격({r.split(':')[-1]}): " + tree_text(g.nodes[r]["tree"]).replace("\n", " ") for r in rules]
    p = {"title": f"{term} 조기졸업 신청", "topic": "졸업", "target": "조기졸업 희망 학부 재학생 (편입생 불가)",
         "status": "진행 중" if any(r["status"].startswith(("예정", "진행")) for r in rows) else "신청 마감",
         "valid_until": g.nodes[pid].get("valid_until"), "context": f"{term} 조기졸업", "stages": rows, "pending": [],
         "warnings": warnings, "notices": notices_of(g, sids), "contacts": ["교무처 학사팀 (행정관 201호)"]}
    p["summary"] = summarize(p) or code_summary(rows, today)
    return env.get_template("procedure.md.j2").render(p=p, today=today.isoformat())


def tree_text(t, depth=0) -> str:
    pad = "  " * depth
    if "AND" in t or "OR" in t:
        op = "AND" if "AND" in t else "OR"
        head = "다음을 모두 충족" if op == "AND" else "다음 중 하나 충족"
        return "\n".join([f"{pad}- {head}"] + [tree_text(x, depth + 1) for x in t[op]])
    if t.get("attr") == "other":
        return f"{pad}- {t['text']}"
    v = t["value"]
    if isinstance(v, list):
        v = "~".join(map(str, v)) if t["op"] == "between" else ", ".join(map(str, v))
    if isinstance(v, bool):
        v = "예" if v else "아니오"
    if isinstance(v, dict):
        v = "학번·계열별 기준표"
    note = f" ({t['note']})" if t.get("note") else ""
    return f"{pad}- {ATTR.get(t['attr'], t['attr'])}: {v} {OPS.get(t['op'], t['op'])}".rstrip() + note


def render_rules(g, today):
    rules = []
    for r in G.out(g, "tmpl:grad", "ELIGIBLE_IF"):
        src = G.inn(g, r, "DEFINES")
        rules.append({"title": "정기졸업 자격", "text": tree_text(g.nodes[r]["tree"]), "extra": None,
                      "source": ", ".join(g.nodes[s]["title"] for s in src)})
    for r, title in (("rule:thesis-apply", "졸업논문제 신청 자격"), ("rule:math-exam", "수학과 졸업시험 대상")):
        if r in g:
            a = g.nodes[r]
            extra = None
            if a.get("lookup_tables"):
                rows = a["lookup_tables"]["third_year_credits"]
                extra = "3학년 수료학점: " + "; ".join(f"{x['admission_year']}학번 {x['field']} {x['value']}학점" for x in rows).replace("*", "전체")
            if a.get("subjects"):
                extra = f"과목: {', '.join(a['subjects'])} (세 과목 모두 응시). 면제 조건: 첨부 파일에만 있음 [확인 필요]"
            rules.append({"title": title, "text": tree_text(a["tree"]), "extra": extra,
                          "source": ", ".join(g.nodes[s]["title"] for s in G.inn(g, r, "DEFINES"))})
    outcomes = [{"name": g.nodes[o]["label"], "rule": g.nodes[o]["rule_text"]} for o in G.out(g, "tmpl:grad", "HAS_OUTCOME")]
    srules = [{"name": g.nodes[s]["key"], "rule": g.nodes[s]["rule"], "source": ", ".join(g.nodes[u]["title"] for u in G.inn(g, s, "DESCRIBES"))}
              for s in G.out(g, "tmpl:grad", "HAS_STAGE_RULE") if g.nodes[s].get("rule")]
    warnings = [g.nodes[c]["label"] for c in G.out(g, "tmpl:grad", "HAS_CAUTION")]
    notices = [{"title": g.nodes[n]["title"], "url": g.nodes[n]["url"]} for n in g if n.startswith("notice:static")]
    r = {"title": "학부 졸업 자격·인증제·심사결과", "topic": "졸업", "context": "졸업 규정", "rules": rules, "outcomes": outcomes,
         "stage_rules": srules, "warnings": warnings, "notices": notices}
    return env.get_template("rules.md.j2").render(r=r, today=today.isoformat())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=date.today().isoformat())
    today = date.fromisoformat(ap.parse_args().today)
    g = G.load()
    PAGES.mkdir(parents=True, exist_ok=True)
    old = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PAGES.glob("*.md")}
    pages, off = {}, []
    for t in sorted({a["term"] for n, a in g.nodes(data=True) if a.get("type") == "Procedure"}):
        vu = g.nodes[f"proc:grad:{t}"].get("valid_until")
        if vu and date.fromisoformat(vu) < today:
            off.append(t)
            continue
        if not any(g.nodes[s].get("hi") for s in G.out(g, f"proc:grad:{t}", "HAS_STAGE")):
            continue  # 날짜가 하나도 없는 학기(본문 추출 전)는 아직 만들지 않음
        pages[f"절차_{t}_졸업_공통.md"] = render_procedure(g, t, today)
        for pid in G.inn(g, f"proc:grad:{t}", "PART_OF"):
            dept = pid.split(":")[-1]
            name = g.nodes[f"dept:{dept}"]["label"].replace("·", "").replace(" ", "")
            pages[f"절차_{t}_졸업_{name}.md"] = render_procedure(g, t, today, dept)
        if G.out(g, f"proc:early-grad:{t}", "HAS_STAGE") and any(g.nodes[s].get("hi") for s in G.out(g, f"proc:early-grad:{t}", "HAS_STAGE")):
            pages[f"절차_{t}_조기졸업.md"] = render_early(g, t, today)
    pages["규정_졸업_공통.md"] = render_rules(g, today)
    for p in PAGES.glob("*.md"):
        if p.name not in pages:
            p.unlink()
    changed = []
    for name, txt in pages.items():
        (PAGES / name).write_text(txt, encoding="utf-8")
        if old.get(name) != hashlib.sha256(txt.encode()).hexdigest():
            changed.append(name)

    # 목차: 챗봇(에이전트 A)이 질문에 맞는 페이지를 고르는 표. 경로는 저장소 기준 전체 경로.
    def meta(name):
        if name.startswith("규정_"):
            return "규정", "전체 학부생", "졸업 자격, 졸업학점, 졸업인증제(졸업논문제·정보인증제), 졸업심사 결과(졸업/수료/계속수학), 수학과 졸업시험 대상"
        if "조기졸업" in name:
            t = name.split("_")[1]
            keys = [g.nodes[x]["label"] for x in G.out(g, f"proc:early-grad:{t}", "HAS_STAGE")]
            return "절차", "조기졸업 신청자", "조기졸업, " + ", ".join(dict.fromkeys(keys))
        t = name.split("_")[1]
        dept_name = name.rsplit("_", 1)[-1].removesuffix(".md")
        if dept_name == "공통":
            keys = [g.nodes[x]["label"] for x in G.out(g, f"proc:grad:{t}", "HAS_STAGE")]
            return "절차", f"{t} 졸업예정자 전체(본부·학사팀 일정)", ", ".join(dict.fromkeys(keys))
        code = next((d.split(":")[1] for d, a in g.nodes(data=True) if a.get("type") == "Dept"
                     and a.get("label", "").replace("·", "").replace(" ", "") == dept_name), None)
        keys = [g.nodes[x]["label"] for x in G.out(g, f"proc:grad:{t}:{code}", "HAS_STAGE")] if code else []
        return "절차", f"{dept_name} {t} 졸업예정자 (본부 일정 + 학과 일정, 학과 마감 우선)", ", ".join(dict.fromkeys(keys)) or "본부 일정과 같음"
    idx = ["# 졸업 위키 목차", "", f"갱신: {today} (매일 새벽 자동 갱신)", "",
           "질문에 맞는 페이지를 '대상'과 '키워드'로 고른 뒤 '경로'의 파일을 읽는다. 학과가 정해진 질문은 그 학과 페이지를 먼저 읽는다.", "",
           "| 경로 | 종류 | 대상 | 키워드 |", "|---|---|---|---|"]
    for n in sorted(pages, key=lambda x: (not x.startswith("규정"), "공통" not in x, x)):
        k, who, kw = meta(n)
        idx.append(f"| wiki/pages/{n} | {k} | {who} | {kw.replace('|', '/')} |")
    idx += ["", "## 지난 학기 (페이지 없음 — 질문하면 '지난 학기 공지'라고 안내)", ""] + [f"- {t} 졸업" for t in off] + [""]
    (ROOT / "wiki/index.md").write_text("\n".join(idx), encoding="utf-8")
    log = ROOT / "wiki/log.md"
    prev = log.read_text(encoding="utf-8") if log.exists() else "# 위키 변경 기록\n"
    if changed:
        prev += f"\n- {today} | render | 바뀐 파일 {len(changed)}개: {', '.join(changed)}"
    log.write_text(prev, encoding="utf-8")
    print(f"페이지 {len(pages)}개 생성, 바뀐 파일 {len(changed)}개, 끌 학기: {off}")
    for n in sorted(pages):
        print(" ", n)


if __name__ == "__main__":
    main()
