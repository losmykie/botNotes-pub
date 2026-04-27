# Pipeline Guide: From Zero to MVP

A complete implementation guide for the three core pipelines in the Sector 7G automated intelligence system. Each section walks through exactly what the code does, what infrastructure you need, and how to get something running.

---

## What You're Building

Three fully automated pipelines that run without intervention:

| Pipeline | Trigger | Input | Output |
|---|---|---|---|
| **News Briefing** | Hourly cron | RSS feeds + Brave News API | AI-analyzed briefing → email + cloud storage |
| **YouTube Analyzer** | Drop URL in Telegram or email | YouTube URL | Structured notes → email + cloud storage |
| **Podcast Transcriber** | Drop URL, or automatic from feed | Podcast URL or audio file | Transcript + analysis → email + cloud storage |

All three share the same stack: local Ollama inference, AWS for email and storage, Python 3, and bash.

---

## Prerequisites

### System

- Linux host (Ubuntu or Fedora — scripts use `dnf` references in comments, adapt for your distro)
- Python 3.10+
- `git`, `curl` installed

### System-level tools (install via package manager, not pip)

```bash
# Ubuntu
sudo apt install ffmpeg yt-dlp

# Fedora
sudo dnf install ffmpeg yt-dlp
```

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` minimum:

```
boto3
requests
openai-whisper
psutil
matplotlib
```

### Ollama

Install from [ollama.com](https://ollama.com) and pull the models:

```bash
ollama pull gemma4:e2b     # YouTube, podcasts, email summarization
ollama pull qwen3.5:9b     # News briefing (large context window needed)
```

Verify Ollama is running on `localhost:11434`:

```bash
curl http://localhost:11434/api/tags
```

### AWS

You need an AWS account with these services configured:

| Service | Purpose |
|---|---|
| S3 | Stores reports, transcripts, article indexes |
| DynamoDB | Indexes reports for dashboard retrieval |
| SES | Sends email — verify your sending domain first |

AWS credentials go in `~/.aws/credentials` (standard profile format). Region: `us-east-1` is hardcoded in the scripts — change if needed.

### Environment file

Create `.env` in the repo root. **Never commit this file.**

```bash
# Email routing
EMAIL_ADDRESS=<your-gmail-address>
EMAIL_APP_PASSWORD=<your-gmail-app-password>
MY_EMAIL=<your-personal-email>

# Telegram (optional — for URL routing)
TELEGRAM_BOT_TOKEN=<your-telegram-bot-token>
TELEGRAM_CHAT_ID=<your-telegram-chat-id>

# Brave News API (optional — needed for news briefing Brave section)
BRAVE_API=<your-brave-api-key>

# OpenRouter (optional — fallback LLM if Ollama fails)
OPENROUTER=<your-openrouter-api-key>

