"""
Matchstat data-quality spike.

Pulls a small sample of player + per-match stat data from the Matchstat
RapidAPI endpoint to validate before committing to a full historical
backfill. Writes nothing to the production database — purely diagnostic.

Endpoint exposed: GET /admin/matchstat-spike  →  returns a JSON report
covering name-match resolution, stat-field coverage, value sanity, and
a few raw example rows.
"""
from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Optional
from urllib import request as _req
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

from api.db import query, query_one

log = logging.getLogger("api.matchstat_spike")

API_HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
API_BASE = f"https://{API_HOST}"


def _headers() -> dict:
    key = os.environ.get("MATCHSTAT_API_KEY", "").strip()
    return {
        # Cloudflare in front of the upstream blocks Python's default UA, so
        # send a real-looking one. RapidAPI itself doesn't gate on UA.
        "User-Agent": "Mozilla/5.0 (compatible; ratethat-tennis/1.0; +https://ratethat.tennis)",
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": API_HOST,
        "Accept": "application/json",
    }


# 2-letter ISO → 3-letter ISO country codes (the subset that appears in our
# players table — Matchstat's PlayerCountry filter expects the 3-letter form).
_CC2_TO_CC3 = {
    "AR": "ARG", "AT": "AUT", "AU": "AUS", "BA": "BIH", "BE": "BEL", "BG": "BUL",
    "BO": "BOL", "BR": "BRA", "BY": "BLR", "CA": "CAN", "CH": "SUI", "CL": "CHI",
    "CN": "CHN", "CO": "COL", "CR": "CRC", "CY": "CYP", "CZ": "CZE", "DE": "GER",
    "DK": "DEN", "DO": "DOM", "EC": "ECU", "EE": "EST", "EG": "EGY", "ES": "ESP",
    "FI": "FIN", "FR": "FRA", "GB": "GBR", "GE": "GEO", "GR": "GRE", "HK": "HKG",
    "HR": "CRO", "HU": "HUN", "ID": "INA", "IE": "IRL", "IL": "ISR", "IN": "IND",
    "IT": "ITA", "JP": "JPN", "KR": "KOR", "KZ": "KAZ", "LT": "LTU", "LU": "LUX",
    "LV": "LAT", "MD": "MDA", "ME": "MNE", "MX": "MEX", "MY": "MAS", "NL": "NED",
    "NO": "NOR", "NZ": "NZL", "PE": "PER", "PH": "PHI", "PL": "POL", "PT": "POR",
    "PY": "PAR", "RO": "ROU", "RS": "SRB", "RU": "RUS", "SE": "SWE", "SI": "SLO",
    "SK": "SVK", "TH": "THA", "TN": "TUN", "TR": "TUR", "TW": "TPE", "UA": "UKR",
    "US": "USA", "UY": "URU", "UZ": "UZB", "VE": "VEN", "VN": "VIE", "ZA": "RSA",
}


def _to_cc3(cc2: Optional[str]) -> Optional[str]:
    if not cc2:
        return None
    cc2 = cc2.upper()
    # Already 3 letters? pass through.
    if len(cc2) == 3:
        return cc2
    return _CC2_TO_CC3.get(cc2)


