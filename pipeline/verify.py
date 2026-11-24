"""
④ 코드 검증 — LLM 추출 결과를 그대로 믿지 않는다.

  python pipeline/verify.py

검사 (실패한 값은 그래프에 'verified: false'로 들어가고, 위키에는 [확인 필요]로 나간다)
  1. 근거 문장이 원문(data/raw/{source}_{no}/text.txt)에 실제로 있는가 (공백·표 기호 무시)
     - 원문 폴더가 아직 없으면 추출 파일의 verification 기록(이전 대조 결과)을 쓴다
  2. 날짜의 요일이 근거 문장의 요일과 같은가 (연도 추정이 맞았는지 확인)
  3. 시작 ≤ 종료
결과: data/extracted/_verify.json  {공지ID: {"ok": bool, "stages": {단계키: bool}, "problems": [...]}}
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "data/extracted"
RAW = ROOT / "data/raw"
WD = "월화수목금토일"
norm = lambda s: re.sub(r"[\s|/]", "", s or "")


def weekday_problems(date: dict, quotes: list[str]) -> list[str]:
    out = []
    for d in (date.get("lo"), date.get("hi")):
        if not d:
            continue
        dd = datetime.fromisoformat(d).date()
        w = WD[dd.weekday()]
        for q in quotes:
            q2 = q.replace(" ", "")
            for fm in (f"{dd.month}월{dd.day}일(", f"{dd.month}/{dd.day}(", f"{dd.month}.{dd.day}.(", f"{dd.month:02d}.{dd.day:02d}(",
                       f"{dd.month:02d}.{dd.day:02d}.(", f"{dd.year}.{dd.month:02d}.{dd.day:02d}.(", f"{dd.month}.{dd.day:02d}.("):
                i = q2.find(fm)
                if i >= 0 and i + len(fm) < len(q2) and q2[i + len(fm)] != w:
                    out.append(f"{d}는 {w}요일인데 원문은 '{q2[i + len(fm)]}': {q}")
    return out


def main():
    report = {}
    for f in sorted(EX.glob("*.json")):
        if f.name.startswith("_"):
            continue
        ex = json.loads(f.read_text(encoding="utf-8"))
        nid = ex["notice"]["id"]
        raw = RAW / f.stem / "text.txt"
        text = norm(raw.read_text(encoding="utf-8")) if raw.exists() else None
        problems, stage_ok = [], {}

        def quote_ok(q):
            if text is None:  # 원문 폴더 없음 → 이전 대조 기록을 믿되 표시
                return "근거 문장 전부 원문에 있음" in ex.get("verification", {}).get("result", "") or "원문에 있음" in ex.get("verification", {}).get("result", "")
            return norm(q) in text

        for s in ex["stages"]:
            ok = all(quote_ok(q) for q in s["evidence"])
            if not ok:
                problems.append(f"근거 불일치: {s['key']}")
            if s.get("date"):
                wp = weekday_problems(s["date"], s["evidence"])
                problems += wp
                ok = ok and not wp
                lo, hi = s["date"].get("lo"), s["date"].get("hi")
                if lo and hi and lo > hi:
                    problems.append(f"시작>종료: {s['key']}")
                    ok = False
            stage_ok[s["key"]] = ok
        for c in ex["cautions"] + ex["contacts"]:
            if not all(quote_ok(q) for q in c["evidence"]):
                problems.append(f"근거 불일치: {c.get('text') or c.get('topic')}")
        report[nid] = {"ok": not problems, "stages": stage_ok, "problems": problems,
                       "basis": "raw/text.txt 대조" if text is not None else "이전 대조 기록(원문 폴더 없음)"}
    (EX / "_verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = {k: v for k, v in report.items() if not v["ok"]}
    print(f"검증 {len(report)}건: 통과 {len(report) - len(bad)}, 문제 {len(bad)}")
    for k, v in bad.items():
        print(" ", k, v["problems"])
    print("원문 폴더 없이 이전 대조 기록으로 통과한 건:", sum(1 for v in report.values() if v["basis"].startswith("이전")))


if __name__ == "__main__":
    main()
