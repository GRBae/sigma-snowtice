"""
③ LLM 구조화 추출 — 원문 1건 → JSON 1개 (data/extracted/{source}_{no}.json)

  python pipeline/extract.py                 # raw에 있고 extracted에 없는 공지 전부
  python pipeline/extract.py --only main_96120

규칙 (pipeline/extract_prompt.md)
  - 원문에 없는 값은 null, 모든 날짜·조건·대상에 원문 문장(evidence)을 그대로 복사
  - 출력 형식은 data/extracted/main_96120.json 등 gold 예시와 같다 (few-shot으로 2건 첨부)
  - 공개 게시판 공지만 입력한다 (내부자료·개인정보 금지). API 키는 .env에 두고 git에서 뺀다

★ 정해야 할 것: call_llm()의 공급자 (SNOWCHAT API Gateway / 다른 API). 정해지면 이 함수만 채운다.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, EX = ROOT / "data/raw", ROOT / "data/extracted"
FEWSHOT = ["main_96120", "math_146958"]  # 본부 단계형 1건 + 학과 단계형 1건
REQUIRED = {"notice", "skip", "role", "topic", "procedure", "issued_by", "stages", "rules", "cautions", "outcomes", "contacts", "refers_to"}


def call_llm(system: str, user: str) -> str:
    """JSON 문자열을 돌려준다. temperature 0, JSON 모드.
    예) OpenAI 호환 게이트웨이라면:
        from openai import OpenAI
        cli = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
        r = cli.chat.completions.create(model=os.environ["LLM_MODEL"], temperature=0,
                                        response_format={"type": "json_object"},
                                        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content
    """
    raise NotImplementedError("추출 LLM 공급자를 정한 뒤 call_llm()을 채우세요 (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL).")


def build_prompt(meta: dict, text: str) -> tuple[str, str]:
    system = (ROOT / "pipeline/extract_prompt.md").read_text(encoding="utf-8")
    shots = []
    for s in FEWSHOT:
        raw = RAW / s / "text.txt"
        if raw.exists():
            shots.append(f"### 예시 원문\n{raw.read_text(encoding='utf-8')[:4000]}\n### 예시 출력\n{(EX / f'{s}.json').read_text(encoding='utf-8')}")
    user = "\n\n".join(shots + [f"### 공지 메타\n{json.dumps(meta, ensure_ascii=False)}\n### 원문\n{text}\n### 출력 (JSON 하나)"])
    return system, user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    todo = [d for d in sorted(RAW.iterdir()) if d.is_dir() and (d / "text.txt").exists() and not (EX / f"{d.name}.json").exists()]
    if args.only:
        todo = [d for d in todo if d.name == args.only]
    print(f"추출 대상 {len(todo)}건")
    for d in todo:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        system, user = build_prompt(meta, (d / "text.txt").read_text(encoding="utf-8"))
        out = json.loads(call_llm(system, user))
        missing = REQUIRED - set(out)
        if missing:
            print(f"  {d.name}: 칸 누락 {missing} → 건너뜀")
            continue
        out["extracted_by"] = os.environ.get("LLM_MODEL", "llm")
        (EX / f"{d.name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {d.name}: 단계 {len(out['stages'])}개")


if __name__ == "__main__":
    main()