def _get(path: str, params: Optional[dict] = None, timeout: int = 12) -> dict:
    """Make a single Matchstat GET. Returns a parsed JSON dict + a tiny meta block."""
    url = API_BASE + path
    if params:
        url += "?" + urlencode(params)
    req = _req.Request(url, headers=_headers())
    t0 = time.time()
    try:
        with _req.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body) if body else None
            return {
                "ok": True,
                "status": resp.status,
                "ms": int((time.time() - t0) * 1000),
                "data": data,
            }
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return {"ok": False, "status": e.code, "error": str(e), "body": body[:500]}
    except URLError as e:
        return {"ok": False, "status": 0, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Spike
# ─────────────────────────────────────────────────────────────────────────────

# The detailed match-stat fields we care about for prediction (the ones
# Sackmann doesn't have at a per-match level).
TARGET_STAT_FIELDS = [
    "aces1", "aces2",
    "doubleFaults1", "doubleFaults2",
    "firstServe1", "firstServeOf1",
    "winningOnFirstServe1", "winningOnFirstServeOf1",
    "winningOnSecondServe1", "winningOnSecondServeOf1",
    "breakPointsConverted1", "breakPointsConvertedOf1",
    "winners1", "winners2",
    "unforcedErrors1", "unforcedErrors2",
    "netApproaches1", "netApproachesOf1",
    "totalPointsWon1", "totalPointsWon2",
    "fastestServe1", "fastestServe2",
    "averageFirstServeSpeed1", "averageSecondServeSpeed1",
    "rpw1", "rpwOf1",
]


def _pick_sample_players(n: int = 10) -> list[dict]:
    """Choose ~n active top-RTT players to spike against."""
    return query(
        """
        SELECT p.id, p.name, p.full_name, p.country_code, pr.rtt_score
        FROM players p
        JOIN player_ratings pr ON pr.player_id = p.id
        WHERE pr.rtt_score IS NOT NULL
          AND p.is_active = TRUE
        ORDER BY pr.rtt_score DESC NULLS LAST
        LIMIT %s
        """,
        (n,),
    )


def _resolve_matchstat_id(player: dict, tour: str = "atp") -> dict:
    """
    Try to find this player in Matchstat's player list by name.
    Returns {ms_id, ms_name, strategy, candidates}.
    """
    full = (player.get("full_name") or player.get("name") or "").strip()
    short = (player.get("name") or "").strip()
    if not full and not short:
        return {"ms_id": None, "strategy": "no-name"}

    # The Matchstat /player endpoint doesn't have a search param — it's a paginated
    # list with optional country/group filters. For the spike we'll fetch a single
    # page (the top of the rankings) to demonstrate ID lookup mechanics. A real
    # backfill would either use full-text search (/misc/search) or paginate
    # through the whole list once and cache locally.
    cc3 = _to_cc3(player.get("country_code"))
    if cc3:
        # The doc shows `PlayerCountry:{ITA}` but the live endpoint rejects
        # braces. Try a sequence of plausible filter syntaxes and fall back
        # to an unfiltered single-page fetch if all fail.
        page = None
        last_error = None
        for filter_value in (
            f"PlayerCountry:{cc3}",
            f"PlayerCountry:{{{cc3}}}",
        ):
            attempt = _get(
                f"/tennis/v2/{tour}/player",
                params={"filter": filter_value, "pageSize": 100},
            )
            body = attempt.get("data") if attempt.get("ok") else None
            # Bare list, or {data: [...]} — both are valid success shapes.
            if isinstance(body, list):
                page = attempt
                break
            if isinstance(body, dict) and isinstance(body.get("data"), list):
                page = attempt
                break
            last_error = attempt

        if page is None:
            # Final fallback: fetch first page unfiltered and search there.
            attempt = _get(f"/tennis/v2/{tour}/player", params={"pageSize": 200})
            body = attempt.get("data") if attempt.get("ok") else None
            if isinstance(body, (list, dict)):
                page = attempt
            else:
                return {"ms_id": None, "strategy": "list-fetch-failed",
                        "last_error_preview": str(last_error)[:300]}

        body = page.get("data")
        if isinstance(body, list):
            rows = body
        elif isinstance(body, dict) and isinstance(body.get("data"), list):
            rows = body["data"]
        else:
            return {"ms_id": None, "strategy": "unexpected-list-shape",
                    "shape_type": type(body).__name__,
                    "body_preview": (str(body)[:300] if body is not None else None)}
        last_token = full.replace(".", "").split()[-1].lower() if full else ""
        first_initial = (short[:1] or "").lower() if short else ""

        # 1: exact full name
        for r in rows:
            if (r.get("name") or "").strip().lower() == full.lower():
                return {"ms_id": r.get("id"), "ms_name": r.get("name"),
                        "strategy": "exact-full"}

        # 2: surname + first initial
        for r in rows:
            tokens = (r.get("name") or "").lower().split()
            if not tokens:
                continue
            if tokens[-1] == last_token and tokens[0][:1] == first_initial:
                return {"ms_id": r.get("id"), "ms_name": r.get("name"),
                        "strategy": "surname-initial"}

        # 3: surname only (also case-insensitive substring)
        last_matches = [
            r for r in rows
            if last_token and last_token in (r.get("name") or "").lower()
        ]
        if len(last_matches) == 1:
            r = last_matches[0]
            return {"ms_id": r.get("id"), "ms_name": r.get("name"),
                    "strategy": "surname-only"}
        if len(last_matches) > 1:
            return {"ms_id": None, "strategy": "ambiguous-surname",
                    "candidates": [{"id": r["id"], "name": r["name"]} for r in last_matches[:5]]}

        # No match — return debug info so we can see what the list looked like
        return {
            "ms_id": None,
            "strategy": "no-match",
            "list_size": len(rows),
            "sample_names": [r.get("name") for r in rows[:8]],
            "looking_for": {"full": full, "last_token": last_token, "first_initial": first_initial},
        }

    return {"ms_id": None, "strategy": "no-country-code"}


def _spike_one_player(player: dict, tour: str = "atp") -> dict:
    """Run the full lookup → past-matches probe for a single player."""
    out = {
        "rtt_player": {
            "id": player["id"],
            "name": player.get("name"),
            "full_name": player.get("full_name"),
            "country_code": player.get("country_code"),
            "rtt_score": float(player["rtt_score"]) if player.get("rtt_score") is not None else None,
        },
    }

    # 1) Resolve the Matchstat ID
    resolved = _resolve_matchstat_id(player, tour=tour)
    out["resolution"] = resolved
    ms_id = resolved.get("ms_id")
    if not ms_id:
        return out

    # 2) Pull profile (sanity check that ID works)
    profile = _get(f"/tennis/v2/{tour}/player/profile/{ms_id}",
                   params={"include": "form,ranking,country"})
    if profile.get("ok") and profile.get("data"):
        prof = profile["data"]
        out["profile"] = {
            "currentRank": prof.get("currentRank"),
            "ch": prof.get("ch"),
            "height": prof.get("height"),
            "birthday": prof.get("birthday"),
            "ep_present": bool(prof.get("ep")),
        }
    else:
        out["profile_error"] = profile

    # 3) Past matches with stats — this is the headline test
    matches = _get(f"/tennis/v2/{tour}/player/past-matches/{ms_id}",
                   params={"include": "round,tournament.court,tournament.rank,stat",
                           "pageSize": 20})
    if not matches.get("ok"):
        out["matches_error"] = matches
        return out

    # Same defensive pattern: matches may come back as { data: [...] } or as a bare list.
    mbody = matches.get("data")
    if isinstance(mbody, list):
        rows = mbody
    elif isinstance(mbody, dict) and isinstance(mbody.get("data"), list):
        rows = mbody["data"]
    else:
        out["matches_unexpected_shape"] = {
            "shape_type": type(mbody).__name__,
            "preview": (str(mbody)[:400] if mbody is not None else None),
        }
        rows = []
    out["match_count_returned"] = len(rows)

    # Coverage: how many matches actually have stat blocks at all,
    # and per-field how many populated.
    field_counts = {f: 0 for f in TARGET_STAT_FIELDS}
    matches_with_stats = 0
    sample_match = None
    for m in rows:
        stat = m.get("stat") or {}
        if isinstance(stat, list):
            stat = stat[0] if stat else {}
        if stat:
            matches_with_stats += 1
        for f in TARGET_STAT_FIELDS:
            if stat and stat.get(f) is not None:
                field_counts[f] += 1
        if not sample_match and stat:
            # Save one fully-populated match as an example (truncated player objs)
            sample_match = {
                "id": m.get("id"),
                "date": m.get("date"),
                "result": m.get("result"),
                "tournament": (m.get("tournament") or {}).get("name"),
                "court": ((m.get("tournament") or {}).get("court") or {}).get("name"),
                "rank":  ((m.get("tournament") or {}).get("rank")  or {}).get("name"),
                "round": (m.get("round") or {}).get("name"),
                "player1": {"id": m.get("player1Id"), "name": (m.get("player1") or {}).get("name")},
                "player2": {"id": m.get("player2Id"), "name": (m.get("player2") or {}).get("name")},
                "stat_keys": sorted(list(stat.keys())) if isinstance(stat, dict) else [],
                "stat": {k: stat.get(k) for k in TARGET_STAT_FIELDS} if isinstance(stat, dict) else None,
            }

    out["coverage"] = {
        "matches_with_stat_block": matches_with_stats,
        "matches_total":           len(rows),
        "stat_field_population":   field_counts,
    }
    if sample_match:
        out["sample_match"] = sample_match
    return out


def run_spike(n_players: int = 10, tour: str = "atp") -> dict:
    """Run the spike across N players and aggregate findings."""
    if not os.environ.get("MATCHSTAT_API_KEY"):
        return {"error": "MATCHSTAT_API_KEY env var is not set on this service"}

    sample = _pick_sample_players(n_players)
    if not sample:
        return {"error": "No active rated players available in player_ratings — fix that first"}

    results: list[dict] = []
    t0 = time.time()
    for p in sample:
        try:
            results.append(_spike_one_player(p, tour=tour))
        except Exception as e:
            results.append({
                "rtt_player": {"id": p["id"], "name": p.get("name")},
                "error": f"{type(e).__name__}: {e}",
            })

    # Aggregate the per-field population counts across all probed players
    agg_field_pop: dict[str, int] = {f: 0 for f in TARGET_STAT_FIELDS}
    total_matches_with_stats = 0
    total_matches = 0
    resolved = 0
    for r in results:
        cov = r.get("coverage") or {}
        total_matches += cov.get("matches_total") or 0
        total_matches_with_stats += cov.get("matches_with_stat_block") or 0
        for f, c in (cov.get("stat_field_population") or {}).items():
            agg_field_pop[f] = agg_field_pop.get(f, 0) + c
        if r.get("resolution", {}).get("ms_id"):
            resolved += 1

    return {
        "elapsed_sec": round(time.time() - t0, 2),
        "tour": tour,
        "players_probed": len(results),
        "players_resolved": resolved,
        "resolution_rate": round(100 * resolved / len(results), 1) if results else 0,
        "matches_returned": total_matches,
        "matches_with_stat_block": total_matches_with_stats,
        "stat_block_rate": (round(100 * total_matches_with_stats / total_matches, 1)
                             if total_matches else 0),
        "field_population_count": agg_field_pop,
        "field_population_pct": {
            f: (round(100 * c / total_matches_with_stats, 1)
                if total_matches_with_stats else 0)
            for f, c in agg_field_pop.items()
        },
        "per_player": results,
    }
