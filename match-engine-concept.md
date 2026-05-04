# ratethat.tennis — Match Engine: Design Concept

## Core philosophy
Every competitor (TennisBrain, TennisViz, Tennis Explorer, WinnerOdds) shows data AT the user.
ratethat.tennis should show a DECISION to the user, supported by data.

The bettor's question is always: "Is there value here?" Answer that first, then justify it.

---

## Page hierarchy

### 1. Match header (always visible)
- Tournament + surface + round badges
- Player cards: avatar, rank, nationality, form dots (last 5)
- Our prediction tension bar (42% vs 58%) — the headline number
- Market edge strip at bottom: odds / implied prob / our edge / confidence

### 2. Five tabs
Overview | Form | Head to head | Serve | Intelligence

---

## Tab breakdown

### Overview
- **Radar/spider chart** (6 dimensions): Serve · Return · Surface form · BP conversion · Mental · Consistency
  - Two overlapping polygons, each player a different colour
  - Immediate shape-vs-shape read: if Alcaraz's polygon is bigger on the clay side, you see it instantly
- **Stat comparison bars** (ratethat.dog-style)
  - Each metric is one row: Player 1 bar ← label → Player 2 bar
  - Values shown as numbers at each end
  - **Switcher**: Overall / Clay / vs Top 20 / Last 20 — swaps the underlying dataset

### Form
- Line chart of "performance index" (our ML score, not raw W/L) over last 15 matches
- **Surface switcher**: All / Clay / Hard / Grass — filters to matches on that surface
- Summary cards: avg index, momentum (+/-), win rate

### Head to head
- All-time record summary with surface breakdown bars
- Chronological list of recent meetings (tournament, round, surface, score, winner dot)

### Serve
- **Three-way switcher**: Player · Serve number (1st/2nd) · Court side (Deuce/Ad)
- Three serve zones shown as coloured tiles (Wide / Body / T)
  - Colour intensity = frequency (light = rare, dark = dominant zone)
- Stat cards: serve in %, avg speed, aces/match

### Intelligence
- **Factor cards** with model weight bar (the "deep reasoning" rendered as human-readable drivers)
  - High / Medium / Low impact badges
  - Each card = one model feature with plain-English explanation
- **AI narrative paragraph** — the "story" of why our model predicts this
- **Historical analogue** — most similar matchup in training data
- **Recommended bet types** with our edge % vs market for each

---

## Competitor gaps we fill

| Platform | What they do well | What's missing |
|---|---|---|
| TennisBrain | Live Betfair price integration | Ugly UI, no serve/pattern analysis |
| TennisViz | Deep database, D3 charts | Academic feel, no bettor-first hierarchy |
| Tennis Explorer | 35k player database, H2H | No visualisations, overwhelmingly dense |
| WinnerOdds | 1M+ match model, 100+ bookmakers | No player style context, no narrative |
| Matchstat | 20yr track record | No interactive charts, no form visualisation |

**Our differentiation**:
1. Model edge vs market is the HEADLINE — not buried
2. Form lines use our ML performance index, not just W/L dots
3. Serve heatmap gives stylistic context (how their games mesh)
4. Intelligence tab makes the model's reasoning legible
5. Surface switcher on every chart — surface is everything in tennis

---

## Data mapping to schema

| UI element | Schema source |
|---|---|
| Prediction probability | ML model output (to build) |
| Radar dimensions | player_ratings (serve_rating, clay/hard/grass_rating, consistency_score, form_score) + match_stats from sa_matches |
| Form line chart | Rolling performance index derived from sa_matches + match_ratings.quality_score |
| Stat bars | sa_matches (w_ace, w_1stIn, w_bpSaved etc.) + player_surface_stats |
| H2H list | matches table filtered to both player IDs |
| Serve heatmap | Not in current schema — requires serve zone data from Hawk-Eye/Match Charting Project (future data source) |
| Intelligence factors | model feature importances (to expose via API) |
| Market edge | Bookmaker odds API (not yet in schema — needs bookmaker_odds table) |

---

## Recommended schema additions

1. **bookmaker_odds** table — match_id, bookmaker, player, decimal_odds, implied_prob, fetched_at
2. **model_predictions** table — match_id, predicted_prob_p1, model_version, feature_importances (JSONB), predicted_at
3. **serve_zones** table — match_id, player_id, serve_number, court_side, zone (W/B/T), count, pct (when data available)
4. **performance_index** column in match_ratings — pre-computed rolling ML score per player per match
