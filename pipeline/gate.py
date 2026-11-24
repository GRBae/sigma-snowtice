"""
안전장치 — 오늘 결과가 이상하면 커밋·업로드하지 않는다 (어제 데이터를 그대로 둔다).

  python pipeline/gate.py      # 통과하면 0, 막히면 1로 끝남 → GitHub Actions가 push 단계를 건너뜀

막는 조건 (직전 커밋과 비교)
  - 공지 노드가 20% 넘게 줄었다      → 사이트 구조가 바뀌어 목록을 못 읽은 경우
  - 위키 페이지 수가 20% 넘게 줄었다
  - 날짜가 채워진 단계가 줄었다       → 추출·검증이 대량으로 실패한 경우
  - 검증 실패 공지가 전체의 30% 이상
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def stats_from_text(nodes_txt: str) -> dict:
    n = [json.loads(l) for l in nodes_txt.splitlines() if l.strip()]
    return {"notice": sum(1 for x in n if x["type"] == "Notice"),
            "dated": sum(1 for x in n if x["type"] == "Stage" and x.get("hi"))}


def prev_file(path: str) -> str | None:
    r = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def main():
    now = stats_from_text((ROOT / "data/graph/graph_nodes.jsonl").read_text(encoding="utf-8"))
    now["pages"] = len(list((ROOT / "wiki/pages").glob("*.md")))
    v = json.loads((ROOT / "data/extracted/_verify.json").read_text(encoding="utf-8"))
    bad_ratio = sum(1 for x in v.values() if not x["ok"]) / max(len(v), 1)
    problems = []
    old_nodes = prev_file("data/graph/graph_nodes.jsonl")
    if old_nodes:
        old = stats_from_text(old_nodes)
        old_pages = subprocess.run(["git", "ls-tree", "--name-only", "HEAD", "wiki/pages/"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        old["pages"] = len(old_pages)
        if now["notice"] < old["notice"] * 0.8:
            problems.append(f"공지 노드 {old['notice']} → {now['notice']}")
        if old["pages"] and now["pages"] < old["pages"] * 0.8:
            problems.append(f"위키 페이지 {old['pages']} → {now['pages']}")
        if now["dated"] < old["dated"]:
            problems.append(f"날짜 있는 단계 {old['dated']} → {now['dated']}")
        print(f"어제 {old} → 오늘 {now}")
    if bad_ratio >= 0.3:
        problems.append(f"검증 실패 비율 {bad_ratio:.0%}")
    if problems:
        print("⛔ 업로드 중단:", "; ".join(problems))
        sys.exit(1)
    print("✅ 통과")


if __name__ == "__main__":
    main()
