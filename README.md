# youtube-digest

A dependency-light tool that keeps you on top of a fast-moving topic on YouTube **without
watching everything**. It searches new videos by keyword, pulls their transcripts, summarizes
each with the Claude CLI, and serves the results in a tiny local web app.

Zero paid API keys: summarization runs through the `claude` CLI (your existing subscription).
Storage is local SQLite. The whole thing is ~500 lines of Python.

```
keywords ─► yt-dlp search ─► transcript fetch ─► claude -p (summarize) ─► SQLite ─► local web UI (:8731)
```

## Why
Following "Claude Code / AI agents / automation" on YouTube means dozens of new videos a week.
Watching them all is impossible; titles alone are noise. This turns the firehose into a scannable
list of summaries you can read in minutes, and remembers what it has already processed.

## Features
- **Keyword collection** with per-keyword caps and a daily new-summary limit (`config.json`).
- **Transcript-based summaries** via the Claude CLI — no per-call API billing.
- **429-resistant**: optionally borrows your browser's logged-in cookies for yt-dlp.
- **Local web UI** on `http://127.0.0.1:8731` — one-click `start.command` / `stop.command`.
- **Idempotent**: already-summarized videos are skipped (SQLite dedup).

## Requirements
- Python 3.10+
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) on PATH
- The [`claude` CLI](https://claude.com/claude-code) on PATH (used for summarization)

```bash
pip install -r requirements.txt
```

## Usage
```bash
python3 collect.py                 # collect + summarize all keywords in config.json
python3 collect.py "Claude Code"   # one-off keyword
python3 app.py                     # serve the web UI at http://127.0.0.1:8731
```
Or double-click `start.command` (macOS) to launch the UI and open it in your browser.

## Configuration (`config.json`)
```json
{
  "keywords": ["AI agent", "Claude Code", "業務自動化"],
  "max_per_keyword": 8,
  "daily_limit": 10,
  "days_back": 7,
  "sub_langs": ["ja", "en"],
  "cookies_from_browser": "safari",
  "transcript_char_limit": 25000,
  "claude_model": ""
}
```
- `cookies_from_browser` — `safari`/`chrome`/`firefox`, or empty to disable (used to dodge yt-dlp 429s).
- `claude_model` — empty uses the CLI default.

## Automating it
Run `collect.py` on a schedule (cron / launchd) to wake up to a fresh digest each morning. The web
app just reads the SQLite DB, so it can stay running.

## Notes
Your collected data lives in `data/digest.db`, which is git-ignored — this repo ships the tool, not
anyone's feed. For personal use; respect YouTube's Terms of Service and each creator's rights.

## License
MIT — see [LICENSE](LICENSE).
