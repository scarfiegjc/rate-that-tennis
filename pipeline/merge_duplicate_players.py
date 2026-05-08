"""
merge_duplicate_players.py — fix duplicate player records that share the same
physical identity but have different `players.id` values because their names
differ in diacritics, casing, or whitespace.

Concrete example: api-tennis.com has two distinct event records for the same
match — one labelled "D. Džumhur" (api_key X → players.id 17380) and one
labelled "D. Dzumhur" (api_key Y → players.id 19801). The two halves of the
match end up referencing different player IDs, so player-level views (form,
match history, stats) become asymmetric.

This module:
  • finds groups of player rows that share the same NORMALIZED name
    (lower-cased, diacritics stripped, whitespace collapsed) within the same
    tour gender,
  • picks a canonical id per group (the one with the most match references —
    ties broken by lowest id),
  • updates every foreign-key reference to point at the canonical id,
  • deletes the now-orphan shadow rows.

Idempotent — second run is a no-op.

The set of foreign-key tables is hard-coded below. If you add a new table
that references players(id), add it here too.
"""

from __future__ import annotations
import unicodedata
from typing import List, Tuple

import psycopg2
import psycopg2.extras


# ─── Name normalisation ─────────────────────────────────────────────────────

def normalise_name(name: str) -> str:
    """Lower-case, strip diacritics, collapse whitespace, drop trailing dots."""
    if not name:
        return ""
    s = name.strip().lower()
    # NFKD decomposes accented characters into base + combining mark.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Collapse whitespace, normalise punctuation
    s = " ".join(s.split())
    return s


# ─── Foreign-key tables that reference players.id ───────────────────────────
# (table_name, column_name, has_unique_constraint_on_player_id)
# When `has_unique` is True, we delete the shadow row before updating to avoid
# unique-violation errors. When False, we just UPDATE.

FK_TABLES_SIMPLE: List[Tuple[str, str]] = [
    ("matches",                "first_player_id"),
    ("matches",                "second_player_id"),
]

FK_TABLES_UNIQUE_ON_PLAYER: List[Tuple[str, str]] = [
    ("player_ratings",         "player_id"),    # UNIQUE on player_id
    ("player_point_stats",     "player_id"),    # PK on player_id
    ("ms_player_links",        "player_id"),    # PK on player_id
]

# Tables with composite unique constraints — we move what we can, drop conflicts.
FK_TABLES_COMPOSITE: List[Tuple[str, str, List[str]]] = [
    # (table, fk_column, conflict_columns_for_DELETE-on-conflict)
    ("player_ratings_history", "player_id", ["player_id", "rated_at"]),
    ("player_surface_stats",   "player_id", ["player_id", "surface_id", "season"]),
    ("player_hand_splits",     "player_id", ["player_id", "vs_hand"]),
    ("serve_zones",            "player_id", ["player_id", "surface_id",
                                              "serve_number", "court_side", "zone"]),
]


# ─── Discovery ───────────────────────────────────────────────────────────────

def find_duplicate_groups(conn) -> list[dict]:
    """
    Return a list of duplicate groups — each group is a set of player rows
    that almost certainly represent the SAME physical player.

    A pair is treated as the same person ONLY when ALL of:
      • Their normalised names match (lower-case, diacritics stripped),
      • They share a country (or one's country is NULL — name+country match
        carries more weight than country presence),
      • If both have a `full_name`, the normalised full_names also match.

    Short-form name collisions like "J. Adams" / "M. Clark" — where two
    legitimately different players share an initial.surname token — are
    NOT merged unless the full_name and country agree.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
              p.id,
              p.api_key,
              p.name,
              p.full_name,
              p.country,
              (SELECT COUNT(*) FROM matches m
                 WHERE m.first_player_id = p.id OR m.second_player_id = p.id) AS match_count,
              (SELECT COUNT(*) FROM player_ratings pr WHERE pr.player_id = p.id) AS ratings_count
            FROM players p
            WHERE p.name IS NOT NULL AND LENGTH(TRIM(p.name)) > 0
        """)
        rows = cur.fetchall()

    # First-pass bucket by normalised SHORT name.
    by_norm: dict[str, list[dict]] = {}
    for r in rows:
        n = normalise_name(r["name"])
        if not n:
            continue
        by_norm.setdefault(n, []).append(dict(r))

    groups = []
    for norm, members in by_norm.items():
        if len(members) < 2:
            continue

        # Now refine within the bucket: cluster members that genuinely look
        # like the same person (same country, same full_name when both have it).
        clusters: list[list[dict]] = []
        for m in members:
            placed = False
            m_country = (m.get("country") or "").strip().upper() or None
            m_fullnorm = normalise_name(m.get("full_name") or "")
            for c in clusters:
                head = c[0]
                h_country = (head.get("country") or "").strip().upper() or None
                h_fullnorm = normalise_name(head.get("full_name") or "")
                # Country: match if same OR either is NULL.
                country_ok = (m_country == h_country) or (not m_country) or (not h_country)
                # Full-name: if both have one, must agree (after normalisation).
                if m_fullnorm and h_fullnorm:
                    fullname_ok = (m_fullnorm == h_fullnorm)
                else:
                    fullname_ok = True   # at least one missing — fall back to short-name+country
                if country_ok and fullname_ok:
                    c.append(m)
                    placed = True
                    break
            if not placed:
                clusters.append([m])

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            # Sort: most matches first, then most ratings, then lowest id (canonical first).
            cluster.sort(key=lambda x: (-x["match_count"], -x["ratings_count"], x["id"]))
            groups.append({
                "norm_name": norm,
                "country":   (cluster[0].get("country") or None),
                "full_name": cluster[0].get("full_name") or None,
                "members":   cluster,
            })

    # Order groups by total match count across members (most impactful first).
    groups.sort(key=lambda g: -sum(m["match_count"] for m in g["members"]))
    return groups


