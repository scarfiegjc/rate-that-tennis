"""
api/email.py — Resend email integration for ratethat.tennis
Uses urllib only (no extra deps).
Env vars required:
  RESEND_API_KEY   — Resend API key
  RTT_FROM_EMAIL   — sender address, e.g. "ratethat.tennis <hello@ratethat.tennis>"
  RTT_SITE_URL     — base URL, e.g. "https://ratethat.tennis"
"""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("RTT_FROM_EMAIL", "ratethat.tennis <hello@ratethat.tennis>")
SITE_URL = os.getenv("RTT_SITE_URL", "https://ratethat.tennis")

BRAND_GREEN = "#00c853"
BRAND_DARK = "#0a0e14"
BRAND_CARD = "#131820"


def send_email(to: str, subject: str, html: str) -> dict:
    """Send a single email via Resend. Returns the Resend response dict."""
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY env var not set")
    payload = json.dumps({
        "from": FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
    }).encode()
    req = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Resend error {e.code}: {body}") from e


def _wrap(body: str, preheader: str = "") -> str:
    """Wrap body HTML in branded email shell."""
    pre = f'<div style="display:none;max-height:0;overflow:hidden;">{preheader}&nbsp;</div>' if preheader else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>ratethat.tennis</title>
</head>
<body style="margin:0;padding:0;background:{BRAND_DARK};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e8eaf0;">
{pre}
<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_DARK};padding:32px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- Header -->
      <tr><td style="padding-bottom:24px;text-align:center;">
        <a href="{SITE_URL}" style="text-decoration:none;">
          <span style="font-size:22px;font-weight:800;letter-spacing:-0.5px;color:#fff;">
            ratethat<span style="color:{BRAND_GREEN};">.tennis</span>
          </span>
        </a>
      </td></tr>

      <!-- Body card -->
      <tr><td style="background:{BRAND_CARD};border-radius:12px;padding:32px 28px;">
        {body}
      </td></tr>

      <!-- Footer -->
      <tr><td style="padding-top:24px;text-align:center;font-size:12px;color:#4a5568;line-height:1.6;">
        <a href="{SITE_URL}/account" style="color:#4a5568;">Manage email preferences</a>
        &nbsp;·&nbsp;
        <a href="{SITE_URL}" style="color:#4a5568;">ratethat.tennis</a>
        <br/>You're receiving this because you subscribed at ratethat.tennis.
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Template renderers
# ─────────────────────────────────────────────────────────────────────────────

def render_daily_predictions(picks: list, date_str: str) -> str:
    """
    picks: list of dicts with keys:
      match_label, player1, player2, surface,
      predicted_winner, prob (0-1), edge_pct, confidence
    date_str: e.g. "Wednesday 14 May"
    """
    if not picks:
        rows_html = '<p style="color:#6b7280;text-align:center;">No predictions for today — check back tomorrow.</p>'
    else:
        rows = []
        for p in picks:
            conf_colour = {"high": BRAND_GREEN, "medium": "#f59e0b", "low": "#6b7280"}.get(
                p.get("confidence", "low"), "#6b7280"
            )
            prob_pct = int(round(p.get("prob", 0.5) * 100))
            edge = p.get("edge_pct", 0)
            edge_str = f"+{edge:.1f}%" if edge > 0 else f"{edge:.1f}%"
            edge_col = BRAND_GREEN if edge > 0 else "#ef4444"
            rows.append(f"""
<tr>
  <td style="padding:14px 0;border-bottom:1px solid #1e2530;">
    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:4px;">
      {p.get('surface','')} · {p.get('match_label','')}
    </div>
    <div style="font-size:15px;font-weight:600;color:#e8eaf0;margin-bottom:6px;">
      {p.get('player1','')} <span style="color:#4a5568;">vs</span> {p.get('player2','')}
    </div>
    <div style="display:flex;gap:12px;align-items:center;">
      <span style="background:{BRAND_DARK};border-radius:6px;padding:4px 10px;font-size:13px;font-weight:700;color:{BRAND_GREEN};">
        ▶ {p.get('predicted_winner','')} {prob_pct}%
      </span>
      <span style="font-size:12px;color:{edge_col};font-weight:600;">Edge: {edge_str}</span>
      <span style="font-size:11px;color:{conf_colour};text-transform:uppercase;letter-spacing:0.04em;">
        {p.get('confidence','').upper()}
      </span>
    </div>
  </td>
</tr>""")
        rows_html = f'<table width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>'

    body = f"""
<h2 style="margin:0 0 4px;font-size:20px;font-weight:800;color:#fff;">Today's Predictions</h2>
<p style="margin:0 0 24px;font-size:14px;color:#6b7280;">{date_str}</p>
{rows_html}
<p style="margin:24px 0 0;text-align:center;">
  <a href="{SITE_URL}/predictions"
     style="display:inline-block;background:{BRAND_GREEN};color:#000;font-weight:700;
            font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none;">
    View all predictions →
  </a>
</p>
"""
    return _wrap(body, preheader=f"{len(picks)} predictions for {date_str}")


