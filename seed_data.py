#!/usr/bin/env python3
"""
ratethat.tennis — Initial data seed via pg8000
Runs: sync_event_types + today's fixtures
"""
import subprocess, sys, os, tempfile, json, time
from datetime import date

print("Setting up...")
tmp = tempfile.mkdtemp()
subprocess.run([sys.executable, "-m", "pip", "install", "pg8000", "requests", "--target", tmp, "-q"], check=True)
sys.path.insert(0, tmp)

import pg8000.native
import requests

API_KEY  = "7b2c30d69f93cbbaa699c7a65483e620ec4bf53adc0a105eb9d38876d307002a"
API_BASE = "https://api.api-tennis.com/tennis"

def api_get(method, **params):
    params["APIkey"] = API_KEY
    params["method"] = method
    r = requests.get(API_BASE, params=params, timeout=30)
    data = r.json()
    if data.get("error"):
        return []
    return data.get("result", [])

def classify(type_str):
    t = type_str.lower()
    is_doubles = "double" in t
    if "atp" in t:       return "ATP", "Men", is_doubles
    if "wta" in t:       return "WTA", "Women", is_doubles
    if "challenger men" in t: return "Challenger", "Men", is_doubles
    if "challenger wom" in t: return "Challenger", "Women", is_doubles
    if "itf men" in t:   return "ITF", "Men", is_doubles
    if "itf wom" in t:   return "ITF", "Women", is_doubles
    if "boys" in t:      return "Junior", "Men", is_doubles
    if "girls" in t:     return "Junior", "Women", is_doubles
    if "mixed" in t:     return "Mixed", "Mixed", is_doubles
    if "exhibition" in t: return "Exhibition", "Mixed", is_doubles
    if "teams" in t:     return "Teams", "Mixed", is_doubles
    return "Other", "Unknown", is_doubles

print("Connecting to Railway...")
conn = pg8000.native.Connection(
    user="postgres",
    password="DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS",
    host="switchyard.proxy.rlwy.net",
    port=39343,
    database="railway",
    ssl_context=True
)
print("Connected ✓")

# ── 1. Event types ──────────────────────────────────────────
print("\n[1/3] Syncing event types...")
events = api_get("get_events")
for e in events:
    cat, gender, is_doubles = classify(e["event_type_type"])
    conn.run("""
        INSERT INTO event_types (api_key, type_name, tour_category, gender, is_doubles)
        VALUES (:key, :name, :cat, :gender, :dbl)
        ON CONFLICT (api_key) DO UPDATE SET
            type_name=EXCLUDED.type_name, tour_category=EXCLUDED.tour_category,
            gender=EXCLUDED.gender, is_doubles=EXCLUDED.is_doubles
    """, key=e["event_type_key"], name=e["event_type_type"], cat=cat, gender=gender, dbl=is_doubles)
print(f"  ✓ {len(events)} event types loaded")

# ── 2. Today's fixtures ─────────────────────────────────────
today = date.today().strftime("%Y-%m-%d")
print(f"\n[2/3] Fetching fixtures for {today}...")
fixtures = api_get("get_fixtures", date_start=today, date_stop=today)
print(f"  Got {len(fixtures)} matches from API")

surface_cache = {}
et_cache      = {}
t_cache       = {}
p_cache       = {}
inserted = updated = 0

def get_surface_id(name):
    name = name.strip().title() if name else "Unknown"
    if name not in surface_cache:
        rows = conn.run("SELECT id FROM surfaces WHERE name=:n", n=name)
        if rows:
            surface_cache[name] = rows[0][0]
        else:
            rows = conn.run("INSERT INTO surfaces (name) VALUES (:n) ON CONFLICT (name) DO NOTHING RETURNING id", n=name)
            if rows:
                surface_cache[name] = rows[0][0]
            else:
                surface_cache[name] = conn.run("SELECT id FROM surfaces WHERE name=:n", n=name)[0][0]
    return surface_cache[name]

def get_et_id(type_str):
    if type_str not in et_cache:
        rows = conn.run("SELECT id FROM event_types WHERE type_name=:n", n=type_str)
        if rows:
            et_cache[type_str] = rows[0][0]
        else:
            cat, gender, is_dbl = classify(type_str)
            rows = conn.run("""
                INSERT INTO event_types (api_key, type_name, tour_category, gender, is_doubles)
                VALUES (-(nextval('event_types_id_seq'::regclass)), :n, :c, :g, :d)
                ON CONFLICT DO NOTHING RETURNING id
            """, n=type_str, c=cat, g=gender, d=is_dbl)
            if rows:
                et_cache[type_str] = rows[0][0]
            else:
                et_cache[type_str] = conn.run("SELECT id FROM event_types WHERE type_name=:n", n=type_str)[0][0]
    return et_cache[type_str]

