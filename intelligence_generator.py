#!/usr/bin/env python3
"""
Tennis Match Intelligence Generator for ratethat.tennis

Fetches upcoming matches missing intelligence, searches for recent player news,
generates journalism-quality analysis pieces, and stores them back to the database.
"""

import json
import sys
from datetime import datetime
import anthropic
import requests
from typing import Optional

# Configuration
API_BASE = "http://localhost:8000/api/v1"
LOG_FILE = "/Users/Gareth/Documents/Claude/Projects/RateThatTennis/intelligence_runs.log"

def log_run(message: str):
    """Append to intelligence_runs.log"""
    with open(LOG_FILE, "a") as f:
        timestamp = datetime.now().isoformat()
        f.write(f"[{timestamp}] {message}\n")

def fetch_intel_queue(days_ahead: int = 2) -> dict:
    """Fetch list of upcoming matches missing intelligence."""
    try:
        resp = requests.get(f"{API_BASE}/admin/intel/queue?days_ahead={days_ahead}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log_run(f"ERROR fetching intel queue: {e}")
        return {"queue": [], "count": 0}

def fetch_match_details(match_id: int) -> Optional[dict]:
    """Fetch all facts needed to generate intelligence for a match."""
    try:
        resp = requests.get(f"{API_BASE}/matches/{match_id}/intelligence", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log_run(f"ERROR fetching match {match_id}: {e}")
        return None

def search_player_news(player_name: str) -> str:
    """Search the web for recent news about a player."""
    try:
        # Use Anthropic's web search via a simple approach:
        # We'll just ask Claude about recent form/news that it knows about
        # In a real implementation, you'd call a news API or web search API
        return f"[Recent form search for {player_name} - use match facts from API]"
    except Exception as e:
        log_run(f"ERROR searching news for {player_name}: {e}")
        return ""

def generate_intelligence(match_data: dict) -> dict:
    """
    Generate three journalism-quality pieces for a match:
    - Player 1 analysis
    - Player 2 analysis
    - Full match preview with betting angles
    """

    client = anthropic.Anthropic()

    # Extract key facts
    match_id = match_data.get("match_id")
    facts = match_data.get("facts", {})
    match_info = facts.get("match", {})
    p1_data = facts.get("p1", {})
    p2_data = facts.get("p2", {})
    prediction = facts.get("prediction", {})
    h2h = facts.get("h2h", {})
    summaries = facts.get("summaries", {})

    p1_name = p1_data.get("name", "Player 1")
    p2_name = p2_data.get("name", "Player 2")
    tournament = match_info.get("tournament", "")
    surface = match_info.get("surface", "")

    # Resolve predicted_winner from internal code to actual player name
    raw_winner = prediction.get('predicted_winner')
    if raw_winner == 'first_player':
        predicted_winner_name = p1_name
    elif raw_winner == 'second_player':
        predicted_winner_name = p2_name
    else:
        predicted_winner_name = 'No clear prediction'

    p1_prob = prediction.get('prob_first_player', 0.5)
    p2_prob = prediction.get('prob_second_player', 0.5)

    # Build context for Claude
    context = f"""
You are a professional tennis journalist writing for ratethat.tennis. Generate three
pieces of match intelligence:

MATCH DETAILS:
- Tournament: {tournament}
- Surface: {surface}
- Round: {match_info.get('round', 'Unknown')}

PLAYERS:
P1: {p1_name}
  RTT Score: {p1_data.get('rtt', 'N/A')}
  Form: {p1_data.get('form', 'N/A')}
  Momentum: {p1_data.get('momentum', 'N/A')}
  Surface ratings: Clay {p1_data.get('surface_ratings', {}).get('clay', 'N/A')},
                  Hard {p1_data.get('surface_ratings', {}).get('hard', 'N/A')},
                  Grass {p1_data.get('surface_ratings', {}).get('grass', 'N/A')}
  Recent form: {summaries.get('p1', {}).get('win_loss_last_10', 'N/A')}
  Current streak: {summaries.get('p1', {}).get('current_streak', 'N/A')}

P2: {p2_name}
  RTT Score: {p2_data.get('rtt', 'N/A')}
  Form: {p2_data.get('form', 'N/A')}
  Momentum: {p2_data.get('momentum', 'N/A')}
  Surface ratings: Clay {p2_data.get('surface_ratings', {}).get('clay', 'N/A')},
                  Hard {p2_data.get('surface_ratings', {}).get('hard', 'N/A')},
                  Grass {p2_data.get('surface_ratings', {}).get('grass', 'N/A')}
  Recent form: {summaries.get('p2', {}).get('win_loss_last_10', 'N/A')}
  Current streak: {summaries.get('p2', {}).get('current_streak', 'N/A')}

HEAD-TO-HEAD:
- {p1_name} leads {h2h.get('p1_wins', 0)}-{h2h.get('p2_wins', 0)} from {h2h.get('total', 0)} meetings

MODEL PREDICTION (DO NOT contradict these figures — they are the output of our ML model
and must be accurately reflected in your writing):
- {p1_name} win probability: {p1_prob:.1%}
- {p2_name} win probability: {p2_prob:.1%}
- THE MODEL'S PREDICTED WINNER IS: {predicted_winner_name}
- Confidence: {prediction.get('confidence', 'Unknown')}

TASK:
Generate JSON with exactly these three fields:

1. "p1_intel": 150-200 word analysis of {p1_name} - their form, momentum, surface suitability,
   and tactical matchup advantages/disadvantages. Write in journalistic style.
   Use gender-appropriate pronouns based on the player's name.

2. "p2_intel": 150-200 word analysis of {p2_name} - their form, momentum, surface suitability,
   and tactical matchup advantages/disadvantages. Write in journalistic style.
   Use gender-appropriate pronouns based on the player's name.

3. "match_preview": 200-250 word match preview that combines both player narratives,
   highlights the key tactical angles, and explains the betting model's reasoning.
   You MUST state that {predicted_winner_name} is the model's predicted winner with a
   {max(p1_prob, p2_prob):.0%} win probability. Include surface context, h2h significance,
   and form trends.

Output ONLY valid JSON, no explanation.
"""

    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": context
                }
            ]
        )

        response_text = message.content[0].text

        # Parse the JSON response
        # Try to extract JSON from the response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            json_str = response_text[json_start:json_end]
            result = json.loads(json_str)
        else:
            result = json.loads(response_text)

        return {
            "p1_intel": result.get("p1_intel", ""),
            "p2_intel": result.get("p2_intel", ""),
            "match_preview": result.get("match_preview", "")
        }

    except Exception as e:
        log_run(f"ERROR generating intelligence for match {match_id}: {e}")
        return {
            "p1_intel": "",
            "p2_intel": "",
            "match_preview": ""
        }

