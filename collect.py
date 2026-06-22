#!/usr/bin/env python3
"""
YouTube ダイジェスト収集スクリプト
キーワードで新着動画を検索 → 字幕取得 → Claude定額枠で要約 → SQLite保存

使い方:
    python3 collect.py                # config.json の全キーワードを収集
    python3 collect.py "Claude Code"  # 単発キーワードを即収集（手動用）
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "digest.db")
CONFIG = os.path.join(BASE, "config.json")

# YouTubeのbot対策(HTTP 429)回避用。ブラウザのログイン済みCookieを使う。
_COOKIE_BROWSER = None


def cookie_args():
    return ["--cookies-from-browser", _COOKIE_BROWSER] if _COOKIE_BROWSER else []


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def init_db():
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            channel TEXT,
            url TEXT,
            published TEXT,
            duration INTEGER,
            keyword TEXT,
            summary TEXT,
            transcript_source TEXT,
            created_at TEXT
        )
    """)
    con.commit()
    return con


def already_have(con, video_id):
    cur = con.execute("SELECT 1 FROM videos WHERE video_id=?", (video_id,))
    return cur.fetchone() is not None


def search_videos(keyword, max_n):
    """yt-dlp の ytsearch でメタデータだけ取得（APIキー不要）"""
    log(f"検索: 「{keyword}」 上位{max_n}本")
    cmd = [
        "yt-dlp",
        f"ytsearch{max_n}:{keyword}",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
    ] + cookie_args()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        log(f"  検索タイムアウト: {keyword}")
        return []
    vids = []
    for line in out.stdout.splitlines():
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        vids.append({
            "video_id": j.get("id"),
            "title": j.get("title", ""),
            "channel": j.get("channel") or j.get("uploader", ""),
            "url": j.get("url") or f"https://www.youtube.com/watch?v={j.get('id')}",
            "duration": j.get("duration") or 0,
        })
    return vids


def fetch_metadata(video_id):
    """公開日など詳細メタを1本分取得"""
    cmd = ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
           "--dump-json", "--skip-download", "--no-warnings"] + cookie_args()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        j = json.loads(out.stdout)
        return {
            "title": j.get("title", ""),
            "channel": j.get("channel") or j.get("uploader", ""),
            "duration": j.get("duration") or 0,
            "upload_date": j.get("upload_date", ""),  # YYYYMMDD
        }
    except Exception:
        return None


def vtt_to_text(vtt_path):
    """VTT字幕からタイムスタンプ・タグを除去してプレーンテキスト化"""
    with open(vtt_path, encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    lines = []
    seen = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT":
            continue
        if "-->" in line or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        # インラインタグ <00:00:00.000> や <c> を除去
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def get_transcript(video_id, sub_langs):
    """字幕（手動優先→自動字幕）を取得してテキスト返却。無ければ None"""
    with tempfile.TemporaryDirectory() as td:
        outtmpl = os.path.join(td, "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", ",".join(sub_langs),
            "--sub-format", "vtt",
            "--skip-download", "--no-warnings",
            "--sleep-subtitles", "1",
            "-o", outtmpl,
        ] + cookie_args()
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # 言語の優先順で最初に見つかったVTTを使う
        for lang in sub_langs:
            for f in os.listdir(td):
                if f.endswith(".vtt") and f".{lang}." in f:
                    text = vtt_to_text(os.path.join(td, f))
                    if text:
                        return text, f"字幕({lang})"
        # 言語指定外でも何かVTTがあれば使う
        for f in os.listdir(td):
            if f.endswith(".vtt"):
                text = vtt_to_text(os.path.join(td, f))
                if text:
                    return text, "字幕(auto)"
    return None, None


SUMMARY_PROMPT = """あなたは優秀な情報キュレーターです。以下はYouTube動画の字幕全文です。
これを日本語で要約してください。出力は必ず次のMarkdown構造に厳密に従うこと:

## 一言で
（この動画が何を言っているか1文で）

## 3行サマリ
- （要点1）
- （要点2）
- （要点3）

## キーポイント
- （重要な具体的内容を5個まで箇条書き。数値・固有名詞・手順は残す）

## 使えるネタ / 学び
- （視聴者が実務や発信に活かせる具体アクションを2〜3個）

前置き・後置きの挨拶は不要。上記見出しだけを出力すること。字幕:
"""


def summarize(transcript, model, char_limit):
    text = transcript[:char_limit]
    cmd = ["claude", "-p", SUMMARY_PROMPT]
    if model:
        cmd += ["--model", model]
    try:
        res = subprocess.run(cmd, input=text, capture_output=True,
                             text=True, timeout=300)
        out = res.stdout.strip()
        return out if out else None
    except subprocess.TimeoutExpired:
        log("  要約タイムアウト")
        return None


def collect(keywords=None):
    global _COOKIE_BROWSER
    cfg = load_config()
    _COOKIE_BROWSER = cfg.get("cookies_from_browser") or None
    con = init_db()
    kws = keywords or cfg["keywords"]
    max_n = cfg.get("max_per_keyword", 5)
    daily_limit = cfg.get("daily_limit", 10)
    days_back = cfg.get("days_back", 7)
    sub_langs = cfg.get("sub_langs", ["ja", "en"])
    model = cfg.get("claude_model", "") or ""
    char_limit = cfg.get("transcript_char_limit", 25000)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    added = 0

    for kw in kws:
        if daily_limit and added >= daily_limit:
            break
        for v in search_videos(kw, max_n):
            if daily_limit and added >= daily_limit:
                log(f"日次上限{daily_limit}本に到達→終了")
                break
            vid = v["video_id"]
            if not vid or already_have(con, vid):
                continue
            meta = fetch_metadata(vid)
            if not meta:
                continue
            # 公開日フィルタ
            ud = meta.get("upload_date", "")
            if ud:
                try:
                    pub = datetime.strptime(ud, "%Y%m%d").replace(tzinfo=timezone.utc)
                    if pub < cutoff:
                        continue
                except ValueError:
                    pass
            log(f"  処理: {meta['title'][:50]}")
            transcript, source = get_transcript(vid, sub_langs)
            if not transcript:
                log("    字幕なし→スキップ")
                continue
            summary = summarize(transcript, model, char_limit)
            if not summary:
                log("    要約失敗→スキップ")
                continue
            con.execute("""
                INSERT OR REPLACE INTO videos
                (video_id,title,channel,url,published,duration,keyword,summary,transcript_source,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                vid, meta["title"], meta["channel"],
                f"https://www.youtube.com/watch?v={vid}",
                ud, meta["duration"], kw, summary, source,
                datetime.now().isoformat(timespec="seconds"),
            ))
            con.commit()
            added += 1
            log(f"    ✓ 要約保存")
    con.close()
    log(f"完了: 新規{added}本を追加")
    return added


if __name__ == "__main__":
    kws = sys.argv[1:] if len(sys.argv) > 1 else None
    collect(kws)