# AWS
AWS_DEFAULT_REGION=us-east-1
```

Scripts load `.env` manually at startup — no `python-dotenv` needed.

---

## Pipeline 1: News Briefing

**Script:** `_scripts/generate_report.py`
**Cron:** `0 * * * *` (every hour)
**Model:** `qwen3.5:9b` (needs the large context window for a full article list)

### What it does, step by step

**Step 1 — Load RSS articles from DynamoDB**

Scans the RSS DynamoDB table for articles where `reported_at` does not exist (unread) and `fetched_at >= now - 24h`. The 24-hour window prevents the same articles cycling back on every run. Results are grouped by feed name for later rendering.

A separate script (`poll_feeds.py`) runs every 10 minutes and writes fresh RSS articles into this table. The briefing generator just reads from it.

**Step 2 — Fetch Brave News**

Hits the Brave News API across seven hardcoded topic queries:

```
Top Headlines, AI News, Anthropic, OpenAI, AWS, Apple, Iran / Middle East
```

Returns up to 5 results per topic. Results are stored in a local SQLite DB (`brave_articles.db`) to prevent the same URL being reported twice. A 7-day pruning window keeps the DB clean.

If `BRAVE_API` is not set, this step is silently skipped.

**Step 3 — Load analysis history from S3**

Fetches the last 10 analysis text files from S3 (`transcripts/news-briefings/YYYY/MM/`). These are injected into the LLM prompt as context under the instruction *"do NOT repeat these trends"* — so the model doesn't just write the same briefing every hour when the news cycle is slow.

**Step 4 — Build the unified article list**

RSS and Brave articles are merged into a single numbered list:

```
[1] [RSS/Hacker News] Article title | description snippet
[2] [Brave/AI News] Article title | description snippet
...
```

Each article gets a sequential number `[N]` that the LLM must use as a citation in its output.

**Step 5 — Generate AI analysis**

Sends the full numbered list to `qwen3.5:9b` via Ollama's `/api/chat` endpoint with a 600-second timeout. The prompt enforces:

- Every bullet must begin with `[N]` citation(s) — no uncited bullets
- Topics must be grouped under `**bold headers**` (e.g. `**AI & Technology**`)
- Each group gets 2-4 sentences of context, then individual bullets
- Bullets are 30-50 words each: key fact + detail + implication
- No invented topics — only groups supported by the article list

After generation, a validation pass strips any bullet whose citation numbers don't appear in the article index. This kills hallucinated claims.

**Step 6 — Write the report file**

Writes a markdown file to `_reports/Daily_News_Briefing_MONTH_DD_YYYY_HHMM.md`. Structure:

```markdown
# Daily News Briefing — April 25, 2026 10:00

## Analysis & Trends to Watch
[AI-generated grouped analysis with [N] citations]

---

## Brave News (34 articles)
[Topic tables with title + link]

---

## RSS Feeds (N articles)
[Per-feed tables with title + date + link]
```

**Step 7 — Upload to S3 and index in DynamoDB**

Three uploads per run:
1. `reports/news-briefings/filename.md` — the full report (retrieved by the dashboard)
2. `transcripts/news-briefings/YYYY/MM/filename.txt` — analysis text only (used as history context in future runs)
3. `articles/news-briefings/YYYY/MM/filename.json` — the full article index with URLs and metadata

DynamoDB record:

```
PK: category = "news-briefings"
SK: "YYYY-MM-DDTHH:MM:SSZ#filename.md"
Fields: s3_key, title, date
```

**Step 8 — Prune local reports**

Keeps only the 5 most recent `.md` files in `_reports/`. Older ones are deleted. S3 and DynamoDB retain the full history.

**Step 9 — Send HTML email**

Builds a styled HTML email with:
- Yellow header bar (`#FEEE91`) with article count
- Source pills (RSS count, Brave count)
- AI analysis rendered with Sky Blue (`#8CE4FF`) accents and clickable citation superscripts
- Article tables per feed (RSS) and per topic (Brave)
- Sent via AWS SES v2

**Step 10 — Mark articles as reported**

Updates `reported_at` on every RSS article in DynamoDB and every Brave URL in SQLite. They won't appear in future runs.

**Step 11 — Git commit and push**

Auto-commits the new `.md` file to the repo with identity `mrSmither <your-bot-email@gmail.com>` and pushes. This is how the public repo gets updated automatically.

---

### MVP minimum for this pipeline

1. Set up `poll_feeds.py` cron to populate the RSS DynamoDB table
2. Configure `.env` with `BRAVE_API` (free tier works)
3. Pull `qwen3.5:9b` in Ollama
4. Create the S3 bucket and DynamoDB table
5. Run manually: `python3 _scripts/generate_report.py`

You can skip SES initially — the markdown file is written locally regardless. Wire up email once the analysis quality looks good.

---

## Pipeline 2: YouTube Analyzer

**Script:** `_scripts/process_youtube.sh`
**Trigger:** Manual, via email, or via Telegram URL drop
**Model:** `gemma4:e2b` (default, overridable)

Pass a YouTube URL to analyze it, or pass `--music-video` to skip analysis and route it to a music catalog instead.

### What it does, step by step

**Step 1 — Get the video title**

```bash
python3 -m yt_dlp --print "%(title)s" "$URL"
```

