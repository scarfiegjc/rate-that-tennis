"""
ratethat.tennis — Intelligence Generation Pipeline
Fetches upcoming matches lacking intelligence text, generates 5-piece
journalistic previews via the Anthropic API, and stores them back.

Run via: run_intelligence.command
Or directly: python3 -m pipeline.intelligence
"""

import json
import os
import sys
import time

import requests

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = os.environ.get(
    "RTT_API_BASE", "https://rate-that-tennis-production.up.railway.app"
)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"
DAYS_AHEAD = int(os.environ.get("RTT_INTEL_DAYS", "2"))


# ── Anthropic call (raw HTTP — no SDK dependency required) ────────────────────

def generate_intelligence(facts: dict) -> dict:
    """Call Anthropic API to generate 5 intelligence fields for a match."""

    match   = facts.get("match", {})
    pred    = facts.get("prediction", {})
    p1      = facts.get("p1", {})
    p2      = facts.get("p2", {})
    h2h     = facts.get("h2h", {})
    market  = facts.get("market", {})

    surface = (match.get("surface") or "hard").lower()

    def surface_rating(player, surf):
        return player.get("surface_ratings", {}).get(surf)

    p1_surf = surface_rating(p1, surface)
    p2_surf = surface_rating(p2, surface)

    def fmt_form(form_list):
        lines = []
        for f in (form_list or []):
            score = f.get("score") or ""
            lines.append(
                f"  {f.get('result','?')} vs {f.get('opp','?')} "
                f"({score}) — {f.get('tournament','?')} [{f.get('surface','?')}]"
            )
        return "\n".join(lines) if lines else "  No recent results on record."

    p1_form_str = fmt_form(p1.get("recent_form"))
    p2_form_str = fmt_form(p2.get("recent_form"))

    # Market context
    market_str = ""
    if market and (market.get("p1") or market.get("p2")):
        p1m = market.get("p1") or {}
        p2m = market.get("p2") or {}
        parts = []
        if p1m.get("decimal_odds"):
            parts.append(f"{p1.get('name')} @ {p1m['decimal_odds']:.2f} ({p1m.get('bookmaker','market')})")
        if p2m.get("decimal_odds"):
            parts.append(f"{p2.get('name')} @ {p2m['decimal_odds']:.2f} ({p2m.get('bookmaker','market')})")
        if parts:
            market_str = "Bookmaker odds: " + " | ".join(parts)

    prompt = f"""You are a sports journalist writing intelligence for ratethat.tennis, a tennis analytics platform.

MATCH FACTS
-----------
Tournament: {match.get('tournament','?')}
Round: {match.get('round','?')}
Surface: {match.get('surface','?')}
Date: {match.get('event_date','?')}

PLAYER 1: {p1.get('name','?')} ({p1.get('country','?')})
  RTT Score: {p1.get('rtt')}
  {match.get('surface','?').capitalize() if match.get('surface') else 'Surface'} rating: {p1_surf}
  Form score: {p1.get('form')}
  Momentum: {p1.get('momentum')}
  Recent results (last 10):
{p1_form_str}

PLAYER 2: {p2.get('name','?')} ({p2.get('country','?')})
  RTT Score: {p2.get('rtt')}
  {match.get('surface','?').capitalize() if match.get('surface') else 'Surface'} rating: {p2_surf}
  Form score: {p2.get('form')}
  Momentum: {p2.get('momentum')}
  Recent results (last 10):
{p2_form_str}

PREDICTION
  Predicted winner: {pred.get('predicted_winner','?')}
  P1 win probability: {pred.get('prob_first_player')}
  P2 win probability: {pred.get('prob_second_player')}
  Confidence: {pred.get('confidence','?')}
  RTT gap: {pred.get('rtt_gap')}
  Surface gap: {pred.get('surface_gap')}
  Form gap: {pred.get('form_gap')}

HEAD-TO-HEAD (production data)
  {p1.get('name','P1')} wins: {h2h.get('p1_wins',0)}
  {p2.get('name','P2')} wins: {h2h.get('p2_wins',0)}
  Total meetings: {h2h.get('total',0)}

{market_str}

INSTRUCTIONS
------------
Write EXACTLY these five fields in your response as a JSON object with these keys:
  p1_intel, p2_intel, match_preview, did_you_know, confidence_line

Rules (strictly enforced):
- p1_intel: 2–4 sentences on {p1.get('name','Player 1')}: form, ability, surface preference. Use exact RTT score, surface rating, form score, momentum. Reference 1–2 specific recent results with opponent name and score if notable.
- p2_intel: same for {p2.get('name','Player 2')}.
- match_preview: 3–5 sentences. Include the H2H record (total meetings and breakdown). State the model's predicted winner and their probability. Name the key advantages (RTT gap, surface gap, form gap). Say what the underdog needs to do to win. If bookmaker odds are present, compare to model probability and call out value or fair pricing.
- did_you_know: ONE punchy sentence with ONE striking statistic from the data above. Only use facts you can confirm from the recent_form list or the numbers above. Never invent.
- confidence_line: ONE sentence under 20 words explaining why the model has {pred.get('confidence','?')} confidence. Reference the strongest factor.

Style:
- Confident, concise, sports-preview. No filler, no hedging ("only time will tell" etc.).
- No knowledge from outside the provided facts. Do not invent injuries, news, or personality.
- Numbers must be exact. Player names as given.
- Surfaces lowercase unless starting a sentence.

Respond with ONLY valid JSON. No markdown, no extra text."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"].strip()

    # Strip markdown code fences if the model wraps in them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run():
    if not ANTHROPIC_API_KEY:
        print("❌  ANTHROPIC_API_KEY is not set in .env — cannot call Claude API.")
        print("   Add:  ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Step 1 — fetch the queue
    print(f"▶  Fetching intelligence queue (next {DAYS_AHEAD} days)…")
    try:
        r = requests.get(f"{API_BASE}/api/v1/admin/intel/queue?days_ahead={DAYS_AHEAD}", timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"❌  Could not reach API: {e}")
        sys.exit(1)

    queue_data = r.json()
    queue = queue_data.get("queue", [])
    count = queue_data.get("count", 0)

    if count == 0:
        print("✓  No matches need intelligence — nothing to do.")
        return

    print(f"   Found {count} match(es) needing intelligence.\n")

    succeeded = 0
    failed = []

    for i, match in enumerate(queue, 1):
        mid  = match["match_id"]
        name = f"{match.get('p1_name','?')} vs {match.get('p2_name','?')}"
        surf = match.get("surface", "?")
        tourn = match.get("tournament", "?")
        print(f"[{i}/{count}] {name} — {tourn} ({surf})")

        # Step 2 — fetch facts
        try:
            fr = requests.get(f"{API_BASE}/api/v1/matches/{mid}/intelligence", timeout=30)
            fr.raise_for_status()
            facts = fr.json().get("facts", {})
        except Exception as e:
            print(f"       ⚠  Could not fetch facts: {e} — skipping")
            failed.append((mid, name, f"facts fetch: {e}"))
            continue

        # Step 3 — generate
        print(f"       Generating intelligence via Claude…")
        try:
            intel = generate_intelligence(facts)
        except Exception as e:
            print(f"       ⚠  Generation failed: {e} — skipping")
            failed.append((mid, name, f"generation: {e}"))
            continue

        # Validate required fields
        for field in ("p1_intel", "p2_intel", "match_preview"):
            if not intel.get(field):
                err = f"missing field '{field}' in response"
                print(f"       ⚠  {err} — skipping")
                failed.append((mid, name, err))
                break
        else:
            # Step 4 — store
            payload = {
                "p1_intel":        intel.get("p1_intel", ""),
                "p2_intel":        intel.get("p2_intel", ""),
                "match_preview":   intel.get("match_preview", ""),
                "did_you_know":    intel.get("did_you_know", ""),
                "confidence_line": intel.get("confidence_line", ""),
                "model":           MODEL,
            }
            try:
                sr = requests.post(
                    f"{API_BASE}/api/v1/admin/intel/store/{mid}",
                    json=payload,
                    timeout=30,
                )
                sr.raise_for_status()
                print(f"       ✓  Stored.")
                succeeded += 1
            except Exception as e:
                print(f"       ⚠  Store failed: {e}")
                failed.append((mid, name, f"store: {e}"))

        # Small pause to avoid hammering the API
        if i < count:
            time.sleep(0.5)

    # Step 5 — summary
    print(f"\n{'─'*50}")
    print(f"✓  Intelligence generation complete.")
    print(f"   Succeeded: {succeeded}/{count}")
    if failed:
        print(f"   Failed:    {len(failed)}")
        for fid, fname, reason in failed:
            print(f"     • [{fid}] {fname}: {reason}")


if __name__ == "__main__":
    run()
