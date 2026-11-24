#!/usr/bin/env bash
# 매일 새벽 실행하는 전체 흐름 (GitHub Actions도 이 파일을 그대로 부른다)
set -euo pipefail
cd "$(dirname "$0")"
TODAY=${TODAY:-$(TZ=Asia/Seoul date +%F)}

python crawler/crawl.py --phase list --with-depts          # ① 게시판 목록 (학교 CMS·k2web)
python crawler/build_index.py                              #    + 어댑터 없는 9곳은 브라우저 스캔 결과
python pipeline/group.py                                   # ⓪ 제목으로 같은 글 묶기 → fetch_queue.csv
python crawler/crawl.py --phase detail --with-depts --only-queue data/graph/fetch_queue.csv   # ② 대표 공지 본문
python pipeline/extract.py || echo "⚠ 추출 LLM 미설정 또는 실패: 이미 있는 추출 결과로 진행"   # ③
python pipeline/verify.py                                  # ④
python pipeline/build_graph.py                             # ⑤ 그래프
python pipeline/load_mysql.py                              #    SQL 파일 (DB 직접 적재는 MYSQL_DSN 있을 때)
if [ -n "${MYSQL_DSN:-}" ]; then python pipeline/load_mysql.py --dsn "$MYSQL_DSN"; fi
python pipeline/render.py --today "$TODAY"                 # ⑥ 위키 md (SNOWCHAT 에이전트 A)
python pipeline/agent_cards.py --today "$TODAY"            #    학과별 할 일·마감 md (에이전트 B, B안)
python pipeline/lint.py --today "$TODAY"                   # ⑦ 점검