The raw title is sanitized into a filename-safe string (`spaces and special chars → underscores`). This becomes the output filename base.

**Step 2 — Download subtitles**

Tries auto-generated English subtitles first:

```bash
python3 -m yt_dlp --write-auto-subs --sub-lang en --sub-format vtt \
  --skip-download -o "$VTT_BASE.%(ext)s" "$URL"
```

If the `.vtt` file exists, it strips all timing lines, position tags, and WEBVTT headers, then deduplicates consecutive identical lines (auto-subs repeat heavily). The clean transcript goes to `_tmp/transcript_TIMESTAMP.txt`.

If no subtitles exist, falls back to Whisper:

```bash
python3 -m whisper "$AUDIO_FILE" --model base --device cpu \
  --output_format txt --output_dir "$TMP_DIR"
```

Whisper must run with `--device cpu` — the GPU is occupied by Ollama. Cold-start adds ~2 minutes.

**Step 3 — LLM analysis**

Sends the transcript to Ollama with a strict output format:

```
# Video Title

## Summary & Key Takeaways
(4-6 bullets — main topics, arguments, conclusions)

## Detailed Notes
(Section-by-section breakdown with ### subheadings, - bullets, **bold key terms**)
```

The prompt uses an "assistant prefill" trick — seeding the assistant turn with `# Video Title\n\n## Summary & Key Takeaways\n` to force the model to start from the right place rather than opening with meta-commentary.

If Ollama fails, falls back to OpenRouter (`xiaomi/mimo-v2-pro`). If both fail, saves the raw transcript instead of losing the data.

**Step 4 — Upload to S3**

Two objects:
1. `transcripts/youtube/YYYY/MM/safe_title.txt` — raw transcript
2. `reports/youtube/safe_title.md` — the LLM-formatted analysis

DynamoDB record:

```
PK: category = "youtube"
SK: "YYYY-MM-DDTHH:MM:SSZ#safe_title.md"
Fields: s3_key, title, date
```

**Step 5 — Cleanup**

Deletes the transcript from `_tmp/`. The `_tmp/` directory is gitignored and used only as a staging area.

**Step 6 — Git commit and push**

Auto-commits `_media/youtube/safe_title.md` to the repo and pushes.

**Step 7 — Send HTML email**

Formatted email with the full analysis. The `md_to_html()` function inside the script handles the conversion — headings, bullet lists with Sky Blue dot indicators, bold terms.

### LLM override at runtime

```bash
LLM_PROVIDER=openrouter LLM_MODEL=deepseek/deepseek-v3.2 \
  ./_scripts/process_youtube.sh "https://youtube.com/watch?v=..."
```

### Music video mode

Pass `--music-video` to skip the LLM entirely and route to a separate S3 bucket for video storage:

```bash
./_scripts/process_youtube.sh --music-video "https://youtube.com/watch?v=..."
```

Downloads the full video + thumbnail, uploads to a second S3 bucket (`eu-north-1`), indexes in DynamoDB as `music-video`, sends a confirmation email.

---

### MVP minimum for this pipeline

1. Install `yt-dlp` and `ffmpeg` system-wide
2. Pull `gemma4:e2b` in Ollama
3. Set up the S3 bucket and DynamoDB table
4. Run: `./_scripts/process_youtube.sh "https://youtube.com/watch?v=..."`

The script writes to `_media/youtube/` locally regardless of S3 success. You can test the full analysis chain without AWS — just remove or skip the upload step.

---

## Pipeline 3: Podcast Transcriber

**Script:** `_scripts/process_podcast.sh`
**Trigger:** Manual URL drop, email, or automatic from feed monitor (`check_podcasts.py`)
**Model:** `gemma4:e2b` (default, overridable)

### What it does, step by step

**Step 1 — Get the podcast title**

If triggered by the feed monitor (`check_podcasts.py`), it sets `PODCAST_NAME` and `EPISODE_TITLE` env vars before calling this script. The script uses those to build a display title like `Show Name — Episode Title`.

If called manually, it falls back to `yt-dlp --print "%(title)s"` against the URL.

**Step 2 — Download audio**

