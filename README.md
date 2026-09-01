# yamlgraph-daily-digest

A daily tech news bulletin that publishes itself. No servers, no email,
no Docker — a [YAMLGraph](https://github.com/sheikkinen/yamlgraph)
pipeline runs in GitHub Actions every morning at 06:00 UTC and commits
a markdown bulletin back to this repo. The repo is the runtime, the
state store, and the publication channel.

## Latest digests

<!-- digest-index -->
- [2026-09-01](digests/2026-09-01.md)
- [2026-08-30](digests/2026-08-30.md)
- [2026-08-29](digests/2026-08-29.md)
- [2026-08-28](digests/2026-08-28.md)
- [2026-08-27](digests/2026-08-27.md)
- [2026-08-26](digests/2026-08-26.md)
- [2026-08-25](digests/2026-08-25.md)
- [2026-08-24](digests/2026-08-24.md)
- [2026-08-23](digests/2026-08-23.md)
- [2026-08-22](digests/2026-08-22.md)
- [2026-08-21](digests/2026-08-21.md)
- [2026-08-20](digests/2026-08-20.md)
- [2026-08-19](digests/2026-08-19.md)
- [2026-08-18](digests/2026-08-18.md)
<!-- /digest-index -->

## How it works

```
cron 06:00 UTC → GitHub Actions runner
  → pytest tests/            (gate: the digest job needs it)
  → pip install yamlgraph feedparser beautifulsoup4 httpx python-dotenv
  → run_digest.py: fetch HN/RSS → dedup (committed digest.db) →
    extract content → LLM analysis (map node) → rank top stories →
    render markdown + HTML → gate → archive → email
  → git commit digests/YYYY-MM-DD.md + digest.db + README index → push
```

- **Pipeline** — [graph.yaml](graph.yaml) (YAMLGraph), prompts in
  [prompts/](prompts/), side-effect nodes in [nodes/](nodes/) and
  [tools/](tools/)
- **State** — `digest.db` (seen-URL dedup) is committed each run;
  git history is the audit trail
- **Delivery** — the bulletin is **archived to disk before it is emailed**
  (persist-before-publish). A failed send leaves the bulletin intact and
  the run red, so the next run retries the day cleanly.
- **No-op days** — when no new stories pass dedup, `digest_status` is
  `no_articles`, the gate routes to END, and nothing is written, sent, or
  committed. Routing never keys off empty markdown, so a malformed ranker
  response cannot masquerade as a quiet day.

## Email

Five repository secrets drive delivery ([tools/smtp_email.py](tools/smtp_email.py),
vendored from yamlgraph FR-907 — see
[tools/smtp_email.VENDORED.md](tools/smtp_email.VENDORED.md)):

| Secret | Meaning |
|---|---|
| `SMTP_SERVER` | hostname |
| `SMTP_PORT` | `465` → implicit TLS; anything else → STARTTLS |
| `SMTP_USER` | login, and the default `From:` |
| `SMTP_PASSWORD` | login secret — never logged, never in an exception |
| `SMTP_TO` | recipient |

Mail is multipart: the markdown bulletin as the text part, a rendered
HTML alternative built from the same story list — no markdown parser, no
extra dependency. Every failure raises; there is no success-shaped
fallback, so an unattended run cannot report green while delivering
nothing.

## Run locally

```bash
pip install yamlgraph feedparser beautifulsoup4 httpx python-dotenv
export ANTHROPIC_API_KEY=sk-...
# plus the five SMTP_* variables above, or a .env file
python run_digest.py
```

There is no dry mode. Running it IS the intent — it will archive and
send. To iterate without delivering, unset `SMTP_TO` and the send raises
loudly rather than skipping silently.

## Provenance

Adapted from the [daily_digest example](https://github.com/sheikkinen/yamlgraph/tree/main/examples/daily_digest)
(Fly.io + email variant) under yamlgraph FR-819.
