"""Regression tests: Prompt Armor must not flag ordinary docs (hivemind ticket #435),
while real flooding / gibberish attacks must still fire."""

import asyncio
import random

from zugashield import ShieldVerdict
from zugashield.config import ShieldConfig
from zugashield.layers.prompt_armor import PromptArmorLayer
from zugashield.threat_catalog import ThreatCatalog

_LAYER = PromptArmorLayer(ShieldConfig(), ThreatCatalog())


def check(text):
    return asyncio.run(_LAYER.check(text))


def sig_ids(decision):
    return {t.signature_id for t in decision.threats_detected}


def _status_doc(words=2200):
    """Ordinary markdown status doc: prose, tables, backticked paths."""
    rng = random.Random(7)
    vocab = (
        "the service is running and the deploy finished so we moved to the next "
        "step of the plan while a review of the board shows that work continues "
        "on the tickets for this week with notes about each one in a table"
    ).split()
    lines = ["# Live board", "", "| Item | State | Notes |", "|---|---|---|"]
    paths = [
        "`~/Projects/ZugaLife/backend`",
        "`~/.cloudflared/config.yml`",
        "**/tmp/backend-rss-pipeline.log**",
        "(`/var/lib/zugashield/quarantine`)",
        '"~/Projects/ZugaLife/backend/main.py"',
    ]
    count = 0
    while count < words:
        row = " ".join(rng.choice(vocab) for _ in range(12))
        lines.append(f"| {row} | {rng.choice(paths)} | {rng.choice(paths)} |")
        count += 14
        lines.append(" ".join(rng.choice(vocab) for _ in range(20)) + ".")
        count += 20
    return "\n".join(lines)


class TestOrdinaryDocsAllowed:
    def test_long_markdown_status_doc_allowed(self):
        doc = _status_doc()
        assert len(doc.split()) > 1700
        d = check(doc)
        assert d.verdict == ShieldVerdict.ALLOW, sig_ids(d)

    def test_markdown_table_not_flagged(self):
        header = "| Name | State |\n|---------|---------|\n"
        rows = "".join(f"| item{n} | ok{n} |\n" for n in range(200))
        d = check(header + rows)
        assert "PA-FLOOD-REPEAT" not in sig_ids(d)
        assert "PA-GLITCH-SPECIAL" not in sig_ids(d)

    def test_markdown_wrapped_paths_not_high_entropy(self):
        text = (
            "Edited `~/Library/LaunchAgents/com.zuga.hivemind.plist` and "
            "**~/Library/LaunchAgents/com.zuga.shieldwatch.plist** plus "
            "(`~/Library/LaunchAgents/com.zuga.zugabotd.plist`) today."
        )
        assert "PA-GLITCH-ENTROPY" not in sig_ids(check(text))

    def test_wrapped_url_and_hex_not_high_entropy(self):
        text = "see (https://example.com/a?b=c1d2e3f4g5) and `deadbeefcafebabe1234` and \"0123456789abcdef\" ok"
        assert "PA-GLITCH-ENTROPY" not in sig_ids(check(text))


class TestRealAttacksStillFire:
    def test_single_word_flood(self):
        d = check("ignore " * 200)
        assert d.verdict != ShieldVerdict.ALLOW
        assert "PA-FLOOD-REPEAT" in sig_ids(d)

    def test_stopword_flood(self):
        d = check("the " * 300)
        assert "PA-FLOOD-REPEAT" in sig_ids(d)

    def test_flood_with_some_padding(self):
        d = check(("spam spam spam spam please " * 60))
        assert "PA-FLOOD-REPEAT" in sig_ids(d)

    def test_gibberish_tokens_still_flagged(self):
        text = "qZx9Kd2Vm7LpR4wYtN8bFj3HcG6sUaE Wv1XoB0iTyM9eQrD7kZnA2LhP4gJcS8 Rt6UbY3xNwK1mV5qDzHj9GaE7pLoC0"
        assert "PA-GLITCH-ENTROPY" in sig_ids(check(text))

    def test_wrapped_gibberish_still_flagged(self):
        text = "`qZx9Kd2Vm7LpR4wYtN8bFj3HcG6sUaE` **Wv1XoB0iTyM9eQrD7kZnA2LhP4gJcS8** (Rt6UbY3xNwK1mV5qDzHj9GaE7pLoC0)"
        assert "PA-GLITCH-ENTROPY" in sig_ids(check(text))
