# botNotes Pipeline Specification

> Context file for AI agents. Describes what exists, how it's wired, and why — enough to recreate it from scratch.

---

## Architecture Overview

Three content pipelines feed into a shared cloud backend. Everything ingests locally, runs LLM analysis locally, then pushes output to AWS for email delivery, storage, and dashboard access.

```
 INPUTS                    LOCAL (Linux server)              CLOUD (AWS)
 ─────────────────────     ───────────────────────────       ──────────────────────────
 RSS Feeds (every 10m) ──► poll_feeds.py                ──► DynamoDB (article index)
                                                          │
 Brave News API        ──► generate_report.py            ├──► S3 (reports + transcripts)
                           (qwen3.5:9b via Ollama)       ├──► DynamoDB (report index)
                                                          └──► SES → Email
 YouTube URL           ──► process_youtube.sh
                           yt-dlp → subtitles/Whisper   ──► S3 → DDB → SES → Email
                           gemma4:e2b via Ollama

 Podcast URL           ──► process_podcast.sh
                           yt-dlp → Whisper (CPU)        ──► S3 → DDB → SES → Email
                           gemma4:e2b via Ollama

 Email / Telegram      ──► check_email.py (router)
                           routes URLs to above scripts

 Podcast RSS feeds     ──► check_podcasts.py (monitor)
                           auto-dispatches new episodes
```

**How it ties together:**

- All pipelines share one S3 bucket and one DynamoDB table (`category` + `timestamp#filename` key structure)
- The dashboard (separate service) reads that DynamoDB table to list reports, then fetches `.md` files from S3 for display
- Scripts auto-commit output files to this git repo on every run — GitHub Pages serves them publicly
- Cron on the local server drives all scheduling — no Lambda triggers, no event-driven cloud infrastructure
- Ollama runs persistently on the local machine; Whisper is invoked per-job with `--device cpu` (GPU stays with Ollama)
- OpenRouter is a fallback only — if Ollama is unavailable, any pipeline can route through OpenRouter at runtime

**What runs where:**

| Component | Runs on | Persists to |
|---|---|---|
| LLM inference | Local (Ollama) | — |
| Audio transcription | Local (Whisper CPU) | — |
| Report `.md` files | Local → git | GitHub (public) |
| Reports + transcripts | — | S3 |
| Report index | — | DynamoDB |
| Email delivery | — | SES |
| Dashboard | AWS Lambda | — |

---

## Stack

| Layer | Technology |
|---|---|
| Runtime | Python 3, bash — no containers |
| LLM | Ollama running locally (`localhost:11434`) |
| Transcription | Whisper (`--device cpu` always — GPU is reserved for Ollama) |
| Download | yt-dlp (YouTube + podcast audio) |
| Cloud storage | AWS S3 |
| Cloud index | AWS DynamoDB |
| Email delivery | AWS SES v2 |
| Secrets | `.env` file, loaded manually at script start |

---

## LLM Assignments

| Pipeline | Model | Why |
|---|---|---|
| News Briefing | `qwen3.5:9b` | Needs large context window for 50-100 article list |
| YouTube Analysis | `gemma4:e2b` | Shorter transcripts; fast cold-start (~2 min) |
| Podcast Analysis | `gemma4:e2b` | Same as YouTube |
| Email summarization | `gemma4:e2b` | Inline article summaries, short context |

OpenRouter is a runtime override for any pipeline: `LLM_PROVIDER=openrouter LLM_MODEL=<model> ./_scripts/process_youtube.sh "<URL>"`

---

## Pipeline 1: News Briefing

**File:** `_scripts/generate_report.py` — runs hourly via cron

**Inputs:**
- RSS articles from DynamoDB (written by `poll_feeds.py` every 10 min)
- Brave News API — 7 hardcoded topic queries, 5 results each, freshness: past day
- Last 10 analysis texts from S3 (history context to prevent repeating trends)

**Process:**
1. Load unread RSS articles (`fetched_at >= now-24h`, `reported_at` not set)
2. Fetch Brave News articles not seen before (deduplicated via local SQLite, 7-day window)
3. Merge into a single numbered list `[1]...[N]` — RSS first, then Brave
4. Send full list to `qwen3.5:9b` with analysis prompt
5. Validate output: strip any bullet whose `[N]` citations don't appear in the article index (hallucination filter)
6. Write markdown report, upload to S3, index in DynamoDB, send HTML email
7. Mark all articles as `reported_at = now`
8. Git commit + push the new `.md` file; keep only latest 5 locally

**LLM prompt rules enforced:**
- Every bullet must begin with `[N]` citation(s)
- Topics grouped under `**bold headers**` (e.g. `**AI & Technology**`)
- Each group: 2-4 context sentences, then bullets
- Bullets: 30-50 words — key fact + detail + implication
- Do not invent topics not supported by the article list

**Output format:**
```
# Daily News Briefing — Month DD, YYYY HH:MM

## Analysis & Trends to Watch
[grouped analysis with [N] citations]

---

## Brave News (N articles)
[per-topic tables: title | link]

---

## RSS Feeds (N articles)
[per-feed tables: title | published | link]
```

**S3 layout:**
```
reports/news-briefings/filename.md
transcripts/news-briefings/YYYY/MM/filename.txt   ← analysis text only
articles/news-briefings/YYYY/MM/filename.json      ← full article index
```

---

## Pipeline 2: YouTube Analyzer

**File:** `_scripts/process_youtube.sh` — triggered by URL drop (Telegram or email)

**Inputs:** YouTube URL. Optional: `--music-video` flag routes to music catalog instead.