def render_my_picks_digest(
    display_name: str,
    upcoming: list,
    recent_results: list,
    stats: dict,
) -> str:
    """
    upcoming: list of dicts { match_label, player1, player2, surface, my_pick, kickoff }
    recent_results: list of dicts { match_label, player1, player2, my_pick, result, correct }
    stats: dict { total_picks, correct, roi_pct }
    """
    name = display_name or "there"

    # Stats row
    total = stats.get("total_picks", 0)
    correct = stats.get("correct", 0)
    roi = stats.get("roi_pct", 0.0)
    hit_rate = f"{int(correct/total*100)}%" if total else "—"
    roi_str = f"+{roi:.1f}%" if roi > 0 else f"{roi:.1f}%"
    roi_col = BRAND_GREEN if roi >= 0 else "#ef4444"

    stats_html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_DARK};border-radius:8px;padding:16px;margin-bottom:28px;">
  <tr>
    <td align="center" style="padding:8px;">
      <div style="font-size:24px;font-weight:800;color:#fff;">{total}</div>
      <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Total Picks</div>
    </td>
    <td align="center" style="padding:8px;">
      <div style="font-size:24px;font-weight:800;color:{BRAND_GREEN};">{hit_rate}</div>
      <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">Hit Rate</div>
    </td>
    <td align="center" style="padding:8px;">
      <div style="font-size:24px;font-weight:800;color:{roi_col};">{roi_str}</div>
      <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.05em;">P&amp;L</div>
    </td>
  </tr>
</table>"""

    # Recent results
    if recent_results:
        result_rows = []
        for r in recent_results[:5]:
            icon = "✅" if r.get("correct") else "❌"
            result_rows.append(f"""
<tr>
  <td style="padding:10px 0;border-bottom:1px solid #1e2530;font-size:13px;color:#e8eaf0;">
    {icon} <strong>{r.get('my_pick','')}</strong>
    <span style="color:#6b7280;"> · {r.get('match_label','')}</span>
    <span style="color:#4a5568;float:right;">{r.get('result','')}</span>
  </td>
</tr>""")
        results_html = f"""
<h3 style="font-size:14px;font-weight:700;color:#fff;margin:0 0 12px;text-transform:uppercase;letter-spacing:0.05em;">
  Recent Results
</h3>
<table width="100%" cellpadding="0" cellspacing="0">{"".join(result_rows)}</table>"""
    else:
        results_html = ""

    # Upcoming
    if upcoming:
        up_rows = []
        for u in upcoming[:5]:
            up_rows.append(f"""
<tr>
  <td style="padding:10px 0;border-bottom:1px solid #1e2530;font-size:13px;color:#e8eaf0;">
    ★ <strong>{u.get('my_pick','')}</strong>
    <span style="color:#6b7280;"> · {u.get('match_label','')}</span>
    <span style="color:#4a5568;float:right;">{u.get('kickoff','')}</span>
  </td>
</tr>""")
        upcoming_html = f"""
<h3 style="font-size:14px;font-weight:700;color:#fff;margin:24px 0 12px;text-transform:uppercase;letter-spacing:0.05em;">
  Coming Up
</h3>
<table width="100%" cellpadding="0" cellspacing="0">{"".join(up_rows)}</table>"""
    else:
        upcoming_html = ""

    body = f"""
<h2 style="margin:0 0 4px;font-size:20px;font-weight:800;color:#fff;">Your Picks Digest</h2>
<p style="margin:0 0 24px;font-size:14px;color:#6b7280;">Hey {name}, here's how your picks are going.</p>
{stats_html}
{results_html}
{upcoming_html}
<p style="margin:28px 0 0;text-align:center;">
  <a href="{SITE_URL}/my-picks"
     style="display:inline-block;background:{BRAND_GREEN};color:#000;font-weight:700;
            font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none;">
    View my picks →
  </a>
</p>
"""
    return _wrap(body, preheader=f"Your picks: {hit_rate} hit rate, {roi_str} P&L")


def render_announcement(subject_line: str, body_html: str, display_name: str = "") -> str:
    """Generic announcement email. body_html is injected directly."""
    name_greeting = f"<p style='margin:0 0 16px;font-size:14px;color:#6b7280;'>Hey {display_name},</p>" if display_name else ""
    body = f"""
<h2 style="margin:0 0 16px;font-size:20px;font-weight:800;color:#fff;">{subject_line}</h2>
{name_greeting}
<div style="font-size:15px;color:#c4c9d4;line-height:1.7;">
  {body_html}
</div>
<p style="margin:28px 0 0;text-align:center;">
  <a href="{SITE_URL}"
     style="display:inline-block;background:{BRAND_GREEN};color:#000;font-weight:700;
            font-size:14px;padding:12px 28px;border-radius:8px;text-decoration:none;">
    Go to ratethat.tennis →
  </a>
</p>
"""
    return _wrap(body, preheader=subject_line)
