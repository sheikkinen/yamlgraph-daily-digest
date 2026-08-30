# Vendored: smtp_email

Provenance for the vendored SMTP transport. Nothing is added to
`smtp_email.py` itself — this sidecar exists so the copy can stay
byte-identical (FR-903 judgement R-2).

## Upstream

| | |
|---|---|
| Repository | `sheikkinen/yamlgraph` |
| Path | `examples/shared/smtp_email.py` |
| Commit | `ca44832b14b6e1b1b3d4111f4f15c80e7dcc2ecd` |
| Governing FR | FR-907 (CAP-252 / REQ-YG-627) |

## Why vendored rather than imported

`pyproject.toml` `[tool.setuptools.packages.find]` excludes
`examples*` from the yamlgraph wheel, so `examples/shared/` is
unreachable from a PyPI consumer. Measured 2026-08-29 while enforcing
FR-906: the corpus-census demo, run outside a checkout against published
`yamlgraph 0.5.23`, failed with `No module named 'examples'`.

## Digests at copy time

| File | SHA-256 | Identical to upstream |
|---|---|---|
| `smtp_email.py` | `dfae6b2e4e97983a8826f508ee8aa894579e5cc9ca9501a37bcb53d12b57c5d9` | yes |
| `smtp_email.tool.yaml` | — | **no — adapted** |

`tools/smtp_email.tool.yaml` could not be copied verbatim: upstream
declares `module: examples.shared.smtp_email`, which does not resolve
here for the reason above. Only the runtime reference changed
(`module:` → `path: smtp_email.py`); name, description, and contract
are unchanged. The manifest is configuration, not the security surface.

## What the drift test does and does not prove

`tests/test_vendored_smtp.py` recomputes the digest above and compares
it to this file. That proves the vendored copy has not been **edited
locally** since it was taken.

It does **not** detect upstream drift. This repository has no access to
the yamlgraph tree at test time, so an upstream security fix — to the
header-injection refusal, the unchained exceptions, or the
validate-before-socket order — will not arrive here on its own. Re-vendor
deliberately and update this file.
