# yamlgraph-daily-digest

A daily tech news bulletin that publishes itself. No servers, no email,
no Docker — a [YAMLGraph](https://github.com/sheikkinen/yamlgraph)
pipeline runs in GitHub Actions every morning at 06:00 UTC and commits
a markdown bulletin back to this repo. The repo is the runtime, the
state store, and the publication channel.

## Latest digests

<!-- digest-index -->
- [2026-08-22](digests/2026-08-22.md)
- [2026-08-21](digests/2026-08-21.md)
- [2026-08-20](digests/2026-08-20.md)
- [2026-08-19](digests/2026-08-19.md)
- [2026-08-18](digests/2026-08-18.md)
<!-- /digest-index -->

## How it works

```
cron 06:00 UTC → GitHub Actions runner
  → pip install yamlgraph feedparser beautifulsoup4 httpx python-dotenv
  → run_digest.py: fetch HN/RSS → dedup (committed digest.db) →
    extract content → LLM analysis (map node) → rank top stories →
    render markdown
  → git commit digests/YYYY-MM-DD.md + digest.db + README index → push
```

- **Pipeline** — [graph.yaml](graph.yaml) (YAMLGraph), prompts in
  [prompts/](prompts/), side-effect nodes in [nodes/](nodes/)
- **State** — `digest.db` (seen-URL dedup) is committed each run;
  git history is the audit trail
- **Delivery** — the commit is the delivery; watch or star this repo
- **No-op days** — when no new stories pass dedup, nothing is committed

## Run locally

```bash
pip install yamlgraph feedparser beautifulsoup4 httpx python-dotenv
export ANTHROPIC_API_KEY=sk-...
python run_digest.py --dry-run
```

## Provenance

Adapted from the [daily_digest example](https://github.com/sheikkinen/yamlgraph/tree/main/examples/daily_digest)
(Fly.io + email variant) under yamlgraph FR-819.
