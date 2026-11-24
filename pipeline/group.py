"""
⓪ 제목으로 같은 글 묶기 (본문 수집 전에 실행 → 받을 공지를 줄임)

입력: data/raw/graduation_index_all.csv (본부 + 48개 학과 게시판, 졸업 관련 493건, 제목·게시일만)
출력:
  data/graph/notice_clusters.csv   공지 → 묶음(같은 내용의 글) → 대표 공지
  data/graph/fetch_queue.csv       본문을 받아야 할 대표 공지만 (재게시는 안 받음)
  data/graph/h0_barcode.csv        0차원 지속성 바코드 (임계값 근거)

방법 (방법론 문서 2.6과 같음)
  w_ij = α·cos(제목 n-gram) + β·Jaccard(엔티티: 학기·단계 유형) + γ·exp(-|Δt|/τ)
  d = 1 - w 로 single-linkage → H0 바코드의 death 값 = 묶음이 합쳐지는 거리
  death 분포의 큰 틈을 임계값 ε* 로 쓴다 (임의의 0.8 같은 값을 찍지 않음)
  연쇄(chaining) 방지: 학기가 다르면 d=1, 학과 자체 공지끼리는 학과가 다르면 d=1
"""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import connected_components, minimum_spanning_tree
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "graph"
ALPHA, BETA, GAMMA, TAU = 0.5, 0.3, 0.2, 14.0

# 제목 → 단계 유형 (절차 템플릿의 단계). 위에서부터 먼저 맞는 것.
STAGE_TYPES = [
    ("대학원", r"\[대학원\]|학위청구|석사|박사|아동심리치료전공"),
    ("교원자격검정", r"교원자격무시험검정"),
    ("폭력예방교육", r"폭력예방교육"),
    ("일정표", r"주요\s*졸업\s*일정|졸업 일정 &|졸업심사일정|졸업 관련 주요 일정"),
    ("조기졸업", r"조기\s*졸업"),
    ("졸업계획제출", r"졸업\s*계획\s*제출|졸업계획입력"),
    ("이수현황정리", r"이수현황|과목 정리|교과구분 변경|상호인정과목|인정과목 이동"),
    ("수료생졸업신청", r"수료생"),
    ("인증제결과", r"인증제.*심사결과|논문제 심사결과|심사결과 조회 및"),
    ("인증제제출", r"인증제.*(제출|시행)|논문/정보 능력 인증|정보인증제 제출"),
    ("최종사정결과", r"최종\s*졸업\s*사정|졸업\s*사정\s*결과|졸업심사결과|졸업자 통지"),
    ("영문성명", r"영문성명"),
    ("계속수학", r"계속수학"),
    ("학위수여식", r"학위수여식"),
    ("학위증배부", r"학위증|졸업생 안내사항"),
    ("졸업시험", r"졸업\s*시험|종합시험|본시험|재시험"),
    ("대체시험·어학", r"대체시험|HSK|TOPCIT|어학"),
    ("지도교수", r"지도교수|지도 방식|지도 교수"),
    ("졸업작품·프로젝트", r"졸업작품|졸업 작품|졸업프로젝트|졸업 프로젝트|졸업보고서|졸업 심사, 졸업 전시|전시|산학협력"),
    ("콜로키움", r"콜로키움"),
    ("양식·규정", r"양식|학칙|규정|졸업학점|졸업 학점|졸업요건|기준"),
    ("논문제신청", r"논문제.*신청|논문제 신청자|논문제 안내|논문제 운영|논문제 공지|논문제 변경|논문제 추가"),
    ("논문제제출", r"논문제.*제출|논문 제출|증빙|인쇄본|미신청자"),
]
CENTRAL = {"일정표", "조기졸업", "졸업계획제출", "이수현황정리", "수료생졸업신청", "인증제결과", "인증제제출",
           "최종사정결과", "영문성명", "계속수학", "학위수여식", "논문제신청",
           "교원자격검정", "폭력예방교육"}  # 교원양성센터·인권센터 공지를 학과가 재게시 → 학교 전체 단계


def stage_type(title: str) -> str:
    for name, pat in STAGE_TYPES:
        if re.search(pat, title):
            return name
    return "기타"


