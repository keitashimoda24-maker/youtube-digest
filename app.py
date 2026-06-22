#!/usr/bin/env python3
"""
YouTube ダイジェスト Webアプリ（localhost専用）
    python3 app.py   → http://127.0.0.1:8731 をブラウザで開く

依存ゼロ（Python標準ライブラリのみ）。収集はバックグラウンドで collect.py を実行。
"""
import html
import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "digest.db")
PORT = 8731

# 収集ジョブの実行状態（簡易・単一プロセス内共有）
_job = {"running": False, "log": "", "last_added": None}


def md_to_html(text):
    """超軽量Markdown→HTML（見出し・箇条書き・改行のみ対応）"""
    out = []
    for line in (text or "").splitlines():
        s = html.escape(line)
        if line.startswith("## "):
            out.append(f"<h4>{html.escape(line[3:])}</h4>")
        elif line.startswith("- "):
            out.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{s}</p>")
    # 連続<li>を<ul>で囲む
    res, in_ul = [], False
    for el in out:
        if el.startswith("<li>"):
            if not in_ul:
                res.append("<ul>")
                in_ul = True
            res.append(el)
        else:
            if in_ul:
                res.append("</ul>")
                in_ul = False
            res.append(el)
    if in_ul:
        res.append("</ul>")
    return "\n".join(res)


def fetch_rows(keyword=None, q=None):
    if not os.path.exists(DB):
        return []
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sql = "SELECT * FROM videos WHERE 1=1"
    args = []
    if keyword and keyword != "__all__":
        sql += " AND keyword=?"
        args.append(keyword)
    if q:
        sql += " AND (title LIKE ? OR summary LIKE ? OR channel LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY created_at DESC"
    rows = con.execute(sql, args).fetchall()
    con.close()
    return rows


def all_keywords():
    if not os.path.exists(DB):
        return []
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT keyword, COUNT(*) c FROM videos GROUP BY keyword ORDER BY c DESC"
    ).fetchall()
    con.close()
    return rows


def run_collect(keyword=None):
    if _job["running"]:
        return
    _job["running"] = True
    _job["log"] = "収集中…（数分かかります）"

    def worker():
        try:
            cmd = [sys.executable, os.path.join(BASE, "collect.py")]
            if keyword:
                cmd.append(keyword)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            tail = "\n".join((p.stdout or "").splitlines()[-3:])
            _job["log"] = tail or "完了"
        except Exception as e:
            _job["log"] = f"エラー: {e}"
        finally:
            _job["running"] = False

    threading.Thread(target=worker, daemon=True).start()


