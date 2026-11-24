# 시그마(snowtice) 졸업 공지 데이터 파이프라인

2026-11-24 · 확정 흐름으로 다시 정리한 판

## 1. 흐름 (확정)

```
모든 공지 ─▶ ⓪ 제목으로 같은 글 묶기 ─▶ ①② 대표 공지만 본문 수집(raw) ─▶ ③ LLM 추출(JSON+근거) ─▶ ④ 코드 검증
          ─▶ ⑤ 그래프 하나 (원본) ─┬▶ ⑥ 위키 md (템플릿) ─▶ ⑧ SNOWCHAT Agent A (누구에게나 같은 답)
                                   └▶ MySQL graph_node·graph_edge ─▶ 웹 전체 + SNOWCHAT Agent B (개인화·모으기·관계)
                                   ⑦ 린트: 날짜·문의처 충돌, 끌 파일, 수집 대기
```

- **데이터는 나누지 않는다.** 모든 공지가 그래프에 들어가고, 위키도 모든 절차에 대해 그래프에서 만든다. 나뉘는 건 **질문**이다.
- **위키는 손으로 쓰지 않는다.** 그래프 값을 템플릿에 채워 찍는다. 그래야 공지가 바뀌어도 SNOWCHAT과 웹이 같은 날짜를 말한다.
- **⓪은 흐름을 바꾸는 게 아니라 읽을 양을 줄이는 준비 단계다.** 학과 게시판 글의 대부분이 본부 공지 재게시라서 493건 → 대표 138건만 본문을 받는다.

## 2. 폴더

```
sigma/
├─ run_all.sh                 매일 실행 (①~⑦)
├─ crawler/
│  ├─ crawl.py                ①② 목록→상세→ data/raw/{source}_{no}/ (meta.json·page.html·text.txt·files/, 수정되면 v2/)
│  ├─ sites.yaml              대표 홈페이지·수학과·고정 안내 + 졸업 키워드 필터
│  ├─ sites_depts.yaml        학과 게시판 46곳 (엔진: 학교 CMS 31 · k2web 6 · 기타 9)
│  ├─ browser_uscan.min.js    브라우저 콘솔용 학과 게시판 스캐너
│  └─ aggregate_dept_scan.py  학과 스캔 합치기
├─ pipeline/
│  ├─ group.py                ⓪ 같은 글 묶기 (H0 바코드로 임계값) → fetch_queue.csv
│  ├─ extract.py              ③ LLM 추출 (★ 공급자만 정하면 됨) · extract_prompt.md
│  ├─ verify.py               ④ 근거 문장 원문 대조 · 요일 대조 · 시작≤종료
│  ├─ build_graph.py          ⑤ 그래프 (entities.yaml = 학과·부서 사전)
│  ├─ load_mysql.py           ⑤ graph_node·graph_edge 적재 (ERD v2 칼럼 확인 필요)
│  ├─ render.py               ⑥ 위키 md
│  ├─ lint.py                 ⑦ 점검
│  ├─ query.py                웹 API·Agent B용 질의 (할 일·마감 임박·연관)
│  ├─ graphio.py              그래프 읽기·날짜 표시 공통 함수
│  └─ split_gold.py           (1회) 수작업 정답 추출을 공지별 JSON으로 나눔
├─ templates/procedure.md.j2, rules.md.j2
├─ data/
│  ├─ raw/        공지 목록 493건 · 학과 스캔 · (본문은 crawl.py 실행 후)
│  ├─ extracted/  공지별 추출 JSON 15건 + _verify.json
│  ├─ gold/       수작업 정답 (LLM 추출 정확도 측정용)
│  └─ graph/      graph_nodes/edges.jsonl · graph_load.sql · notice_clusters · fetch_queue · h0_barcode
└─ wiki/
   ├─ SCHEMA.md   페이지 규칙
   ├─ pages/      SNOWCHAT 지식 파일 22개
   ├─ index.md    켤 파일 / 끌 파일
   ├─ log.md      바뀐 파일 기록
   └─ lint_report.md  (팀 내부용)
```

## 3. 지금 결과 (2026-11-24 기준)

| 단계 | 결과 |
|---|---|
| ⓪ 묶기 | 493건 → 138묶음 (본부 21 · 학과 자체 96 · 본부 원본 미수집 6 · 대학원 보류 15). 임계값 ε*=0.566 (H0 바코드 최대 틈) |
| ①② 본문 | **2026-2·2027-1 대표 공지 36건 전부** 내장 브라우저로 수집 (19개 학과, 그누보드·KBoard 3건 포함). 원문 메타·해시는 `data/raw/{key}/meta.json` |
| ③④ 추출·검증 | 51건 (기존 15 + 신규 36, 신규는 Claude 직접 추출 → `work/compact/` → `pipeline/from_compact.py`). 근거 문장은 브라우저에서 원문과 전부 대조. 요일 검사에서 원문 오류 1건 발견(역사문화 '12/27(금)' → 실제 일요일) |
| ⑤ 그래프 | 노드 839 · 간선 1709. 단계 129개 중 **날짜 있는 것 68개** (전 18개). 학과 우선 마감(OVERRIDES) 11개 |
| ⑥ 위키 | 23개 (학과 페이지 20개) |
| ⑦ 린트 | 학과 마감 ≠ 본부 11건 · 검증 실패 1건 · 문과대학 문의 번호 충돌 · 날짜 없는 단계 5건 |

남은 것: 2026-1·2025-2(지난 학기) 대표 공지 76건은 아직 본문 미수집 — 유효기간이 지나 서비스 답변에는 영향 없고, '작년엔 언제였나' 참고용.

## 4. 다음 할 일

