"""
(한 번만 실행) 손으로 만든 정답 추출(data/gold/records_graduation.json)을
파이프라인 형식인 '공지 1건 = JSON 1개'(data/extracted/{source}_{no}.json)로 나눈다.

이후 extract.py(LLM)가 만드는 파일도 같은 형식이다. gold 파일은 LLM 추출 정확도를 잴 때 정답 라벨로 남겨 둔다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
G = json.loads((ROOT / "data/gold/records_graduation.json").read_text(encoding="utf-8"))
OUT = ROOT / "data/extracted"
DATE_Q = re.compile(r"\d{1,2}\s*[./월]\s*\d{1,2}|\d{4}\s*[.년]")

# gold 단계 ID → 표준 단계 키 (그래프 전체에서 쓰는 이름)
STAGE_KEY = {
    "stg:grad:2026-2:01": "졸업계획제출", "stg:grad:2026-2:02": "전공선택", "stg:grad:2026-2:03": "이수현황정리",
    "stg:grad:2026-2:04": "논문제신청", "stg:grad:2026-2:05": "수료생졸업신청", "stg:grad:2026-2:06": "논문제결과물제출",
    "stg:grad:2026-2:07": "정보인증제등록", "stg:grad:2026-2:08": "인증제결과확인", "stg:grad:2026-2:09": "영문성명확인",
    "stg:grad:2026-2:10": "계속수학신청", "stg:grad:2026-2:11": "최종사정결과조회", "stg:grad:2026-2:12": "학위수여식",
    "stg:early:2026-2:01": "조기졸업신청",
    "stg:math:2026-2:01": "졸업시험1차신청", "stg:math:2026-2:02": "졸업시험1차응시", "stg:math:2026-2:03": "졸업시험2차신청",
    "stg:math:2026-2:04": "졸업시험2차응시", "stg:math:2026-2:05": "졸업시험결과", "stg:math:2026-2:06": "콜로키움참석",
}
PROC = {  # gold 절차 → (템플릿, 범위)
    "proc:grad:2026-2": ("tmpl:grad", "본부"), "proc:early-grad:2026-2": ("tmpl:early-grad", "본부"),
    "proc:math-thesis:2026-2": ("tmpl:grad", "math"),
}
URL = {"main": "https://www.sookmyung.ac.kr/kr/news/important-notice.do?mode=view&articleNo={}",
       "math": "https://math.sookmyung.ac.kr/math/notice/notice.do?mode=view&articleNo={}",
       "static": "https://www.sookmyung.ac.kr/kr/university-life/{}.do",
       "physics": "https://physics.sookmyung.ac.kr/bbs/physics/701/{}/artclView.do"}


def nid(src: str) -> str:  # "main:94905" → "notice:main:94905"
    return "notice:" + src


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stages = {s["id"]: s for s in G["stages"]}
    by_stage_proc = {s["id"]: s["proc"] for s in G["stages"]}
    files = 0
    for n in G["notices"]:
        if n.get("body_pending"):
            continue  # 본문 없는 공지는 추출 결과도 없다
        src, no = n["id"].split(":")
        ex = {
            "notice": {"id": nid(n["id"]), "source": src, "article_no": no, "url": URL[src].format(no), "title": n["title"],
                       "posted": n.get("posted"), "posted_by": n.get("posted_by"), "hits": n.get("hits")},
            "skip": False, "role": n["role"], "topic": "졸업",
            "procedure": None, "issued_by": n.get("issued_by"),
            "stages": [], "rules": [], "cautions": [], "outcomes": [], "contacts": [],
            "refers_to": [nid(r) for r in n.get("refers_to", [])],
            "duplicate_of": nid(n["duplicate_of"]) if n.get("duplicate_of") else None,
            "attachments_pending": n.get("attachments_pending", []),
            "verification": {"method": "브라우저 원문 대조", "date": "2026-11-24", "result": "근거 문장 전부 원문에 있음"},
            "extracted_by": "gold(수작업)",
        }
        part = n["part_of"]
        if part in PROC:
            tmpl, scope = PROC[part]
            ex["procedure"] = {"template": tmpl, "term": "2026-2", "scope": scope}
        elif part == "tmpl:grad":
            ex["procedure"] = {"template": "tmpl:grad", "term": None, "scope": "본부"}
        # 이 공지에 근거가 있는 단계만, 근거도 이 공지 것만
        for sid, s in stages.items():
            mine = [e["quote"] for e in s.get("evidence", []) if e["src"] == n["id"]]
            if not mine:
                continue
            has_date = sid in n.get("stages", []) or any(DATE_Q.search(q) for q in mine)
            tmpl, scope = PROC[by_stage_proc[sid]]
            ex["stages"].append({
                "key": STAGE_KEY[sid], "name": s["name"], "scope": scope,
                "procedure_template": tmpl,
                "date": s["date"] if has_date else None,
                "route": s.get("route"), "place": s.get("place"), "target": s.get("target"), "required": s.get("required"),
                "documents": s.get("documents", []), "requires": s.get("requires", []),
                "evidence": mine,
            })
        for r in G["rules"]:
            if r["src"] == n["id"]:
                ex["rules"].append({k: v for k, v in r.items() if k != "src"})
        for c in G["cautions"]:
            if c["evidence"]["src"] == n["id"]:
                ex["cautions"].append({"id": c["id"], "text": c["text"], "evidence": [c["evidence"]["quote"]]})
        for o in G["outcomes"]:
            if o["src"] == n["id"]:
                ex["outcomes"].append({k: v for k, v in o.items() if k != "src"})
        for c in G["contacts"]:
            for e in c["evidence"]:
                if e["src"] == n["id"]:
                    ex["contacts"].append({"topic": c["topic"], "college": c["college"], "office": c["office"], "phone": c["phone"], "evidence": [e["quote"]]})
        (OUT / f"{src}_{no}.json").write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
        files += 1

    # gold에 없던 추가 사실 (2026-11-24 브라우저로 원문 확인)
    extra = {
        "main_95274": {"contacts": [{"topic": "졸업심사", "college": "college:liberal-arts", "office": "office:haksa", "phone": "02-710-9015",
                                     "evidence": ["문과대학, 약학대학, 영어영문학부, 미디어학부 | (02)710-9015"]}]},
        "main_96120": {"contacts": [{"topic": "졸업심사", "college": "college:liberal-arts", "office": "office:haksa", "phone": "02-710-9994",
                                     "evidence": ["문과대학, 약학대학, 미디어학부, 영어영문학부(02)710-9994"]}]},
        # 고정 안내의 '대략적 시기' (학기 무관 규칙) — 학기 공지와 비교하는 데 쓴다
        "static_graduate01": {"stages": [{"key": "졸업계획제출", "name": "재학생 졸업신청(졸업계획 제출)", "scope": "본부",
                                          "procedure_template": "tmpl:grad",
                                          "date": {"lo": None, "hi": None, "precision": "rule", "rule": "1학기 4월 중순 / 2학기 10월 중순"},
                                          "route": "route:portal", "evidence": ["숙명포털 (4월(1학기) /10월 (2학기) 중순)"]}]},
    }
    for fname, add in extra.items():
        p = OUT / f"{fname}.json"
        ex = json.loads(p.read_text(encoding="utf-8"))
        for k, v in add.items():
            ex[k] += v
        p.write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")

    # 신소재물리학부 학과 마감 (본부보다 이름) — 원문: 2026-11-24 브라우저로 본문 확인
    phys = {
        "notice": {"id": "notice:physics:217463", "source": "physics", "article_no": "217463", "url": URL["physics"].format("217463"),
                   "title": "[학사] [졸업] 2026-2 졸업논문제 제출마감 및 세부사항(~12.20.일요일 자정까지)", "posted": "2026-11-23",
                   "posted_by": "dept:physics", "hits": None},
        "skip": False, "role": "stage_detail", "topic": "졸업",
        "procedure": {"template": "tmpl:grad", "term": "2026-2", "scope": "physics"}, "issued_by": "dept:physics",
        "stages": [{"key": "논문제결과물제출", "name": "졸업논문제 결과물 제출(캡스톤디자인 결과보고서)", "scope": "physics",
                    "procedure_template": "tmpl:grad",
                    "date": {"lo": "2026-12-01", "hi": "2026-12-20T23:59", "precision": "minute"},
                    "route": "route:dept-mail", "target": "신소재물리학부 2026-2 졸업논문제 신청자", "required": True,
                    "documents": ["캡스톤디자인 결과보고서(필수)", "발표자료·부가자료(선택)"], "requires": [],
                    "evidence": ["1. 제출기한: 2026.12.01.(화)~2026.12.20.(일) 자정까지"], "overrides": "본부"}],
        "rules": [], "cautions": [], "outcomes": [], "contacts": [], "refers_to": [], "duplicate_of": None,
        "attachments_pending": [], "extracted_by": "gold(수작업)",
        "verification": {"method": "브라우저 원문 대조", "date": "2026-11-24", "result": "근거 문장 원문에 있음"},
    }
    (OUT / "physics_217463.json").write_text(json.dumps(phys, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"추출 파일 {files + 1}개 → {OUT}")


if __name__ == "__main__":
    main()
