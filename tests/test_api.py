"""API 계약 테스트 — 그래프가 매일 바뀌어도 깨지면 안 되는 것만 본다.  실행: pytest -q"""
from fastapi.testclient import TestClient

from api.main import app

c = TestClient(app)
T = "2026-11-24"


def test_health():
    r = c.get("/health").json()
    assert r["ok"] and r["stages"] > 0


def test_todo_dept_overrides_central():
    r = c.get("/todo", params={"dept": "korean", "today": T}).json()
    keys = [i["key"] for i in r["items"]]
    assert keys.count("논문제결과물제출") == 1               # 본부 것은 빠지고 학과 것 하나만
    sub = next(i for i in r["items"] if i["key"] == "논문제결과물제출")
    assert sub["scope"] == "korean" and sub["overrides_central"]
    assert all(i["status"] != "마감" for i in r["items"])
    assert r["items"] == sorted(r["items"], key=lambda i: (i["hi"] or i["lo"] or "9999", i["label"]))


def test_todo_advisor_filter():
    no = c.get("/todo", params={"dept": "korean", "today": T}).json()
    yes = c.get("/todo", params={"dept": "korean", "advisor": "권성우", "today": T}).json()
    assert no["advisor_specific"]["count"] >= 1
    assert any("권성우" in (i["target"] or "") for i in yes["items"])
    assert not any("김한성" in (i["target"] or "") for i in yes["items"])


def test_profile_hides_other_status():
    r = c.get("/todo", params={"dept": "history", "enroll_status": "재학", "admission_year": 2022, "today": T}).json()
    labels = [i["label"] for i in r["items"]]
    assert "수료생 졸업신청" not in labels and "정보인증제 등록" not in labels


def test_every_dated_item_has_source():
    r = c.get("/todo", params={"dept": "ds", "today": T}).json()
    assert all(i["sources"] for i in r["items"] if i["hi"] or i["lo"])


def test_card_text():
    t = c.get("/todo/card", params={"dept": "fn", "today": T}).text
    assert t.startswith("[근거 카드] 식품영양학과") and "출처:" in t


def test_deadlines_window():
    r = c.get("/deadlines", params={"days": 10, "today": T}).json()
    assert all(T <= i["hi"][:10] <= "2026-12-04" for i in r["items"])


def test_graph_and_errors():
    g = c.get("/graph", params={"seed": "interest:grad-req", "k": 10, "today": T}).json()
    assert g["nodes"] and all("why" in n for n in g["nodes"])
    assert c.get("/todo", params={"dept": "zzz"}).status_code == 404
    assert c.post("/admin/reload").status_code == 401


def test_feed_cards():
    r = c.get("/feed", params={"dept": "korean", "enroll_status": "재학", "today": T}).json()
    assert r and all(set(x["badges"]) <= {"새소식", "신청 가능", "지난 일정", "정리 대기"} for x in r)
    m = c.get("/feed", params={"dept": "korean", "ids": "notice:main:96120", "today": T}).json()[0]
    sub = next(s for s in m["stages"] if s["label"] == "졸업논문제 결과물 제출")
    assert sub["dept_override"] and "12-23" in sub["dept_override"]["period"]   # 본부 공지에도 내 학과 마감을 같이 보여줌


def test_web_page():
    assert c.get("/").status_code == 200 and "시그마" in c.get("/").text