def get_tournament_id(api_key, name, et_id, surface_id):
    if api_key not in t_cache:
        rows = conn.run("""
            INSERT INTO tournaments (api_key, name, event_type_id, surface_id)
            VALUES (:k, :n, :e, :s)
            ON CONFLICT (api_key) DO UPDATE SET name=EXCLUDED.name, updated_at=NOW()
            RETURNING id
        """, k=api_key, n=name.strip(), e=et_id, s=surface_id)
        t_cache[api_key] = rows[0][0]
    return t_cache[api_key]

def get_player_id(api_key, name, logo):
    if api_key not in p_cache:
        rows = conn.run("""
            INSERT INTO players (api_key, name, logo_url)
            VALUES (:k, :n, :l)
            ON CONFLICT (api_key) DO UPDATE SET
                name=COALESCE(EXCLUDED.name, players.name),
                logo_url=COALESCE(EXCLUDED.logo_url, players.logo_url),
                updated_at=NOW()
            RETURNING id
        """, k=api_key, n=name, l=logo)
        p_cache[api_key] = rows[0][0]
    return p_cache[api_key]

for ev in fixtures:
    try:
        et_id  = get_et_id(ev.get("event_type_type","Unknown"))
        t_id   = get_tournament_id(ev["tournament_key"], ev.get("tournament_name","?"), et_id, get_surface_id(""))
        p1_id  = get_player_id(ev["first_player_key"],  ev["event_first_player"],  ev.get("event_first_player_logo"))
        p2_id  = get_player_id(ev["second_player_key"], ev["event_second_player"], ev.get("event_second_player_logo"))
        is_live = ev.get("event_live") == "1"
        is_qual = str(ev.get("event_qualification","False")).lower() == "true"
        is_dbl  = "double" in ev.get("event_type_type","").lower()

        rows = conn.run("""
            INSERT INTO matches (
                api_event_key, tournament_id, event_type_id,
                first_player_id, second_player_id,
                event_date, event_time, tournament_round, season,
                is_qualification, is_doubles,
                final_result, game_result, serve, winner, event_status,
                is_live, raw_json
            ) VALUES (
                :ek, :tid, :etid, :p1, :p2,
                :dt, :tm, :rd, :se,
                :iq, :id,
                :fr, :gr, :sv, :wn, :st,
                :lv, :raw
            )
            ON CONFLICT (api_event_key) DO UPDATE SET
                final_result=EXCLUDED.final_result,
                game_result=EXCLUDED.game_result,
                winner=EXCLUDED.winner,
                event_status=EXCLUDED.event_status,
                is_live=EXCLUDED.is_live,
                raw_json=EXCLUDED.raw_json,
                updated_at=NOW()
            RETURNING id, (xmax=0) AS was_inserted
        """,
            ek=ev["event_key"], tid=t_id, etid=et_id, p1=p1_id, p2=p2_id,
            dt=ev["event_date"], tm=ev.get("event_time"), rd=ev.get("tournament_round"),
            se=ev.get("tournament_season"), iq=is_qual, id=is_dbl,
            fr=ev.get("event_final_result"), gr=ev.get("event_game_result"),
            sv=ev.get("event_serve"), wn=ev.get("event_winner"), st=ev.get("event_status"),
            lv=is_live, raw=json.dumps(ev)
        )
        match_id, was_ins = rows[0]
        if was_ins: inserted += 1
        else:       updated  += 1

        for sc in ev.get("scores", []):
            s1 = str(sc.get("score_first",""))
            s2 = str(sc.get("score_second",""))
            conn.run("""
                INSERT INTO match_scores (match_id, set_number, score_first, score_second, is_tiebreak)
                VALUES (:m, :sn, :s1, :s2, :tb)
                ON CONFLICT (match_id, set_number) DO UPDATE SET
                    score_first=EXCLUDED.score_first, score_second=EXCLUDED.score_second
            """, m=match_id, sn=sc.get("score_set"), s1=s1, s2=s2, tb=("." in s1 or "." in s2))

    except Exception as e:
        print(f"  ⚠ skipped event {ev.get('event_key')}: {e}")

print(f"  ✓ Inserted: {inserted}, Updated: {updated}")

# ── 3. Summary ──────────────────────────────────────────────
print("\n[3/3] Database summary:")
rows = conn.run("SELECT COUNT(*) FROM matches")
print(f"  Matches:     {rows[0][0]}")
rows = conn.run("SELECT COUNT(*) FROM players")
print(f"  Players:     {rows[0][0]}")
rows = conn.run("SELECT COUNT(*) FROM tournaments")
print(f"  Tournaments: {rows[0][0]}")
rows = conn.run("SELECT COUNT(*) FROM match_scores")
print(f"  Set scores:  {rows[0][0]}")

conn.close()
print("\n🎾 Seed complete! ratethat.tennis database is live with today's data.")