def store_intelligence(match_id: int, intel: dict) -> bool:
    """Store generated intelligence back to the database via API."""
    try:
        payload = {
            "p1_intel": intel.get("p1_intel", ""),
            "p2_intel": intel.get("p2_intel", ""),
            "match_preview": intel.get("match_preview", ""),
            "model": "claude-opus-4-6"
        }

        resp = requests.post(
            f"{API_BASE}/admin/intel/store/{match_id}",
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        log_run(f"ERROR storing intelligence for match {match_id}: {e}")
        return False

def main():
    """Main execution flow."""
    start_time = datetime.now()
    log_run("═" * 80)
    log_run(f"Tennis Intelligence Generator started - {start_time.isoformat()}")
    log_run("═" * 80)

    # Step 1: Fetch queue of matches needing intelligence
    log_run("Fetching queue of matches needing intelligence...")
    queue_result = fetch_intel_queue(days_ahead=2)
    matches = queue_result.get("queue", [])
    log_run(f"Found {len(matches)} matches needing intelligence")

    if not matches:
        log_run("No matches found requiring intelligence generation.")
        log_run("Run completed with 0 matches processed.\n")
        return

    # Step 2: Process each match
    processed = 0
    successful = 0

    for match in matches[:5]:  # Limit to 5 per run to avoid API rate limits
        match_id = match.get("match_id")
        p1_name = match.get("p1_name", "Unknown")
        p2_name = match.get("p2_name", "Unknown")
        tournament = match.get("tournament", "Unknown")

        log_run(f"\n--- Processing Match {match_id} ---")
        log_run(f"  {p1_name} vs {p2_name}")
        log_run(f"  Tournament: {tournament}")

        # Fetch detailed match data
        match_data = fetch_match_details(match_id)
        if not match_data:
            log_run(f"  SKIPPED: Could not fetch match details")
            continue

        # Generate intelligence
        log_run(f"  Generating intelligence with Claude...")
        intel = generate_intelligence(match_data)

        # Validate generated content
        if not (intel.get("p1_intel") and intel.get("p2_intel") and intel.get("match_preview")):
            log_run(f"  SKIPPED: Generated content incomplete")
            continue

        # Store intelligence
        if store_intelligence(match_id, intel):
            log_run(f"  SUCCESS: Intelligence stored")
            successful += 1
        else:
            log_run(f"  FAILED: Could not store intelligence")

        processed += 1

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    log_run("\n" + "═" * 80)
    log_run(f"Run Summary:")
    log_run(f"  Processed: {processed} matches")
    log_run(f"  Successful: {successful} matches")
    log_run(f"  Failed: {processed - successful} matches")
    log_run(f"  Duration: {duration:.1f} seconds")
    log_run(f"  Ended: {end_time.isoformat()}")
    log_run("═" * 80 + "\n")

if __name__ == "__main__":
    main()
