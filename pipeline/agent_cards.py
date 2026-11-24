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

    rows = "\n".join(f"| {d['name']} | {d['code']} | {'있음' if d['has_dept_schedule'] else '본부 일정만'} |" for d in S.depts(g))
    (OUT / "학과코드.md").write_text(f"# 학과 이름과 학과별 일정 파일\n\n| 학과 | 코드 | 학과 자체 일정 |\n|---|---|---|\n{rows}\n", encoding="utf-8")
    print(f"agent_b 파일 {len(list(OUT.glob('*.md')))}개 → {OUT}")


if __name__ == "__main__":
    main()