def norm_title(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]|★|\*|※|!|【|】", " ", t)
    t = re.sub(r"(학과|학부|전공)\s*(공지|정보)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def days(s: str) -> int:
    y, m, d = map(int, s[:10].split("-"))
    return date(y, m, d).toordinal()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((ROOT / "data/raw/graduation_index_all.csv").open(encoding="utf-8-sig")))
    rows = [r for r in rows if r["posted"]]
    n = len(rows)
    for i, r in enumerate(rows):
        r["idx"] = i
        r["stage"] = stage_type(r["title"])
        r["is_main"] = r["source"] == "대표 홈페이지"
        src = r["host"].split(".")[0]
        r["nid"] = f"notice:{'main' if src == 'www' else src}:{r['id']}"

    # 1) 세 가지 유사도
    tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3)).fit_transform([norm_title(r["title"]) for r in rows])
    cos = (tfidf @ tfidf.T).toarray()
    ent = [{f"term:{r['term']}", f"stage:{r['stage']}"} for r in rows]
    jac = np.array([[len(a & b) / len(a | b) for b in ent] for a in ent])
    t = np.array([days(r["posted"]) for r in rows], dtype=float)
    tim = np.exp(-np.abs(t[:, None] - t[None, :]) / TAU)
    w = ALPHA * cos + BETA * jac + GAMMA * tim
    d = np.clip(1 - w, 0, 1)

    # 2) 연쇄 방지 규칙
    term = np.array([r["term"] for r in rows])
    d[term[:, None] != term[None, :]] = 1.0
    local = np.array([r["stage"] not in CENTRAL for r in rows])
    host = np.array([r["host"] for r in rows])
    # 학과 자체 단계(졸업시험·지도교수 등)는 같은 학과(또는 같은 학부 공동 공지) 안에서만 묶는다
    sw = {"csweb.sookmyung.ac.kr", "ds.sookmyung.ac.kr"}  # 소프트웨어학부 두 전공은 같은 글을 올림
    same_unit = (host[:, None] == host[None, :]) | (np.isin(host, list(sw))[:, None] & np.isin(host, list(sw))[None, :])
    d[(local[:, None] | local[None, :]) & ~same_unit] = 1.0
    # 학과 자체 공지는 제목이 거의 같을 때만 같은 글 (교수별 지도 방식 안내처럼 비슷하지만 다른 글을 합치지 않음)
    d[(local[:, None] | local[None, :]) & (cos < 0.9)] = 1.0
    # 블로킹: 본부 단계 유형이 서로 다르면 같은 글이 아니다 (예: '수료생 졸업신청'과 '인증제 제출'은 같은 날 올라와도 다른 공지)
    stg = np.array([r["stage"] for r in rows])
    cen = np.isin(stg, list(CENTRAL))
    d[cen[:, None] & cen[None, :] & (stg[:, None] != stg[None, :])] = 1.0
    np.fill_diagonal(d, 0)

    # 3) H0 바코드 = 최소 신장 트리 간선 길이 (single-linkage 병합 높이)
    mst = minimum_spanning_tree(d + 1e-9).toarray()
    deaths = np.sort(mst[mst > 0] - 1e-9)
    finite = deaths[deaths < 0.999]
    gaps = np.diff(finite)
    lo, hi = 0.05, 0.6  # 너무 작은 틈(사실상 같은 글)·너무 큰 거리는 후보에서 제외
    cand = [(gaps[i], finite[i], finite[i + 1]) for i in range(len(gaps)) if lo <= finite[i] <= hi]
    g, a, b = max(cand)
    eps = (a + b) / 2
    with (OUT / "h0_barcode.csv").open("w", newline="") as f:
        csv.writer(f).writerows([["death"]] + [[round(x, 4)] for x in deaths])

    # 4) ε* 로 자르기 → 묶음
    adj = (d < eps).astype(int)
    k, lab = connected_components(adj, directed=False)
    clusters = defaultdict(list)
    for r, c in zip(rows, lab):
        clusters[c].append(r)

    # 대표 공지: 본부 원본 > 가장 먼저 올라온 글
    cl_rows, fetch = [], []
    for c, mem in clusters.items():
        rep = sorted(mem, key=lambda r: (not r["is_main"], r["posted"]))[0]
        stages = Counter(r["stage"] for r in mem).most_common(1)[0][0]
        for r in mem:
            r["cluster"] = f"C{c:03d}"
            r["rep"] = rep["nid"]
            cl_rows.append(r)
        if stages == "대학원":
            kind = "보류(대학원)"
        elif any(r["is_main"] for r in mem):
            kind = "본부"
        else:
            kind = "학과 자체" if stages not in CENTRAL else "본부 원본 미수집"
        fetch.append({"cluster": f"C{c:03d}", "rep": rep["nid"], "dept": rep["dept"], "posted": rep["posted"], "term": rep["term"],
                      "stage": stages, "kind": kind, "size": len(mem), "depts": len({r["host"] for r in mem}),
                      "title": rep["title"], "host": rep["host"], "id": rep["id"]})

    with (OUT / "notice_clusters.csv").open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["cluster", "rep", "nid", "dept", "term", "stage", "posted", "title"])
        for r in sorted(cl_rows, key=lambda r: (r["cluster"], not r["is_main"], r["posted"])):
            wr.writerow([r["cluster"], r["rep"], r["nid"], r["dept"], r["term"], r["stage"], r["posted"], r["title"]])
    fetch.sort(key=lambda x: (x["term"] != "2026-2", x["kind"] != "학과 자체", -x["size"], x["posted"]))
    with (OUT / "fetch_queue.csv").open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(fetch[0].keys()))
        wr.writeheader()
        wr.writerows(fetch)

    # 6) 점검: 규칙 기반 정답(학기+본부 단계 유형)과 비교
    pur_ok = pur_n = 0
    for c, mem in clusters.items():
        cen = [r for r in mem if r["stage"] in CENTRAL]
        if len(cen) > 1:
            top = Counter((r["term"], r["stage"]) for r in cen).most_common(1)[0][1]
            pur_ok += top
            pur_n += len(cen)
    hist = Counter(round(x, 1) for x in finite)
    print(f"공지 {n}건 → 묶음 {k}개 (임계값 ε*={eps:.3f}, 가장 큰 틈 {a:.3f}→{b:.3f})")
    print("H0 death 분포(0.1 단위):", dict(sorted(hist.items())))
    print(f"본부 단계 묶음 순도: {pur_ok}/{pur_n} = {pur_ok / max(pur_n, 1):.1%}")
    kc = Counter(x["kind"] for x in fetch)
    print("본문 받을 대표 공지:", dict(kc), "합계", len(fetch))
    print("\n큰 묶음 상위 10:")
    for x in sorted(fetch, key=lambda x: -x["size"])[:10]:
        print(f"  {x['cluster']} {x['term']} {x['stage']:8} 글 {x['size']:2}개·학과 {x['depts']:2}곳 대표={x['rep']} {x['title'][:40]}")


if __name__ == "__main__":
    main()