# ─── Per-group merge ─────────────────────────────────────────────────────────

def _merge_pair(cur, canonical_id: int, shadow_id: int) -> dict:
    """
    Move every reference to shadow_id over to canonical_id, then delete the
    shadow row. Returns a dict of row counts touched.
    """
    counts: dict = {}

    # 1. Simple FKs — just UPDATE.
    for table, col in FK_TABLES_SIMPLE:
        cur.execute(
            f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
            (canonical_id, shadow_id),
        )
        counts[f"{table}.{col}"] = cur.rowcount

    # 2. Player-id-unique tables — delete shadow's row when canonical already has one.
    for table, col in FK_TABLES_UNIQUE_ON_PLAYER:
        # Drop shadow rows that would conflict with canonical's existing row.
        cur.execute(f"""
            DELETE FROM {table}
             WHERE {col} = %s
               AND EXISTS (SELECT 1 FROM {table} t2 WHERE t2.{col} = %s)
        """, (shadow_id, canonical_id))
        dropped = cur.rowcount
        # Move the rest.
        cur.execute(f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                    (canonical_id, shadow_id))
        counts[f"{table}.{col}"] = {"moved": cur.rowcount, "dropped_dupes": dropped}

    # 3. Composite-unique tables — drop conflicting shadow rows then UPDATE.
    for table, col, key_cols in FK_TABLES_COMPOSITE:
        # Predicate matching canonical's existing row's key columns (substituting
        # canonical_id for the {col} value of the shadow's row).
        non_player_keys = [k for k in key_cols if k != col]
        if non_player_keys:
            on_clause = " AND ".join(f"t2.{k} = src.{k}" for k in non_player_keys)
            cur.execute(f"""
                DELETE FROM {table} src
                 WHERE src.{col} = %s
                   AND EXISTS (
                       SELECT 1 FROM {table} t2
                        WHERE t2.{col} = %s AND {on_clause}
                   )
            """, (shadow_id, canonical_id))
        else:
            cur.execute(f"""
                DELETE FROM {table}
                 WHERE {col} = %s
                   AND EXISTS (SELECT 1 FROM {table} t2 WHERE t2.{col} = %s)
            """, (shadow_id, canonical_id))
        dropped = cur.rowcount
        cur.execute(f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                    (canonical_id, shadow_id))
        counts[f"{table}.{col}"] = {"moved": cur.rowcount, "dropped_dupes": dropped}

    # 4. Finally drop the shadow row.
    cur.execute("DELETE FROM players WHERE id = %s", (shadow_id,))
    counts["players_deleted"] = cur.rowcount

    return counts


def merge_group(conn, group: dict, dry_run: bool = True) -> dict:
    """
    Merge a single duplicate group into its canonical member.
    Members must already be ordered with the canonical first.
    """
    members = group["members"]
    if len(members) < 2:
        return {"skipped": "single-member group"}

    canonical = members[0]
    shadows   = members[1:]

    report = {
        "norm_name": group["norm_name"],
        "canonical": {
            "id": canonical["id"], "name": canonical["name"],
            "api_key": canonical["api_key"],
            "match_count": canonical["match_count"],
        },
        "shadows": [],
        "dry_run": dry_run,
    }

    if dry_run:
        for s in shadows:
            report["shadows"].append({
                "id": s["id"], "name": s["name"], "api_key": s["api_key"],
                "match_count": s["match_count"],
                "would_merge": True,
            })
        return report

    with conn.cursor() as cur:
        for s in shadows:
            counts = _merge_pair(cur, canonical["id"], s["id"])
            report["shadows"].append({
                "id": s["id"], "name": s["name"], "api_key": s["api_key"],
                "merge_counts": counts,
            })
    conn.commit()
    return report


def merge_all(conn, dry_run: bool = True, limit: int = 0) -> dict:
    """
    Find every duplicate group and merge them. With dry_run=True, just reports
    what would happen.
    """
    groups = find_duplicate_groups(conn)
    if limit and limit > 0:
        groups = groups[:limit]

    reports = []
    for g in groups:
        reports.append(merge_group(conn, g, dry_run=dry_run))

    return {
        "dry_run":          dry_run,
        "groups_found":     len(groups),
        "groups_processed": len(reports),
        "groups":           reports,
    }
