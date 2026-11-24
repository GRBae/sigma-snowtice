# 웹 프론트 연결 안내 (시그마 그래프 API)

배포 주소를 `API`라고 하면, 웹 화면은 아래만 부르면 된다. 전체 명세는 `{API}/docs` (눌러서 바로 시험 가능).
모든 응답의 날짜는 이미 계산된 표시용 문자열(`period`, `status`)이 같이 오므로 **프론트에서 날짜 계산을 하지 않는다.**

| 화면 (기능명세) | 호출 | 쓸 필드 |
|---|---|---|
| 홈 · 공지함 '신청 가능' | `GET /todo?dept=korean&enroll_status=재학&admission_year=2022` | `items[].label · period · status · d_day · overrides_central · sources[0].url`, `cautions`, `contacts` |
| 지도교수 선택 후 | `…/todo?dept=korean&advisor=권성우` | `advisor_specific`가 null이 되고 그 교수 일정이 `items`에 들어옴 |
| 매일 12:00 알림 | `GET /deadlines?days=7&dept=korean` | `items[]` (비어 있으면 알림 안 보냄) |
| 관심사 그래프 | `GET /graph?seed=interest:grad-req&k=30` | `nodes[]`(id,type,label,score,status,why) · `edges[]`(src,dst,type) → 그래프 라이브러리에 그대로 |
| 공지함 '전체' | `GET /notices?dept=korean&term=2026-2` | `title · posted · board · url · reposts · stages` |
| 인기 게시글 | `GET /popular?limit=10` | `hits · title · url` |
| 단계 상세(모달) | `GET /stage/{stage_id}` | `sources[].evidence` (원문 근거 문장) |
| 학과 선택 드롭다운 | `GET /depts` | `code · name · has_dept_schedule` |

```js
const API = "https://sigma-graph-api.onrender.com";   // 배포 주소로 바꾸기

// 공지함: 내 졸업 할 일
const r = await fetch(`${API}/todo?` + new URLSearchParams({dept: "korean", enroll_status: "재학", admission_year: 2022}));
const todo = await r.json();
todo.items.forEach(i => console.log(i.status, i.label, i.period, i.overrides_central ? "학과 마감 우선" : ""));
if (todo.advisor_specific) showAdvisorPicker(todo.advisor_specific.advisors_in_notices);
```

상태 배지 규칙: `status`가 `진행 중(D-n)` → 초록, `예정(D-n)` 이고 `d_day <= 7` → 주황, `일정 미정` → 회색, `period`에 `[확인 필요]` → 노랑 테두리.

## 백엔드가 따로 있을 때 (Spring 등)
- 그래프 계산은 이 Python 서버가 하고, 백엔드는 로그인·내 라이브러리·알림 발송만 맡는다.
- 백엔드가 이 API를 서버끼리 호출하거나, 프론트가 직접 부른다 (CORS는 `CORS_ORIGINS`로 웹 주소만 허용).
- MySQL에 그래프를 넣어야 하면 `pipeline/load_mysql.py --dsn ...` (ERD v2 칼럼에 맞춰 수정 필요).

## 개인정보
API는 학번·이름을 받지 않는다. `admission_year`(입학 연도)와 학적만 받는다. 로그 저장도 하지 않는다(uvicorn 접근 로그만).
