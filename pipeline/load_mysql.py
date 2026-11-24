"""
그래프 → MySQL graph_node · graph_edge 적재

  python pipeline/load_mysql.py --sql data/graph/graph_load.sql          # SQL 파일만 만들기 (기본)
  python pipeline/load_mysql.py --dsn mysql://user:pw@host:3306/sigma    # 바로 적재 (pymysql 필요)

※ 칼럼은 ERD v2를 확인하기 전의 가정이다. ERD와 다르면 COLUMNS만 고치면 된다.
   graph_node(node_id PK, node_type, label, props JSON, updated_at)
   graph_edge(edge_id PK AUTO, src_id, dst_id, edge_type, props JSON, updated_at)  UNIQUE(src_id, dst_id, edge_type)
매일 실행할 때는 전체를 지우고 다시 넣는다 (수천 건 규모라 증분보다 단순하고 안전).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DDL = """
CREATE TABLE IF NOT EXISTS graph_node (
  node_id    VARCHAR(191) PRIMARY KEY,
  node_type  VARCHAR(40)  NOT NULL,
  label      VARCHAR(500),
  props      JSON,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_node_type (node_type)
);
CREATE TABLE IF NOT EXISTS graph_edge (
  edge_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
  src_id     VARCHAR(191) NOT NULL,
  dst_id     VARCHAR(191) NOT NULL,
  edge_type  VARCHAR(40)  NOT NULL,
  props      JSON,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_edge (src_id, dst_id, edge_type),
  INDEX idx_dst (dst_id, edge_type)
);
"""


def q(s):
    return "NULL" if s is None else "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"


def statements():
    nodes = [json.loads(l) for l in (ROOT / "data/graph/graph_nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    edges = [json.loads(l) for l in (ROOT / "data/graph/graph_edges.jsonl").read_text(encoding="utf-8").splitlines()]
    yield "DELETE FROM graph_edge;"
    yield "DELETE FROM graph_node;"
    for n in nodes:
        nid, typ = n.pop("id"), n.pop("type")
        label = n.get("label") or n.get("title")
        yield f"INSERT INTO graph_node (node_id, node_type, label, props) VALUES ({q(nid)}, {q(typ)}, {q(label)}, {q(json.dumps(n, ensure_ascii=False))});"
    seen = set()
    for e in edges:
        key = (e["src"], e["dst"], e["type"])
        if key in seen:
            continue
        seen.add(key)
        props = {k: v for k, v in e.items() if k not in ("src", "dst", "type")}
        yield f"INSERT INTO graph_edge (src_id, dst_id, edge_type, props) VALUES ({q(e['src'])}, {q(e['dst'])}, {q(e['type'])}, {q(json.dumps(props, ensure_ascii=False))});"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql", default=str(ROOT / "data/graph/graph_load.sql"))
    ap.add_argument("--dsn")
    args = ap.parse_args()
    stmts = list(statements())
    if args.dsn:
        import pymysql
        from urllib.parse import urlparse
        u = urlparse(args.dsn)
        con = pymysql.connect(host=u.hostname, port=u.port or 3306, user=u.username, password=u.password, database=u.path.lstrip("/"), charset="utf8mb4")
        with con.cursor() as cur:
            for s in DDL.strip().split(";"):
                if s.strip():
                    cur.execute(s)
            for s in stmts:
                cur.execute(s)
        con.commit()
        print(f"적재 완료: {len(stmts)}문")
    else:
        Path(args.sql).write_text("SET NAMES utf8mb4;\n" + DDL + "START TRANSACTION;\n" + "\n".join(stmts) + "\nCOMMIT;\n", encoding="utf-8")
        print(f"SQL {len(stmts)}문 → {args.sql}")


if __name__ == "__main__":
    main()