def render_page(keyword=None, q=None):
    rows = fetch_rows(keyword, q)
    kws = all_keywords()
    total = sum(k[1] for k in kws)

    chips = [
        f'<a class="chip {"on" if (keyword in (None,"__all__")) else ""}" href="/?kw=__all__">すべて <b>{total}</b></a>'
    ]
    for k in kws:
        on = "on" if keyword == k[0] else ""
        chips.append(
            f'<a class="chip {on}" href="/?kw={html.escape(k[0])}">{html.escape(k[0])} <b>{k[1]}</b></a>'
        )

    cards = []
    for r in rows:
        dur = r["duration"] or 0
        dur_s = f"{dur//60}:{dur%60:02d}" if dur else ""
        pub = r["published"] or ""
        pub_s = f"{pub[:4]}/{pub[4:6]}/{pub[6:8]}" if len(pub) == 8 else ""
        cards.append(f"""
        <article class="card">
          <div class="meta">
            <span class="kw">{html.escape(r['keyword'] or '')}</span>
            <span class="src">{html.escape(r['transcript_source'] or '')}</span>
            {f'<span class="date">{pub_s}</span>' if pub_s else ''}
          </div>
          <h3><a href="{html.escape(r['url'])}" target="_blank" rel="noopener">{html.escape(r['title'])}</a></h3>
          <div class="ch">{html.escape(r['channel'] or '')}{f' ・ {dur_s}' if dur_s else ''}</div>
          <div class="summary">{md_to_html(r['summary'])}</div>
        </article>""")

    if not cards:
        cards = ['<p class="empty">まだ要約がありません。右上の「今すぐ収集」を押すか、ターミナルで <code>python3 collect.py</code> を実行してください。</p>']

    job_note = f'<div class="job">{html.escape(_job["log"])}</div>' if _job["log"] else ""

    return f"""<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube ダイジェスト</title>
<style>
:root{{--bg:#0f1115;--card:#1a1d24;--fg:#e7e9ee;--mut:#8b90a0;--ac:#4ea1ff;--chip:#252a35;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:-apple-system,system-ui,sans-serif;line-height:1.6}}
header{{position:sticky;top:0;background:rgba(15,17,21,.95);backdrop-filter:blur(8px);padding:16px 20px;border-bottom:1px solid #262b36;z-index:10}}
.topbar{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
h1{{font-size:18px;margin:0}}
form.search{{margin-left:auto;display:flex;gap:8px}}
input[type=text]{{background:var(--chip);border:1px solid #333;color:var(--fg);padding:8px 12px;border-radius:8px;width:220px}}
button{{background:var(--ac);color:#001;border:0;padding:8px 14px;border-radius:8px;font-weight:700;cursor:pointer}}
button.ghost{{background:var(--chip);color:var(--fg)}}
.chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}
.chip{{background:var(--chip);color:var(--fg);text-decoration:none;padding:5px 12px;border-radius:999px;font-size:13px;border:1px solid #2c3240}}
.chip.on{{background:var(--ac);color:#001;font-weight:700}}
.chip b{{opacity:.7;margin-left:4px}}
.job{{margin-top:10px;font-size:12px;color:var(--mut);white-space:pre-wrap}}
main{{max-width:820px;margin:0 auto;padding:20px}}
.card{{background:var(--card);border:1px solid #232834;border-radius:14px;padding:18px 20px;margin-bottom:16px}}
.meta{{display:flex;gap:8px;font-size:12px;color:var(--mut);margin-bottom:6px;flex-wrap:wrap}}
.kw{{color:var(--ac)}}
.card h3{{margin:2px 0 4px;font-size:17px}}
.card h3 a{{color:var(--fg);text-decoration:none}}
.card h3 a:hover{{color:var(--ac)}}
.ch{{font-size:13px;color:var(--mut);margin-bottom:10px}}
.summary h4{{font-size:13px;color:var(--ac);margin:12px 0 4px;text-transform:none}}
.summary ul{{margin:4px 0;padding-left:20px}}
.summary p{{margin:4px 0}}
.empty{{color:var(--mut);text-align:center;padding:60px 0}}
code{{background:var(--chip);padding:2px 6px;border-radius:5px}}
</style></head><body>
<header>
  <div class="topbar">
    <h1>📺 YouTube ダイジェスト</h1>
    <form class="search" method="get" action="/">
      <input type="hidden" name="kw" value="{html.escape(keyword or '__all__')}">
      <input type="text" name="q" placeholder="要約を全文検索…" value="{html.escape(q or '')}">
      <button type="submit">検索</button>
    </form>
    <form method="post" action="/collect" style="display:inline">
      <button class="ghost" type="submit" {"disabled" if _job["running"] else ""}>
        {"収集中…" if _job["running"] else "今すぐ収集"}
      </button>
    </form>
  </div>
  <div class="chips">{''.join(chips)}</div>
  {job_note}
</header>
<main>{''.join(cards)}</main>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            qs = parse_qs(u.query)
            kw = qs.get("kw", [None])[0]
            q = qs.get("q", [None])[0]
            self._send(render_page(kw, q))
        elif u.path == "/status":
            self._send(json.dumps(_job), ctype="application/json")
        else:
            self._send("not found", 404, "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/collect":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length else ""
            kw = parse_qs(body).get("kw", [None])[0]
            run_collect(kw)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._send("not found", 404, "text/plain")

    def log_message(self, *a):
        pass  # アクセスログ抑制


def main():
    print(f"\n  📺 YouTube ダイジェスト起動")
    print(f"  → ブラウザで開く: http://127.0.0.1:{PORT}\n")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
