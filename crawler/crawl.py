"""
snowtice 수집기 (졸업 시범판)

원문층(raw) 하나를 만든다. LLM 위키와 GraphRAG는 모두 이 원문층에서 파생된다.

  목록 페이지 → (분야 필터) → 상세 페이지 → 본문 HTML → 마크다운(표 보존) → data/raw/{source}_{no}/

사용법 (학교 사이트에 접속되는 컴퓨터에서):
  pip install requests beautifulsoup4 pyyaml
  python crawler/crawl.py --topic graduation           # 레지스트리의 게시판 + 고정 페이지
  python crawler/crawl.py --topic graduation --dry-run # 목록만 보고 대상 건수 확인

규칙:
  - robots.txt 때문에 게시판 검색(srSearchVal)을 쓰지 않는다. 목록을 넘기며 제목으로 거른다.
  - 요청 사이 delay_sec 이상 쉰다.
  - 첨부는 이름·번호만 기록하고 내려받지 않는다 (허락 후 attachments.py로 별도 처리).
  - 본문의 이메일 주소는 [이메일]로 가린다 (사이트의 이메일 무단수집 거부 고지).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DATE_RE = re.compile(r"\d{4}[.-]\d{2}[.-]\d{2}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "section", "article", "blockquote", "tr"}


# ---------------------------------------------------------------- HTML → 마크다운
def table_to_md(table: Tag) -> str:
    """rowspan/colspan을 펼쳐서 격자로 만든다. 병합 셀 값을 반복해 넣어야 행마다 의미가 완결된다."""
    grid: list[list[str | None]] = []
    for ri, tr in enumerate(table.find_all("tr")):
        while len(grid) <= ri:
            grid.append([])
        ci = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while ci < len(grid[ri]) and grid[ri][ci] is not None:
                ci += 1
            text = " / ".join(s.strip() for s in cell.get_text("\n").split("\n") if s.strip())
            text = re.sub(r"\s+", " ", text).replace("|", "/")
            rs, cs = int(cell.get("rowspan", 1) or 1), int(cell.get("colspan", 1) or 1)
            for r in range(rs):
                while len(grid) <= ri + r:
                    grid.append([])
                row = grid[ri + r]
                for k in range(cs):
                    while len(row) <= ci + k:
                        row.append(None)
                    row[ci + k] = text
            ci += cs
    if not grid:
        return ""
    width = max(len(r) for r in grid)
    lines = []
    for i, r in enumerate(grid):
        cells = [(r[k] if k < len(r) and r[k] is not None else "") for k in range(width)]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + " --- |" * width)
    return "\n\n" + "\n".join(lines) + "\n\n"


def html_to_md(root: Tag) -> str:
    out: list[str] = []

    def walk(n):
        if isinstance(n, NavigableString):
            out.append(re.sub(r"\s+", " ", str(n)))
            return
        if not isinstance(n, Tag) or n.name in ("script", "style"):
            return
        if n.name == "br":
            out.append("\n"); return
        if n.name == "img":
            out.append(f"[이미지: {n.get('alt')}]" if n.get("alt") else "[이미지]"); return
        if n.name == "table":
            out.append(table_to_md(n)); return
        if n.name == "li":
            out.append("\n- ")
        elif n.name in BLOCK:
            out.append("\n")
        for c in n.children:
            walk(c)
        if n.name in BLOCK:
            out.append("\n")

    walk(root)
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return EMAIL_RE.sub("[이메일]", text)


def norm_hash(md: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", md).strip().encode()).hexdigest()


# ---------------------------------------------------------------- 레코드
@dataclass
class ListRow:
    site_id: str
    article_no: str
    title: str
    category: str | None
    posted: str | None  # YYYY-MM-DD
    pinned: bool


@dataclass
class NoticeVersion:
    site_id: str
    article_no: str
    url: str
    title: str
    category: str | None
    writer: str | None      # 게시판 작성자 = '게시 부서'. 주관 부서는 추출 단계에서 본문으로 따로 뽑는다.
    posted: str | None
    hits: int | None
    attachments: list[dict] = field(default_factory=list)
    body_md: str = ""
    sha256: str = ""
    fetched_at: str = ""
    kind: str = "notice"   # notice | static
    html: str = ""         # 본문 HTML (raw/page.html)


# ---------------------------------------------------------------- 수집기
class Collector:
    def __init__(self, cfg: dict):
        import requests
        self.cfg = cfg
        self.d = cfg["defaults"]
        self.s = requests.Session()
        self.s.headers["User-Agent"] = self.d["user_agent"]
        self._last = 0.0
        self.ca_bundle: dict[str, str] = {}

    def get(self, url: str) -> str:
        wait = self.d["delay_sec"] - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        import requests
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        try:
            r = self.s.get(url, timeout=20, verify=self.ca_bundle.get(host, True))
        except requests.exceptions.SSLError:
            # 중간 인증서를 안 보내는 서버: 브라우저처럼 AIA로 중간 인증서를 받아 '검증을 켠 채' 다시 접속
            from tlsfix import bundle_for
            if host in self.ca_bundle:
                raise
            self.ca_bundle[host] = bundle_for(host)
            print(f"  ℹ {host}: 중간 인증서를 AIA로 보완해 검증 접속")
            r = self.s.get(url, timeout=20, verify=self.ca_bundle[host])
        self._last = time.time()
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    # 목록: 상단 고정글은 매 페이지 반복되므로 중복 제거, 고정글이 아닌 글의 날짜로 중단 판단
    def list_board(self, board: dict, since: str, page_size: int = 50, max_pages: int = 40) -> list[ListRow]:
        rows: dict[str, ListRow] = {}
        for page in range(max_pages):
            url = f"{board['base']}{board['path']}?mode=list&articleLimit={page_size}&article.offset={page * page_size}"
            soup = BeautifulSoup(self.get(url), "html.parser")
            trs = soup.select("table tbody tr")
            if not trs:
                break
            oldest = None
            for tr in trs:
                a = tr.find("a", href=re.compile(r"articleNo="))
                if not a:
                    continue
                no = re.search(r"articleNo=(\d+)", a["href"]).group(1)
                tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                m = DATE_RE.search(tr.get_text(" "))
                posted = m.group(0).replace(".", "-") if m else None
                pinned = bool(tds) and tds[0].startswith("공지")
                cat = tds[1] if len(tds) > 1 and len(tds[1]) <= 6 else None
                rows.setdefault(no, ListRow(board["site_id"], no, a.get_text(" ", strip=True), cat, posted, pinned))
                if not pinned and posted:
                    oldest = posted if oldest is None else min(oldest, posted)
            if oldest and oldest < since:
                break
        return [r for r in rows.values() if (r.posted or "9999") >= since or r.pinned]

    # ---- k2web 엔진 (lis, edu, physics, mse, engine, lcb 등): 목록은 POST page=N, 상세는 /{no}/artclView.do
    def list_board_k2web(self, board: dict, since: str, max_pages: int = 10) -> list[ListRow]:
        rows: dict[str, ListRow] = {}
        url = f"{board['base']}{board['path']}"  # 예: /bbs/physics/701/artclList.do
        for page in range(1, max_pages + 1):
            wait = self.d["delay_sec"] - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            r = self.s.post(url, data={"page": page}, timeout=20)
            self._last = time.time()
            soup = BeautifulSoup(r.text, "html.parser")
            trs = [tr for tr in soup.select("tbody tr") if tr.select_one("a[href*='artclView']")]
            if not trs:
                break
            oldest = None
            for tr in trs:
                a = tr.select_one("a[href*='artclView']")
                no = re.search(r"/(\d+)/artclView", a["href"]).group(1)
                text = tr.get_text(" ", strip=True)
                m = DATE_RE.search(text)
                posted = m.group(0).replace(".", "-") if m else None
                pinned = text.startswith(("공지", "일반공지"))
                title = (tr.select_one("strong") or a).get_text(" ", strip=True)
                rows.setdefault(no, ListRow(board["site_id"], no, title, None, posted, pinned))
                if not pinned and posted:
                    oldest = posted if oldest is None else min(oldest, posted)
            if oldest and oldest < since:
                break
        return [r for r in rows.values() if (r.posted or "9999") >= since or r.pinned]

    def fetch_detail_k2web(self, board: dict, row: ListRow) -> NoticeVersion:
        url = f"{board['base']}{board['path'].replace('artclList.do', '')}{row.article_no}/artclView.do"
        soup = BeautifulSoup(self.get(url), "html.parser")
        body = soup.select_one(".artclView")
        md = html_to_md(body) if body else ""
        title = soup.select_one(".artclViewTitle")
        return NoticeVersion(
            site_id=board["site_id"], article_no=row.article_no, url=url,
            title=title.get_text(" ", strip=True) if title else row.title, category=None, writer=None,
            posted=row.posted, hits=None,
            attachments=[{"name": a.get_text(strip=True), "href": a["href"]} for a in soup.select("a[href*='download.do']")],
            body_md=md, sha256=norm_hash(md), fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            html=str(body) if body else "",
        )

    def fetch_detail(self, board: dict, row: ListRow) -> NoticeVersion:
        if board.get("engine") == "k2web":
            return self.fetch_detail_k2web(board, row)
        url = f"{board['base']}{board['path']}?mode=view&articleNo={row.article_no}"
        soup = BeautifulSoup(self.get(url), "html.parser")
        txt = lambda sel: (soup.select_one(sel).get_text(" ", strip=True) if soup.select_one(sel) else None)
        body = soup.select_one(".b-con-box .fr-view") or soup.select_one(".b-con-box") or soup.select_one(".b-content-box")
        md = html_to_md(body) if body else ""
        hits = txt(".b-hit-box")
        writer = txt(".b-writer-box")
        date = txt(".b-date-box")
        files = [
            {"name": a.get_text(strip=True), "attach_no": re.search(r"attachNo=(\d+)", a["href"]).group(1)}
            for a in soup.select(".b-file-box a[href*='mode=download']")
        ]
        return NoticeVersion(
            site_id=board["site_id"], article_no=row.article_no, url=url,
            title=re.sub(r"^(공지|학사|장학|등록|모집|행정)\s+", "", txt(".b-title-box") or row.title).rstrip(" N"),
            category=row.category,
            writer=writer.replace("작성자", "").strip() if writer else None,
            posted=(DATE_RE.search(date).group(0).replace(".", "-") if date and DATE_RE.search(date) else row.posted),
            hits=int(re.sub(r"\D", "", hits)) if hits and re.search(r"\d", hits) else None,
            attachments=files, body_md=md, sha256=norm_hash(md),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), html=str(body) if body else "",
        )

    def fetch_static(self, page: dict) -> NoticeVersion:
        soup = BeautifulSoup(self.get(page["url"]), "html.parser")
        body = soup.select_one("div.content-box")
        md = html_to_md(body) if body else ""
        return NoticeVersion(
            site_id="static", article_no=page["page_id"], url=page["url"], title=page["name"], category="고정안내",
            writer=None, posted=None, hits=None, body_md=md, sha256=norm_hash(md),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), kind="static",
        )


def matches(title: str, f: dict) -> bool:
    if any(k in title for k in f.get("exclude_keywords", []) + f.get("noise_keywords", [])):
        return False
    return any(t in title for t in f.get("title_tags", [])) or any(k in title for k in f.get("title_keywords", []))


# ---------------------------------------------------------------- 저장 (버전은 덮어쓰지 않고 추가)
def load_known(path: Path) -> dict[tuple[str, str], str]:
    known = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            known[(r["site_id"], r["article_no"])] = r["sha256"]
    return known


SOURCE = {"main_notice": "main", "math_notice": "math"}


def raw_dir(v: NoticeVersion) -> Path:
    return RAW / f"{SOURCE.get(v.site_id, v.site_id)}_{v.article_no}"


def save(v: NoticeVersion, versions_path: Path, md_dir: Path) -> None:
    """원문층 저장: data/raw/{source}_{no}/meta.json · page.html · text.txt (+ files/ 첨부)
    이미 있는 공지가 바뀌면 덮어쓰지 않고 v2/, v3/ … 에 새 버전을 둔다 (변경 알림 근거)."""
    base = raw_dir(v)
    target = base
    if (base / "meta.json").exists():
        n = 2
        while (base / f"v{n}").exists():
            n += 1
        target = base / f"v{n}"
    target.mkdir(parents=True, exist_ok=True)
    meta = {k: getattr(v, k) for k in ("site_id", "article_no", "url", "title", "category", "writer", "posted", "hits",
                                        "attachments", "sha256", "fetched_at", "kind")}
    meta["source"] = SOURCE.get(v.site_id, v.site_id)
    (target / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (target / "page.html").write_text(v.html, encoding="utf-8")
    (target / "text.txt").write_text(v.body_md, encoding="utf-8")
    (target / "files").mkdir(exist_ok=True)  # 첨부는 허락 후 attachments.py가 채움
    with versions_path.open("a", encoding="utf-8") as f:  # 버전 색인 (해시 비교용)
        f.write(json.dumps({"site_id": v.site_id, "article_no": v.article_no, "sha256": v.sha256,
                            "dir": str(target.relative_to(RAW)), "fetched_at": v.fetched_at}, ensure_ascii=False) + "\n")


def load_boards(cfg: dict, with_depts: bool) -> list[dict]:
    """대표 홈페이지·수학과(sites.yaml) + 학과 게시판(sites_depts.yaml, 어댑터 있는 엔진만)"""
    boards = []
    for b in cfg["boards"]:
        src = SOURCE.get(b["site_id"], b["site_id"])
        boards.append({**b, "source": src, "host": b["base"].split("//")[1], "dept": b.get("owner"), "board": b["name"], "engine": "sm_cms"})
    if with_depts:
        dep = yaml.safe_load((Path(__file__).with_name("sites_depts.yaml")).read_text(encoding="utf-8"))
        for b in dep["boards"]:
            if b["engine"] in ("sm_cms", "k2web") and b["site_id"] != "math":
                boards.append({**b, "source": b["site_id"], "host": b["base"].split("//")[1]})
        skipped = [b for b in dep["boards"] if b["engine"] not in ("sm_cms", "k2web")]
        print(f"어댑터 없는 게시판 {len(skipped)}곳은 브라우저 스캔 결과(data/raw/dept_scan) 사용: "
              + ", ".join(f"{b['dept']}({b['engine']})" for b in skipped))
    return boards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).with_name("sites.yaml")))
    ap.add_argument("--topic", default="graduation")
    ap.add_argument("--phase", choices=["list", "detail"], required=True,
                    help="list: 게시판 목록만 → data/raw/list_today.jsonl / detail: 대표 공지 본문 → data/raw/{source}_{no}/")
    ap.add_argument("--with-depts", action="store_true", help="학과 게시판까지")
    ap.add_argument("--only-queue", help="detail 단계: pipeline/group.py가 만든 fetch_queue.csv의 대표 공지만")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    flt = cfg["topic_filters"][args.topic]
    col = Collector(cfg)
    boards = load_boards(cfg, args.with_depts)
    today_list = RAW / "list_today.jsonl"

    if args.phase == "list":
        n_all = n_hit = 0
        failed = []
        with today_list.open("w", encoding="utf-8") as f:
            for b in boards:
                try:
                    lister = col.list_board_k2web if b.get("engine") == "k2web" else col.list_board
                    rows = lister(b, cfg["defaults"]["since"])
                except Exception as e:  # 한 게시판이 죽어도 전체는 계속
                    failed.append(f"{b['source']}({e.__class__.__name__})")
                    continue
                hit = [r for r in rows if matches(r.title, flt)]
                n_all += len(rows); n_hit += len(hit)
                for r in hit:
                    f.write(json.dumps({**asdict(r), "source": b["source"], "host": b["host"], "dept": b.get("dept"),
                                        "board": b["board"], "path": b["path"], "engine": b.get("engine")}, ensure_ascii=False) + "\n")
        print(f"목록 {n_all}건 중 {args.topic} {n_hit}건 → {today_list}  (실패 게시판 {len(failed)}: {', '.join(failed)})")
        if len(failed) > len(boards) // 2:
            raise SystemExit("게시판 절반 이상 실패 → 중단 (사이트 접속 문제 의심)")
        return

    # detail
    versions = RAW / "notice_versions.jsonl"
    known = load_known(versions)
    queue = None
    if args.only_queue:
        import csv as _csv
        queue = {r["rep"] for r in _csv.DictReader(open(args.only_queue, encoding="utf-8-sig")) if not r["kind"].startswith("보류")}
    bmap = {(b["source"], b["board"]): b for b in boards}
    new = changed = same = 0
    for line in today_list.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if queue is not None and f"notice:{d['source']}:{d['article_no']}" not in queue:
            continue
        b = bmap.get((d["source"], d["board"]))
        if not b:
            continue
        row = ListRow(d["site_id"], d["article_no"], d["title"], d.get("category"), d.get("posted"), d.get("pinned", False))
        try:
            v = col.fetch_detail(b, row)
        except Exception as e:
            print(f"  본문 실패 {d['source']}:{d['article_no']} {e.__class__.__name__}")
            continue
        prev = known.get((v.site_id, v.article_no))
        if prev == v.sha256:
            same += 1
            continue
        new += prev is None; changed += prev is not None
        save(v, versions, None)
    for p in cfg.get("static_pages", []):
        if p.get("board"):
            continue
        v = col.fetch_static(p)
        if known.get((v.site_id, v.article_no)) != v.sha256:
            save(v, versions, None)
    print(f"본문: 신규 {new}, 수정 {changed}, 그대로 {same}")


if __name__ == "__main__":
    main()
