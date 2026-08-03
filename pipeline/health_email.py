#!/usr/bin/env python3
"""
ratethat.tennis — healthcheck email digest via Resend.

Referenced by api/main.py's /admin/healthcheck (send_digest) since months
ago, but — like pipeline/healthcheck.py — never actually existed in the
repo, so every healthcheck run silently no-op'd on the email step (masked
by the fact the endpoint 500'd before ever reaching it). Added 2026-08.

Environment variables (see .env / CLAUDE.md "Daily healthcheck"):
    RESEND_API_KEY    — Resend API key. If unset, send_digest() logs and
                        returns without error rather than failing the whole
                        healthcheck run.
    HEALTH_EMAIL_TO   — recipient address
    HEALTH_EMAIL_FROM — sender address (must be a Resend-verified domain,
                        or their onboarding@resend.dev sandbox sender)
"""

from __future__ import annotations

import logging
import os
from typing import List

import requests

log = logging.getLogger("rtt-health-email")

RESEND_URL = "https://api.resend.com/emails"


def _severity_emoji(severity: str, status: str) -> str:
    if status == "PASS":
        return "✅"
    return "🔴" if severity == "CRITICAL" else "🟡"


def _build_html(run_id: str, results: List) -> str:
    rows = []
    for r in results:
        emoji = _severity_emoji(r.severity, r.status)
        repair = f" — {r.repair_message}" if r.auto_repaired else ""
        rows.append(
            f"<tr><td style='padding:4px 8px'>{emoji}</td>"
            f"<td style='padding:4px 8px'><b>{r.name}</b></td>"
            f"<td style='padding:4px 8px'>{r.status}</td>"
            f"<td style='padding:4px 8px'>{r.message}{repair}</td></tr>"
        )
    crit_fail = sum(1 for r in results if r.status == "FAIL" and r.severity == "CRITICAL")
    warn_fail = sum(1 for r in results if r.status == "FAIL" and r.severity == "WARNING")
    headline = (
        "All checks passing" if not crit_fail and not warn_fail
        else f"{crit_fail} critical, {warn_fail} warning failure(s)"
    )
    return f"""
    <div style="font-family: -apple-system, Arial, sans-serif; max-width: 640px">
      <h2 style="margin-bottom:0">ratethat.tennis — daily healthcheck</h2>
      <p style="color:#555; margin-top:4px">Run {run_id} — {headline}</p>
      <table style="border-collapse:collapse; width:100%">
        {''.join(rows)}
      </table>
    </div>
    """


def send_digest(run_id: str, results: List, force: bool = False) -> bool:
    """
    Email a healthcheck digest via Resend. Returns True if sent, False if
    skipped (no API key / no recipient) or on failure — never raises, so a
    missing/misconfigured email setup never breaks the healthcheck endpoint.

    `force` is accepted for API compatibility with older call sites that
    pass it; this implementation always sends when configured (no
    additional throttling), so `force` currently has no distinct effect.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to_addr = os.environ.get("HEALTH_EMAIL_TO", "").strip()
    from_addr = os.environ.get("HEALTH_EMAIL_FROM", "onboarding@resend.dev").strip()

    if not api_key:
        log.info("send_digest: RESEND_API_KEY not set — skipping email "
                 f"(run_id={run_id})")
        return False
    if not to_addr:
        log.info("send_digest: HEALTH_EMAIL_TO not set — skipping email "
                 f"(run_id={run_id})")
        return False

    crit_fail = sum(1 for r in results if r.status == "FAIL" and r.severity == "CRITICAL")
    subject = (
        f"✅ ratethat.tennis healthcheck — all clear ({run_id})"
        if crit_fail == 0
        else f"🔴 ratethat.tennis healthcheck — {crit_fail} critical failure(s) ({run_id})"
    )

    try:
        resp = requests.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": from_addr,
                "to": [to_addr],
                "subject": subject,
                "html": _build_html(run_id, results),
            },
            timeout=15,
        )
        if resp.status_code >= 300:
            log.error(f"send_digest: Resend returned {resp.status_code}: {resp.text[:300]}")
            return False
        log.info(f"send_digest: sent healthcheck email for run_id={run_id} to {to_addr}")
        return True
    except Exception as e:
        log.error(f"send_digest: failed to send email: {type(e).__name__}: {e}")
        return False
