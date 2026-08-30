"""FR-903 — archive then email, in a declared order.

RED before GREEN. These encode the contracts the judgement froze:

- the artifact reaches disk BEFORE the network call (persist-before-publish)
- routing keys off an explicit `digest_status`, never off empty markdown,
  so a malformed ranker response cannot launder into a green no-op
- `--dry-run` does not exist (operator ruling: a dry-run flag is hedging)
- the vendored SMTP copy has not been edited locally since vendoring
- the workflow shape is asserted, not reviewed
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
GRAPH = yaml.safe_load((REPO / "graph.yaml").read_text())
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/digest.yml").read_text())


def _edges(source: str) -> list[dict]:
    return [e for e in GRAPH["edges"] if e.get("from") == source]


class TestDeliveryOrdering:
    def test_graph_declares_the_send_node(self):
        assert "send_email" in GRAPH["nodes"]

    def test_archive_precedes_send_as_a_transition(self):
        """Path, not destination: a terminal-state check passes via error recovery."""
        assert any(e["to"] == "send_email" for e in _edges("write_bulletin")), (
            "write_bulletin must hand off to send_email"
        )
        assert not any(e["to"] == "write_bulletin" for e in _edges("send_email")), (
            "send must not precede archive"
        )

    def test_send_is_reachable_only_through_write_bulletin(self):
        sources = {e["from"] for e in GRAPH["edges"] if e.get("to") == "send_email"}
        assert sources == {"write_bulletin"}

    def test_send_failure_is_loud(self):
        assert GRAPH["nodes"]["send_email"].get("on_error") == "fail", (
            "a silent skip would report green while delivering nothing"
        )


class TestNoOpPredicate:
    def test_formatting_emits_digest_status(self):
        assert "digest_status" in GRAPH["state"]

    def test_gate_routes_on_status_not_on_empty_markdown(self):
        gate_edges = _edges("gate")
        conditions = " ".join(str(e.get("condition", "")) for e in gate_edges)
        assert "digest_status" in conditions, "gate must key off the status field"
        assert "digest_markdown" not in conditions, (
            "empty markdown cannot distinguish 'no articles' from a bad ranker"
        )

    def test_no_articles_routes_to_end(self):
        assert any(
            e["to"] == "END" and "no_articles" in str(e.get("condition", ""))
            for e in _edges("gate")
        )


class TestDryRunIsGone:
    def test_no_dry_run_argument(self):
        source = (REPO / "run_digest.py").read_text()
        assert "dry_run" not in source and "dry-run" not in source, (
            "a dry-run flag is hedging; deviant-daily retired dry_run/force "
            "and tests that they stay gone"
        )

    def test_runner_holds_no_delivery_or_write_logic(self):
        source = (REPO / "run_digest.py").read_text()
        assert "write_text" not in source, "archiving belongs to write_bulletin"
        assert "smtp" not in source.lower(), "delivery belongs to send_email"


class TestVendoredSmtp:
    def test_vendored_copy_matches_its_recorded_digest(self):
        sidecar = (REPO / "tools/smtp_email.VENDORED.md").read_text()
        recorded = re.search(r"`smtp_email\.py` \| `([0-9a-f]{64})`", sidecar)
        assert recorded, "sidecar must record the SHA-256 of the vendored file"
        actual = hashlib.sha256((REPO / "tools/smtp_email.py").read_bytes()).hexdigest()
        assert actual == recorded.group(1), (
            "vendored smtp_email.py was edited locally; re-vendor deliberately"
        )

    def test_sidecar_names_its_upstream_commit(self):
        sidecar = (REPO / "tools/smtp_email.VENDORED.md").read_text()
        assert re.search(r"\| Commit \| `[0-9a-f]{40}` \|", sidecar)

    def test_manifest_resolves_locally(self):
        manifest = yaml.safe_load((REPO / "tools/smtp_email.tool.yaml").read_text())
        assert manifest["name"] == "send_email"
        assert (REPO / "tools" / manifest["runtime"]["path"]).is_file()


class TestWorkflowShape:
    """The deviant-daily pattern: drift is a test failure, not a review note."""

    def test_schedule_is_preserved(self):
        on = WORKFLOW.get("on", WORKFLOW.get(True))
        assert on["schedule"] == [{"cron": "0 6 * * *"}]

    def test_concurrency_group_is_serial(self):
        assert WORKFLOW["concurrency"]["group"] == "daily-digest"
        assert WORKFLOW["concurrency"]["cancel-in-progress"] is False

    def test_write_ceiling_declared(self):
        assert WORKFLOW["permissions"]["contents"] == "write"

    @pytest.mark.parametrize(
        "secret",
        ["SMTP_SERVER", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_TO"],
    )
    def test_every_smtp_secret_is_passed(self, secret):
        text = (REPO / ".github/workflows/digest.yml").read_text()
        assert f"secrets.{secret}" in text

    def test_no_guard_flags_survive(self):
        text = (REPO / ".github/workflows/digest.yml").read_text()
        assert "dry-run" not in text and "dry_run" not in text