1. **본문 수집** — `python crawler/crawl.py --topic graduation --with-depts --only-queue data/graph/fetch_queue.csv` (학교 CMS·k2web 37곳. 그누보드·KBoard·자체 CMS 9곳은 어댑터 추가)
2. **추출 LLM 정하기** → `extract.py`의 `call_llm()`만 채우면 됨. gold 15건으로 정확도 먼저 잼
3. **ERD v2 칼럼 확인** → `load_mysql.py`의 표 정의 맞추기
4. 첨부(PDF) 처리 허락 → 수학과 졸업시험 면제 조건, 학번별 졸업학점
5. 같은 흐름으로 장학·진로 행사 분야 추가 (단계 키·템플릿만 추가)

## 5. 매일 새벽 자동 갱신 (GitHub Actions)

```
03:00 KST  .github/workflows/daily.yml 실행 (GitHub 서버)
  ① crawl --phase list   게시판 목록만 훑기 (빠름, 새 글 찾기)
  ② build_index → group  제목으로 같은 글 묶기 (대표 글만 남김)
  ③ crawl --phase detail 대표 글 중 '내용이 바뀐 것'만 본문 저장 (v2, v3…)
  ④ extract → verify     LLM 추출, 원문 근거 검사
  ⑤ build_graph          그래프(진실의 원천) 다시 계산
  ⑥ render → lint        위키 md 생성, 충돌 보고서
  ⑦ gate.py              어제보다 공지 20%↓·날짜 단계↓·검증 실패 30%↑ → 중단 (어제 것 유지)
  ⑧ main에 커밋          바뀐 게 있을 때만 "daily: 날짜"
  ⑨ snowchat-wiki 브랜치 wiki/pages만 올림 → SNOWCHAT이 이 브랜치를 읽음
  ⑩ 백엔드 알림           BACKEND_RELOAD_URL로 POST → 백엔드가 graph_*.jsonl을 MySQL에 적재
  실패 시                GitHub 이슈 자동 생성
```

### 처음 한 번 설정
1. GitHub에 **private** 저장소 만들고 이 폴더를 push (`.env`는 .gitignore로 제외됨)
2. Settings → Secrets and variables → Actions 에 등록
   - `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (추출 LLM, 정해지면)
   - `BACKEND_RELOAD_URL`, `BACKEND_TOKEN` (백엔드 알림, 선택)
   - `MYSQL_DSN` (Actions에서 DB에 바로 넣고 싶을 때만, 선택)
3. Settings → Actions → General → Workflow permissions: **Read and write**
4. Actions 탭 → daily-update → **Run workflow** 로 수동 실행해서 학교 사이트 접속이 되는지 확인
5. SNOWCHAT GitHub 연동에서 저장소 = 이 저장소, 브랜치 = `snowchat-wiki` 선택

### 주의
- GitHub cron은 UTC 기준이고, 몰리는 시간엔 늦게 시작되거나 건너뛸 수 있음 → 정시가 중요하면 팀 서버 cron에서
  `gh api repos/OWNER/REPO/dispatches -f event_type=daily-update` 로 깨우기
- 60일 동안 저장소 활동이 없으면 예약 실행이 꺼짐 → 매일 커밋이 생기면 문제 없음, 방학 중엔 확인
- 학교 사이트가 해외(GitHub) IP를 막으면 `runs-on: self-hosted` 로 바꾸고 팀 서버(국내)에 러너 설치
- 수집 간격 1~1.5초, robots.txt 준수, 첨부파일(`/_attach/`)은 받지 않음

## 6. 웹·SNOWCHAT 연결 (API 서버)

```
매일 새벽 Actions ─▶ main에 데이터 커밋 ─┬▶ snowchat-wiki 브랜치   → SNOWCHAT 에이전트 A (공통 안내)
                                         ├▶ snowchat-agent-b 브랜치 → SNOWCHAT 에이전트 B (B안: API 호출 불가 시)
                                         └▶ Render 자동 재배포 → API 서버 (api/) ─┬▶ 웹사이트 화면
                                                                                   └▶ SNOWCHAT 에이전트 B (A안: 도구 호출)
```

- `api/main.py` — FastAPI. `/todo`, `/todo/card`, `/deadlines`, `/graph`, `/notices`, `/popular`, `/stage/{id}`, `/depts`, `/admin/reload`
- `api/README.md` — 웹 화면별로 어떤 주소를 부르는지
- `snowchat/README.md` — 에이전트 A·B 지시문, A안/B안, `openapi_tools.json`(도구 등록용 명세)
- `pipeline/agent_cards.py` — B안용 학과별 할 일·마감 md
- `tests/test_api.py` — API 계약 테스트 (Actions에서 매일 돌림)

### 로컬에서 바로 보기
```bash
pip install -r requirements-api.txt
uvicorn api.main:app --reload        # → http://localhost:8000/docs
```

### 배포 (무료, 클릭 몇 번)
1. 이 저장소를 GitHub에 올린다.
2. render.com 가입 → New → **Blueprint** → 저장소 선택 → `render.yaml`대로 `sigma-graph-api`가 만들어짐
3. 발급된 주소(예: `https://sigma-graph-api.onrender.com`)를
   - 웹 프론트의 `API` 상수에,
   - `snowchat/openapi_tools.json`의 `servers.url`에 넣는다.
4. (선택) Render의 `RELOAD_TOKEN` 값을 GitHub Secrets `BACKEND_TOKEN`에, `https://주소/admin/reload`를 `BACKEND_RELOAD_URL`에 넣으면 재배포 없이도 즉시 반영.
- 무료 플랜은 15분 동안 요청이 없으면 잠들어서 첫 요청이 30초쯤 걸린다. 시연 전에 한 번 열어 두거나 유료/학교 서버로 옮긴다.
