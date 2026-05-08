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


# Cached rankings name → ms_id index, populated lazily on first lookup
# within a single spike invocation.
_RANK_INDEX_CACHE: dict[str, dict] = {}  # tour -> {full_lower_name: {id, name, currentRank, countryAcr}}


def _build_rankings_index(tour: str = "atp", max_pages: int = 20, page_size: int = 200) -> dict:
    """
    Fetch the full singles-ranking list for the given tour and build a
    lookup index keyed by lowercased full name. Each ranking page is one
    API call. ATP/WTA both top out around ~2000 ranked singles players.

    The /ranking/singles endpoint is the only place we get a stable
    {id, name} pairing — search returns name+birthday but no id, and the
    /player list is sorted alphabetically (so we'd need to walk the
    entire list to find anyone past the A's).
    """
    if tour in _RANK_INDEX_CACHE:
        return _RANK_INDEX_CACHE[tour]

    index: dict[str, dict] = {}
    surnames: dict[str, list[dict]] = {}
    pages_fetched = 0
    last_count = 0
    sample_first_row = None
    sample_first_keys: list[str] = []
    for page_no in range(1, max_pages + 1):
        page = _get(
            f"/tennis/v2/{tour}/ranking/singles",
            params={"pageSize": page_size, "pageNo": page_no},
        )
        if not page.get("ok"):
            break
        body = page.get("data")
        rows: list = body if isinstance(body, list) else (
            body.get("data") if isinstance(body, dict) else None
        ) or []
        if not rows:
            break
        last_count = len(rows)
        pages_fetched += 1
        # Capture first row of first page so we can see the actual response shape
        if sample_first_row is None and rows:
            r0 = rows[0]
            sample_first_row = r0 if isinstance(r0, (dict, list, str, int, float)) else str(r0)
            if isinstance(r0, dict):
                sample_first_keys = sorted(r0.keys())
        for r in rows:
            if not isinstance(r, dict):
                continue
            # Some endpoints wrap the player as {player: {...}} (the race format)
            inner = r.get("player") if isinstance(r.get("player"), dict) else r
            name = (inner.get("name") or "").strip()
            if not name:
                continue
            entry = {
                "id": inner.get("id"),
                "name": name,
                "currentRank": r.get("currentRank") or r.get("position") or inner.get("currentRank"),
                "countryAcr": inner.get("countryAcr"),
            }
            if not entry["id"]:
                continue
            index[name.lower()] = entry
            tokens = name.replace(".", "").split()
            if tokens:
                surnames.setdefault(tokens[-1].lower(), []).append(entry)
        if len(rows) < page_size:
            break

    cache = {
        "by_name": index, "by_surname": surnames,
        "pages": pages_fetched, "rows_last_page": last_count,
        "sample_first_row": sample_first_row,
        "sample_first_keys": sample_first_keys,
    }
    _RANK_INDEX_CACHE[tour] = cache
    return cache


def _resolve_matchstat_id(player: dict, tour: str = "atp", rank_idx: Optional[dict] = None) -> dict:
    """
    Try to find this player in Matchstat's player list by name.
    Returns {ms_id, ms_name, strategy, candidates}.
    """
    full = (player.get("full_name") or player.get("name") or "").strip()
    short = (player.get("name") or "").strip()
    if not full and not short:
        return {"ms_id": None, "strategy": "no-name"}

    last_token = full.replace(".", "").split()[-1] if full else (
        short.replace(".", "").split()[-1] if short else "")
    first_initial = ((short or full)[:1] or "").lower()

    # Strategy 1 (primary): rankings index lookup. Rankings are the only
    # endpoint that returns {id, name} pairs sorted by relevance (top
    # players first). Pre-built once per spike run by _build_rankings_index.
    if rank_idx is not None and last_token:
        # 1a: exact match on lowered full name
        hit = rank_idx["by_name"].get(full.lower())
        if hit and hit.get("id"):
            return {"ms_id": hit["id"], "ms_name": hit["name"],
                    "strategy": "rankings-exact", "rank": hit.get("currentRank")}
        # 1b: surname bucket — disambiguate by first initial
        bucket = rank_idx["by_surname"].get(last_token.lower(), [])
        if len(bucket) == 1:
            r = bucket[0]
            return {"ms_id": r["id"], "ms_name": r["name"],
                    "strategy": "rankings-surname", "rank": r.get("currentRank")}
        if len(bucket) > 1 and first_initial:
            initials = [b for b in bucket
                        if (b["name"][:1] or "").lower() == first_initial]
            if len(initials) == 1:
                r = initials[0]
                return {"ms_id": r["id"], "ms_name": r["name"],
                        "strategy": "rankings-initial", "rank": r.get("currentRank")}
            if len(initials) > 1:
                return {"ms_id": None, "strategy": "ambiguous-initial",
                        "candidates": initials[:5]}
        if len(bucket) > 1:
            return {"ms_id": None, "strategy": "ambiguous-surname",
                    "candidates": bucket[:5]}

    # Strategy 2: search endpoint — returns name+birthday but no id.
    # Useful only as a sanity probe to confirm a player exists somewhere.
    if last_token:
        search = _get("/tennis/v2/search", params={"search": last_token})
        if search.get("ok"):
            sbody = search.get("data") or {}
            buckets = sbody.get("data") if isinstance(sbody, dict) else None
            if isinstance(buckets, list):
                # Bucket order per docs: player_atp, player_wta, tournament_atp, tournament_wta
                want = "player_atp" if tour == "atp" else "player_wta"
                for b in buckets:
                    if (b.get("category") or "").lower() == want:
                        results = b.get("result") or []
                        # Print one full record so we can see if 'id' is there
                        if results:
                            return {
                                "ms_id": results[0].get("id"),
                                "ms_name": results[0].get("name"),
                                "strategy": "search",
                                "search_total": b.get("total"),
                                "search_first_record_keys": sorted(list(results[0].keys())),
                                "search_first_record": results[0],
                            }

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


def _spike_one_player(player: dict, tour: str = "atp", rank_idx: Optional[dict] = None) -> dict:
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
    resolved = _resolve_matchstat_id(player, tour=tour, rank_idx=rank_idx)
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

    # Build the rankings name→id index ONCE for the whole spike run. This is
    # the path a real backfill would use too: cache name→id locally, then
    # only call player-specific endpoints for the ones we resolved.
    t0 = time.time()
    rank_idx = _build_rankings_index(tour=tour)
    rankings_meta = {
        "pages_fetched": rank_idx.get("pages", 0),
        "names_indexed": len(rank_idx.get("by_name", {})),
        "surnames_indexed": len(rank_idx.get("by_surname", {})),
        "rows_last_page": rank_idx.get("rows_last_page", 0),
        "sample_first_row": rank_idx.get("sample_first_row"),
        "sample_first_keys": rank_idx.get("sample_first_keys"),
    }

    results: list[dict] = []
    for p in sample:
        try:
            results.append(_spike_one_player(p, tour=tour, rank_idx=rank_idx))
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
        "rankings_index": rankings_meta,
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