**Process:**
1. Get video title via `yt-dlp --print "%(title)s"`
2. Try to download auto-generated English VTT subtitles — strip timing/tags, deduplicate repeated lines
3. If no subtitles: download audio, run Whisper (`base` model, CPU)
4. Send cleaned transcript to `gemma4:e2b` with structured output prompt
5. Fallback chain: Ollama → OpenRouter → save raw transcript (never lose data)
6. Upload analysis `.md` + raw transcript to S3, index in DynamoDB, git commit, send HTML email

**Prompt uses assistant prefill** to force the model to start from the right heading rather than adding meta-commentary.

**Output format:**
```
# Video Title

## Summary & Key Takeaways
- 4-6 bullets

## Detailed Notes
[### subheadings, - bullets, **bold key terms**]
```

**S3 layout:**
```
reports/youtube/safe_title.md
transcripts/youtube/YYYY/MM/safe_title.txt
```

---

## Pipeline 3: Podcast Transcriber

**File:** `_scripts/process_podcast.sh` — triggered manually or by `check_podcasts.py` (daily 4am)

**Inputs:** Podcast URL (Apple Podcasts, direct `.mp3`/`.m4a`, or RSS enclosure). Optional env vars: `PODCAST_NAME`, `EPISODE_TITLE` (set by the feed monitor for clean titles).

**Process:**
1. Get episode title (from env vars if set, else `yt-dlp --print`)
2. Download audio: `yt-dlp -x --audio-format mp3`
3. Transcribe: `whisper --model base --device cpu` (~4-5 min per 40-min episode)
4. Send transcript to `gemma4:e2b` with editorial analysis prompt (not a reformat — extract themes, arguments, significance)
5. Fallback chain: Ollama → OpenRouter → save raw transcript
6. Upload to S3, index in DynamoDB, git commit, send HTML email

**Output format:**
```
# Show Name — Episode Title

## Executive Summary
[2-3 paragraph narrative]

## Key Themes & Arguments
### Theme Name
- bullet

## Notable Quotes
- "quote" — Speaker

## Context & Background
[why this topic matters now]

## Key Takeaways
- 5-7 bullets
```

**S3 layout:**
```
reports/podcasts/safe_title.md
transcripts/podcasts/YYYY/MM/safe_title.txt
```

---

## Shared Infrastructure

### DynamoDB — reports table

```
PK (String): category
  Values: "news-briefings" | "youtube" | "podcasts" | "music-video"

SK (String): "YYYY-MM-DDTHH:MM:SSZ#filename.md"

Fields: s3_key, title, date
```

### DynamoDB — RSS table

```
PK (String): feed     (feed name, e.g. "Hacker News")
SK (String): url_hash or timestamp-based key

Fields: link, title, pub_date, description, fetched_at, reported_at
```

### RSS poller

`_scripts/poll_feeds.py` — runs every 10 min, reads `_config/rss_feeds.json`, writes new articles to the RSS DynamoDB table. The briefing generator reads from DDB, not feeds directly.

### Email & URL router

`_scripts/check_email.py` — runs every 5 min, polls Gmail via IMAP, routes URLs:

| URL pattern | Handler |
|---|---|
| `youtube.com` / `youtu.be` | `process_youtube.sh` |
| `youtube.com` + `--music-video` | music catalog branch |
| `podcasts.apple.com` or audio extension | `process_podcast.sh` |
| any other URL | inline Ollama summary via `gemma4:e2b` |

### Podcast feed monitor

`_scripts/check_podcasts.py` — daily 4am, polls `_config/podcast_subscriptions.json`, routes new episodes to `process_podcast.sh` with `PODCAST_NAME` + `EPISODE_TITLE` set.

### Cron schedule

```
*/5 * * * *   check_email.py
*/10 * * * *  poll_feeds.py
0 * * * *     generate_report.py
0 * * * *     email_metrics_report.py
* * * * *     collect_metrics.py
0 4 * * *     check_podcasts.py
0 8 * * *     alerts_cron.py   ← KBBL alerts (separate service)
```

---

## Environment Variables

```bash
EMAIL_ADDRESS=<gmail address for the bot inbox>
EMAIL_APP_PASSWORD=<gmail app password>
MY_EMAIL=<destination email for all output>
TELEGRAM_BOT_TOKEN=<telegram bot token>
TELEGRAM_CHAT_ID=<telegram chat id>
BRAVE_API=<brave search api key>
OPENROUTER=<openrouter api key>
AWS_DEFAULT_REGION=us-east-1
```

AWS credentials live in `~/.aws/credentials` (standard profile). All scripts assume `us-east-1` unless noted.

---

## Key Design Decisions

**Whisper must be CPU-only.** The GPU runs Ollama full-time. Running both on GPU causes OOM. Flag: `--device cpu`.

**qwen3.5:9b is non-negotiable for the briefing.** A full article list (50-100 items) exceeds `gemma4:e2b`'s effective context. Smaller model hallucinates or truncates.

**Citation validation is critical.** Without the hallucination filter (strip bullets with out-of-range `[N]`), the model invents plausible-sounding but fabricated stories at ~1 in 10 runs.

**History deduplication prevents stale analysis.** The last 10 analysis texts are injected into the prompt. Without this, the same trends dominate the briefing for days.

**Never lose a transcript.** All three pipelines fall back to raw transcript on LLM failure rather than exiting with an error. The `.md` file is always written.

**Git is the delivery mechanism.** Scripts auto-commit and push. The public repo updates on every run. This makes output accessible via GitHub Pages without a separate deployment step.
