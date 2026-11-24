"""
시그마 그래프 API — 웹사이트와 SNOWCHAT Agent B가 같이 부르는 서버.

  실행:  uvicorn api.main:app --port 8000        (sigma 폴더에서)
  문서:  http://localhost:8000/docs   (Swagger, 프론트 담당이 여기서 바로 눌러 보면 됨)
  명세:  http://localhost:8000/openapi.json   (SNOWCHAT 도구 등록용)

데이터: data/graph/graph_nodes.jsonl · graph_edges.jsonl (매일 새벽 GitHub Actions가 갱신)
갱신 반영: POST /admin/reload (Authorization: Bearer $RELOAD_TOKEN)
  - DATA_BASE_URL 환경변수가 있으면 그 주소(예: GitHub raw)에서 jsonl을 내려받아 교체
  - 없으면 디스크의 파일을 다시 읽음 (Render·Railway는 push 때 재배포되므로 이것만으로 충분)
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import urllib.request
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from api import service as S

ROOT = Path(__file__).resolve().parent.parent
GR = S.Graph()

app = FastAPI(
    title="시그마 공지 그래프 API",
    version="0.1.0",
    description="숙명여대 공지를 모아 만든 그래프에서 '내 학과 졸업 일정', '마감 임박', '연관 공지'를 계산해 돌려준다. "
                "날짜 비교와 자격 판정은 서버 코드가 하고, 응답의 period/status를 그대로 보여주면 된다. "
                "개인정보(학번·이름)는 받지도 저장하지도 않는다.",
)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["GET", "POST"], allow_headers=["*"])


def today_param(today: Optional[date] = Query(None, description="기준일(테스트용). 비우면 서버 오늘 날짜(Asia/Seoul)")) -> date:
    if today:
        return today
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=9))).date()


def dept_check(dept: str):
    if f"dept:{dept}" not in GR.g:
        raise HTTPException(404, f"모르는 학과 코드: {dept}. /depts 에서 확인")
    return dept


@app.get("/health", summary="서버·그래프 상태")
def health():
    return {"ok": True, **GR.stats()}


@app.get("/depts", summary="학과 코드 목록", description="todo·deadlines의 dept 값으로 쓰는 코드와 이름. has_dept_schedule=false면 학과 자체 일정은 아직 없음.")
def depts():
    return S.depts(GR.g)


@app.get("/todo", operation_id="get_my_graduation_todo", summary="내 학과 졸업 할 일 (본부+학과 합침, 학과 마감 우선)",
         description="학생의 학과와 학적 상태로 이번 학기 졸업 절차에서 아직 안 끝난 단계를 날짜순으로 돌려준다. "
                     "학과가 본부와 다른 마감을 정했으면 학과 것만 남기고 overrides_central에 본부 기간을 적는다. "
                     "지도교수별 일정이 있으면 advisor를 넘겨야 그 교수 일정만 나온다.")
def todo(dept: str = Query(..., description="학과 코드 (예: korean, math, ds). /depts 참고"),
         term: str = Query(S.DEFAULT_TERM, description="학기 (2026-2 = 2027년 2월 졸업)"),
         enroll_status: Optional[Literal["재학", "휴학", "수료"]] = Query(None, description="학적 상태"),
         admission_year: Optional[int] = Query(None, ge=2000, le=2030, description="입학 연도(학번 앞 4자리)만. 학번 전체는 받지 않음"),
         advisor: Optional[str] = Query(None, description="지도교수 이름 (지도교수별 일정이 있는 학과만)"),
         include_closed: bool = False, today: date = Depends(today_param)):
    dept_check(dept)
    return S.todo(GR.g, dept, today, term, enroll_status, admission_year, advisor, include_closed)


@app.get("/todo/card", operation_id="get_my_graduation_todo_card", response_class=PlainTextResponse,
         summary="내 할 일 — 챗봇용 근거 카드(텍스트)",
         description="/todo와 같은 계산을 LLM이 옮겨 쓰기 좋은 한국어 텍스트로 돌려준다. 카드에 없는 날짜·조건은 답하지 말 것.")
def todo_card(dept: str, term: str = S.DEFAULT_TERM, enroll_status: Optional[Literal["재학", "휴학", "수료"]] = None,
              admission_year: Optional[int] = None, advisor: Optional[str] = None, today: date = Depends(today_param)):
    dept_check(dept)
    return S.todo_card_text(S.todo(GR.g, dept, today, term, enroll_status, admission_year, advisor))


@app.get("/deadlines", operation_id="get_upcoming_deadlines", summary="곧 마감되는 일정",
         description="오늘부터 days일 안에 끝나는 졸업 단계. dept를 주면 본부+그 학과, 안 주면 전체 학과.")
def deadlines(days: int = Query(14, ge=1, le=120), dept: Optional[str] = None, today: date = Depends(today_param)):
    if dept:
        dept_check(dept)
    return S.deadlines(GR.g, today, days, dept)


@app.get("/graph", operation_id="get_related_graph", summary="관심사 그래프 (PPR 연관도 + 추천 경로)",
         description="seed 노드에서 Personalized PageRank로 가까운 단계·공지·유의사항을 뽑고, 각 노드에 seed에서 오는 경로(why)를 붙인다. "
                     "seed 예: interest:grad-req, proc:grad:2026-2:korean, stage:2026-2:논문제결과물제출")
def graph(seed: str = "interest:grad-req", k: int = Query(25, ge=5, le=80), today: date = Depends(today_param)):
    try:
        return S.graph_view(GR.g, seed, today, k)
    except KeyError:
        raise HTTPException(404, f"그래프에 없는 노드: {seed}")


@app.get("/notices", operation_id="list_notices", summary="공지 목록 (공지함)",
         description="재게시는 대표 공지 하나로 묶어서 돌려준다(reposts=묶인 개수). dept를 주면 그 학과+대표 홈페이지 공지.")
def notices(dept: Optional[str] = None, term: Optional[str] = None, q: Optional[str] = Query(None, description="제목 검색어"),
            limit: int = Query(50, ge=1, le=500)):
    return S.notices(GR.g, dept, term, q, True, limit)


@app.get("/popular", operation_id="list_popular_notices", summary="인기 공지 (수집 시점 누적 조회수)")
def popular(limit: int = Query(10, ge=1, le=50), term: Optional[str] = None):
    return S.popular(GR.g, limit, term)


@app.get("/stage/{stage_id:path}", summary="단계 하나의 상세 + 근거 문장")
def stage(stage_id: str, today: date = Depends(today_param)):
    if stage_id not in GR.g or GR.g.nodes[stage_id].get("type") != "Stage":
        raise HTTPException(404, "없는 단계")
    return S.stage_card(GR.g, stage_id, today)


def admin(authorization: str = Header("")):
    tok = os.getenv("RELOAD_TOKEN")
    if not tok or authorization != f"Bearer {tok}":
        raise HTTPException(401, "토큰 필요")


@app.post("/admin/reload", summary="새 그래프 불러오기 (GitHub Actions가 매일 호출)", dependencies=[Depends(admin)])
def reload():
    base = os.getenv("DATA_BASE_URL")  # 예: https://raw.githubusercontent.com/OWNER/REPO/main/data/graph
    if base:
        hdr = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.getenv("GITHUB_TOKEN") else {}
        for fn in ("graph_nodes.jsonl", "graph_edges.jsonl"):
            req = urllib.request.Request(f"{base.rstrip('/')}/{fn}", headers=hdr)
            data = urllib.request.urlopen(req, timeout=30).read()
            tmp = ROOT / "data/graph" / (fn + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(ROOT / "data/graph" / fn)
    return GR.reload()