```bash
python3 -m yt_dlp "$URL" -x --audio-format mp3 -o "$AUDIO_FILE"
```

Works with Apple Podcasts URLs, direct `.mp3` / `.m4a` links, and most podcast RSS enclosures. The `-x` flag extracts audio and converts to mp3.

**Step 3 — Transcribe with Whisper**

```bash
python3 -m whisper "$AUDIO_FILE" --model base --device cpu \
  --output_format txt --output_dir "$TMP_DIR"
```

This is the slowest step. Budget ~4–5 minutes per 40-minute episode on a CPU-only machine. The `base` model is used for speed — swap to `small` or `medium` for better accuracy if you have the patience.

`--device cpu` is mandatory if Ollama is using the GPU. Running both on the GPU causes OOM errors.

**Step 4 — LLM analysis**

The podcast prompt is deliberately different from the YouTube prompt. It asks for editorial analysis, not just a structured summary:

```
# Show — Episode Title

## Executive Summary
(2-3 paragraph narrative — what was discussed, why it matters, overall tone)

## Key Themes & Arguments
(For each major theme: ### subheading, position taken, evidence, your analysis. Bullets under each ###.)

## Notable Quotes
(3-5 direct quotes that best capture the episode)

## Context & Background
(Why is this topic being discussed now — what events or trends does it connect to)

## Key Takeaways
(5-7 concise bullets — what a busy reader needs to know)
```

OpenRouter fallback works the same as YouTube. Raw transcript saved if both fail.

**Step 5 — Upload to S3**

Two objects:
1. `transcripts/podcasts/YYYY/MM/safe_title.txt` — raw transcript
2. `reports/podcasts/safe_title.md` — analysis

DynamoDB record same schema as YouTube but with `category = "podcasts"`.

**Step 6 — Cleanup**

Deletes the raw transcript from `_tmp/`.

**Step 7 — Git commit and push**

Auto-commits `_media/podcasts/safe_title.md` and pushes.

**Step 8 — Send HTML email**

Same design as the news briefing email — Sky Blue accent, yellow header bar, styled bullet lists.

---

### MVP minimum for this pipeline

1. `yt-dlp` and `ffmpeg` installed
2. Whisper installed (`pip install openai-whisper`)
3. `gemma4:e2b` in Ollama
4. Run: `./_scripts/process_podcast.sh "https://podcasts.apple.com/..."`

Expect the first run to be slow — Whisper downloads the model on first use (~150MB for `base`).

---

## Shared Infrastructure

### DynamoDB table schema

One table handles all report types.

```
Table: <your-reports-table-name>

PK (String): category
  Values: "news-briefings", "youtube", "podcasts", "music-video"

SK (String): "YYYY-MM-DDTHH:MM:SSZ#filename.md"
  Sortable by date, unique per report

Other fields: s3_key, title, date
```

### S3 layout

```
your-s3-bucket/
  reports/
    news-briefings/     ← full briefing .md files
    youtube/            ← YouTube analysis .md files
    podcasts/           ← podcast analysis .md files
  transcripts/
    news-briefings/YYYY/MM/    ← analysis text (used for history context)
    youtube/YYYY/MM/           ← raw VTT or Whisper transcripts
    podcasts/YYYY/MM/          ← raw Whisper transcripts
  articles/
    news-briefings/YYYY/MM/    ← full article index .json files
```

### RSS feed poller

`poll_feeds.py` runs every 10 minutes and writes new articles to DynamoDB. Configure your feed list in `_config/rss_feeds.json`:

```json
[
  {"name": "Hacker News", "url": "https://news.ycombinator.com/rss"},
  {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/rss.xml"},
  {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"}
]
```

The briefing generator reads from DynamoDB, not the feeds directly — so `poll_feeds.py` must be running before `generate_report.py` will have anything to analyze.

### Git auto-commit identity

Each script commits with a bot identity. Set these in the script or via environment:

```bash
GIT_AUTHOR_NAME="your-bot-name"
GIT_AUTHOR_EMAIL="your-bot-email@gmail.com"
GIT_COMMITTER_NAME="your-bot-name"
GIT_COMMITTER_EMAIL="your-bot-email@gmail.com"
```

