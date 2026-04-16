# XDigestReporter

## Features
- Select the X accounts you want to track.
- Fetch only today's tweets (Asia/Shanghai timezone), up to 20 tweets per account.
- X API cost-saving strategy:
  - Local `user_id` cache (avoid repeated user lookups)
  - Batch username resolution (up to 100 usernames per request)
  - Same-day incremental fetching with `since_id` (fetch only new tweets)
- Output original tweet text and Simplified Chinese translation for each tweet.
- Use GPT-5.3-Codex for account-level summary, evaluation, and key hotspots.
- Generate global hotspot insights.
- Generate both Markdown and LaTeX-compiled PDF reports.
- Support daily scheduled runs (Windows Task Scheduler).
- X API budget gate based on estimated per-request cost.

## Requirements
- X Bearer Token
- Local `codex` command available and authenticated
- Default model: `gpt-5.3-codex`
- LaTeX compiler installed (TeX Live recommended, `xelatex` required in PATH)

## Run
1. Open `XDigestReporter.exe`
2. Fill in X Token (no OpenAI API key required)
3. Select accounts
4. Click "Generate Report Now"

Report output directory: `dist/reports/`

Each run generates 3 files with the same base name:
- `x_digest_*.md`
- `x_digest_*.tex`
- `x_digest_*.pdf` (compiled by LaTeX, includes date and watermark `Jinge Guo專用`)

## Build
```powershell
cd E:\XDigestReporter
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Executable: `E:\XDigestReporter\dist\XDigestReporter.exe`
