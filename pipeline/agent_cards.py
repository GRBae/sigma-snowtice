"""
SNOWCHAT Agent B용 지식 파일 (B안: SNOWCHAT이 외부 API를 못 부를 때).
API가 그때그때 계산할 것을 매일 새벽 미리 계산해서 md로 찍어 둔다.

  python pipeline/agent_cards.py --today 2026-11-24
  → wiki/agent_b/학과별_졸업할일_{학과}.md (학과 일정이 있는 학과마다)
    wiki/agent_b/이번주_마감.md, wiki/agent_b/2주_마감.md
    wiki/agent_b/학과코드.md

A안(외부 API 호출 가능)이면 이 파일들은 필요 없고 api/ 서버를 도구로 등록한다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from api import service as S  # noqa: E402

OUT = ROOT / "wiki/agent_b"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=date.today().isoformat())
    today = date.fromisoformat(ap.parse_args().today)
    gr = S.Graph()
    g = gr.g
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    head = (f"> 이 파일은 매일 새벽 그래프에서 자동 생성됩니다. 기준일 {today.isoformat()}. "
            "D-숫자와 '마감/예정'은 기준일 기준이므로 오늘 날짜와 다르면 날짜(period)로 다시 판단하세요.\n\n")

    depts = [d for d in S.depts(g) if d["has_dept_schedule"]]
    for d in depts:
        r = S.todo(g, d["code"], today)
        body = S.todo_card_text(r)
        adv = r["advisor_specific"]
        if adv:
            body += "\n\n## 지도교수별 일정 (학생에게 지도교수를 물은 뒤 해당 줄만 안내)\n"
            for name in adv["advisors_in_notices"]:
                rr = S.todo(g, d["code"], today, advisor=name)
                for c in rr["items"]:
                    if name in (c["target"] or ""):
                        body += f"- [{name} 교수] {c['label']} | {c['period']} | {c['status']}\n"
        hidden = S.todo(g, d["code"], today, enroll_status="재학", admission_year=2022)["hidden_for_profile"]
        if hidden:
            body += "\n\n## 대상이 정해진 단계 (해당 학생에게만)\n" + "\n".join(f"- {h['label']}: {h['why']}" for h in hidden)
        (OUT / f"학과별_졸업할일_{d['name'].replace('·', '')}.md").write_text(
            f"# {d['name']} 2026-2 졸업 할 일 (학과 코드 {d['code']})\n\n{head}{body}\n", encoding="utf-8")

    for days, name in ((7, "이번주_마감"), (14, "2주_마감")):
        r = S.deadlines(g, today, days)
        lines = [f"- {c['period']} | {c['dept_name']} | {c['label']}" + (f" | 대상: {c['target']}" if c['target'] else "")
                 + (f" | 출처: {c['sources'][0]['url']}" if c["sources"] else "") for c in r["items"]]
        (OUT / f"{name}.md").write_text(f"# {days}일 안에 끝나는 졸업 일정 (전체 학과)\n\n{head}" + ("\n".join(lines) or "- 없음") + "\n",
                                       encoding="utf-8")

    # 불이익·유의사항 모음 (그래프의 HAS_CAUTION + 출처 공지 DEFINES)
    import graphio as G
    L = [f"# 졸업 유의사항·불이익 모음 (본부 + 학과)\n\n{head}"]
    def caution_lines(proc):
        out = []
        for c in G.out(g, proc, "HAS_CAUTION"):
            src = [n for n in G.inn(g, c, "DEFINES") if g.nodes[n].get("type") == "Notice"]
            url = g.nodes[src[0]].get("url") if src else None
            out.append(f"- ⚠ {S.label(g, c)}" + (f" | 출처: {url}" if url else ""))
        return out
    L.append("## 본부(전체)\n" + "\n".join(caution_lines("tmpl:grad") + caution_lines(f"proc:grad:{S.DEFAULT_TERM}")))
    for d in depts:
        ls_ = caution_lines(f"proc:grad:{S.DEFAULT_TERM}:{d['code']}")
        if ls_:
            L.append(f"## {d['name']}\n" + "\n".join(ls_))
    (OUT / "유의사항_모음.md").write_text("\n\n".join(L) + "\n", encoding="utf-8")

    # 연관 추천 (Personalized PageRank: 학과 절차에서 가까운 단계·공지 + 추천 경로)
    R = [f"# 학과별 연관 일정·공지 (그래프 연관도 순)\n\n{head}"
         "> '추천 경로'는 그래프에서 학과 졸업 절차부터 그 항목까지 이어진 관계예요. '왜 같이 챙겨야 하는지' 설명에 쓴다.\n"]
    for d in depts:
        v = S.graph_view(g, f"proc:grad:{S.DEFAULT_TERM}:{d['code']}", today, k=10, types=("Stage", "Notice"), show_closed=False)
        items = [n for n in v["nodes"] if n["id"] != v["seed"]["id"]][:8]
        if items:
            R.append(f"## {d['name']}\n" + "\n".join(
                f"- {n['label']}" + (f" | {n['period']}" if n.get('period') else "") + (f" | {n['url']}" if n.get('url') else "")
                + f" | 추천 경로: {n['why']}" for n in items))
    (OUT / "연관_추천.md").write_text("\n\n".join(R) + "\n", encoding="utf-8")

    rows = "\n".join(f"| {d['name']} | {d['code']} | {'있음' if d['has_dept_schedule'] else '본부 일정만'} |" for d in S.depts(g))
    (OUT / "학과코드.md").write_text(f"# 학과 이름과 학과별 일정 파일\n\n| 학과 | 코드 | 학과 자체 일정 |\n|---|---|---|\n{rows}\n", encoding="utf-8")
    # 에이전트 B 목차
    files = sorted(OUT.glob("학과별_졸업할일_*.md"))
    ix = [f"# 개인화·집계용 자료 목차 (그래프에서 계산한 결과)\n\n갱신: {today.isoformat()} (매일 새벽 자동 갱신)\n",
          "| 경로 | 언제 읽나 |", "|---|---|",
          "| wiki/agent_b/학과코드.md | 학과 이름이 애매할 때, 학과 자체 일정이 있는 학과인지 볼 때 |",
          "| wiki/agent_b/학과별_졸업할일_{학과}.md | '나 ○○학과인데 뭐 남았어?' — 본부+학과 일정을 합치고 학과 마감 우선을 반영한 남은 단계, 지도교수별 일정, 대상이 정해진 단계(수료생만 등) |",
          "| wiki/agent_b/이번주_마감.md | '이번 주 / 곧 마감' — 전체 학과 7일 안 마감 |",
          "| wiki/agent_b/2주_마감.md | '2주 안 / 이번 달 마감' — 전체 학과 14일 안 마감 |",
          "| wiki/agent_b/유의사항_모음.md | '불이익 / 놓치면 안 되는 것 / 주의할 점 정리' — 본부·학과 유의사항 전부 |",
          "| wiki/agent_b/연관_추천.md | '같이 챙길 것 / 관련 일정 / 비슷한 것' — 그래프 연관도 순 항목과 추천 경로 |",
          "", "학과별 파일 목록:", ""] + [f"- wiki/agent_b/{f.name}" for f in files] + [""]
    (OUT / "index.md").write_text("\n".join(ix), encoding="utf-8")
    print(f"agent_b 파일 {len(list(OUT.glob('*.md')))}개 → {OUT}")


if __name__ == "__main__":
    main()