SSH key must be loaded for `git push` to work without a password prompt. Test with `ssh -T git@github.com`.

### SES setup

Verify your sending domain in SES before going live. The scripts use SES v2 (`boto3.client('sesv2', ...)`).

```python
ses.send_email(
    FromEmailAddress='botNotes@yourdomain.com',
    Destination={'ToAddresses': ['you@email.com']},
    Content={'Simple': {'Subject': {...}, 'Body': {'Html': {...}}}}
)
```

You'll get a sandbox limit of 200 emails/day initially. Request production access once you've verified the setup.

---

## Getting to MVP

Build in this order. Each step is independently useful.

### Phase 1 — Local analysis (no cloud needed)

1. Set up virtualenv + install deps
2. Install Ollama, pull `gemma4:e2b` and `qwen3.5:9b`
3. Install `yt-dlp` and `ffmpeg`
4. Drop a YouTube URL: `./_scripts/process_youtube.sh "URL"` — output lands in `_media/youtube/`
5. Drop a podcast URL: `./_scripts/process_podcast.sh "URL"` — output in `_media/podcasts/`

This gets you analysis with zero cloud dependency. The `.md` files are immediately readable.

### Phase 2 — Cloud storage and email

6. Create S3 bucket and DynamoDB table
7. Configure AWS credentials
8. Set up SES, verify your sending domain
9. Fill in `.env` with email and AWS settings
10. Run a YouTube or podcast process — should now upload to S3, index in DDB, and email you

### Phase 3 — Automated news briefing

11. Add `BRAVE_API` to `.env` (free tier: [brave.com/search/api](https://brave.com/search/api))
12. Create the RSS feed config in `_config/rss_feeds.json`
13. Set up `poll_feeds.py` on cron: `*/10 * * * * /path/to/poll_feeds.py`
14. Let it run for a cycle or two to populate DynamoDB
15. Run `generate_report.py` manually — check the markdown output
16. Once happy, add it to cron: `0 * * * * /path/to/generate_report.py`

### Phase 4 — URL routing (Telegram or email)

17. Set up the Telegram bot and add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` to `.env`
18. Wire `check_email.py` or the Telegram MCP listener to call the correct script based on URL pattern
19. Test: drop a YouTube link in Telegram, confirm the analysis arrives by email

### Phase 5 — Podcast feed monitor

20. Configure `_config/podcast_subscriptions.json` with your podcast RSS feeds
21. Add `check_podcasts.py` to cron: `0 4 * * * /path/to/check_podcasts.py`
22. It polls feeds daily at 4am, finds new episodes, and calls `process_podcast.sh` automatically

---

## Key Gotchas

**Whisper and Ollama can't share a GPU.** Run Whisper with `--device cpu` always. Whisper cold-start is ~2 min; a 40-min podcast takes ~4-5 min to transcribe on CPU.

**qwen3.5:9b is mandatory for the briefing, not optional.** The news briefing prompt sends 50-100+ articles in one context window. `gemma4:e2b` (smaller model) truncates the context and starts hallucinating. Use `qwen3.5:9b` for `generate_report.py`.

**Brave News deduplication is local, not global.** The 7-day SQLite window prevents the same URL from appearing twice within a week — but if you wipe the DB, URLs can recycle.

**SES sandbox mode blocks non-verified recipients.** While in sandbox, you can only send to email addresses you've individually verified in SES. Request production access early.

**The analysis history loop.** `generate_report.py` loads the last 10 analyses from S3 and injects them into the prompt. This prevents repetition across runs but adds to the prompt length — don't reduce the Ollama timeout below 300s.

**yt-dlp updates break things.** Podcast and YouTube URLs break when sites update their APIs. Run `pip install --upgrade yt-dlp` if downloads start failing — it's almost always a yt-dlp version issue, not a script bug.

**Log rotation.** Scripts append to log files and rotate at 2000 lines. If you're debugging a cron job that's been running for weeks, the earliest entries may have been pruned.
