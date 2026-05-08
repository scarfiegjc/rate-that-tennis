# ratethat.tennis — Roadmap

> Living document. Read this when picking up work on the site.
> Last updated: May 2026.

## How to use this doc

Three layers, in priority order:

1. **Phase 1 — Make it work** (now). Core model accuracy and site functionality. Until these are solid, nothing else matters.
2. **Phase 2 — Make it trustworthy** (next). Public track record, transparent methodology, polish.
3. **Phase 3 — Make it different** (later). The competitive feature gaps that turn this from "another tennis prediction site" into something people remember and recommend.

Below each phase is a list of concrete things to do, why they matter, and a rough sense of effort. The competitive research that informed phases 2 and 3 is appended at the end as reference.

---

# Phase 1 — Make it work

**Goal: site loads cleanly, model wins more than it loses, daily pipeline is dependable.**

Nothing in phase 2 or 3 has any value until this is true. A beautiful site with a 48% win rate is worse than no site at all — it actively damages trust.

## 1.1 Investigate why production accuracy is below 50%

The backtest reports 66.5% accuracy on 2015–2024 walk-forward data, with AUC 0.730 and a +2.6% edge over Elo. Yesterday's live predictions came in below 50%. That gap is the single most important problem to solve, because either:

- The backtest is overfit / leaks future data and the real number is much lower, **or**
- The production prediction pipeline is computing features differently from training, **or**
- The pipeline is using stale or wrong data (player ID mismatches, missing features, etc.), **or**
- One day is statistically meaningless — with only ~10–20 matches a day, going 4/10 vs 7/10 is normal noise.

**The first thing to figure out is which of those it is.** That diagnostic should happen before any other work.

Concrete steps:

- Pull the last 30–60 days of production predictions from `model_predictions` joined with actual match outcomes. Compute rolling accuracy. If it's been around 60–65%, yesterday is just variance — keep going. If it's been hovering around 50% for weeks, the model has a real problem.
- Compare a handful of live-predicted matches against what `ml/predict.py` would produce if we re-ran the same inputs *now*. They should match. If they don't, there's a freshness or feature-computation bug.
- Pick 5 specific predictions from yesterday and walk through the feature values that fed into them. Spot-check whether ratings, form, H2H counts look right for those players.
- Audit the feature pipeline for **temporal leakage**: any feature that uses match data from after the prediction was made will inflate backtest accuracy and never reproduce live.
- Check that production is using the latest trained model artifact, not a stale one.

**If the model is genuinely under-performing** (not just noisy):

- Retrain on data through the most recent week available (the model loses ground if it's months stale — surface form changes constantly).
- Verify the calibration step is running. Raw probabilities can be 65% accurate but badly calibrated, which kills "edge vs market" calculations even when win rate is fine.
- Check that the ensemble weights (XGBoost / LightGBM / Logistic) are being applied correctly in production.

## 1.2 Get the site reliably functional

Right now the build exists but parts feel rough. Make sure end-to-end the user journey works without dead ends:

- Homepage loads today's matches without errors and with predictions populated for every match where we have data.
- Surface filter actually filters.
- Match detail page loads in under 2 seconds and all 6 tabs render content (no empty states or "data not available" unless that's genuinely the case).
- Player page loads and all 4 tabs work.
- Live page reflects actual live state.
- API health check is green and stays green.
- Mobile responsive layout doesn't break on phone-sized screens.

## 1.3 Daily pipeline reliability

The Railway scheduler runs fixtures + odds + predictions automatically. Make sure:

- The scheduler is actually firing on time (check logs).
- Each step's failure is visible (alerting, even just an email or Slack ping).
- If a step fails, the next step doesn't run on stale data without warning.
- The `pipeline_runs` table is being populated and we can audit any day's run.

## 1.4 Bare minimum trust signals

Even at this phase, two things should be visible to anyone who lands on the site:

- A clear "this is what the model has done historically" page — even just the backtest results presented honestly.
- A footer note that this is a research preview / beta. Setting expectations now is much easier than apologising later.

---

# Phase 2 — Make it trustworthy

**Goal: someone visiting for the first time can decide within 30 seconds whether to take this seriously.**

## 2.1 Public predictions tracker

The single biggest trust builder in this category. WinnerOdds publishes their full P&L since launch. Predixsport publishes every historical prediction with outcome.

A page at `/predictions/history` showing:

- Every prediction we've made
- Whether it was right
- Rolling accuracy (last 30 days, last 90 days, all time)
- Performance broken down by surface and tournament level
- Hypothetical P&L if you'd bet level stakes on every value pick

The data is already in `model_predictions` — this is mostly a frontend page plus a small API endpoint.

**Effort: small (a few days).**

## 2.2 Honest methodology page

A `/how-it-works` page explaining in plain English:

- What data we use (and what we don't)
- The 13 RTT rating dimensions and how each is computed
- How the win-probability model works at a high level
- What "edge vs market" means and how we calculate it
- Known limitations (e.g. lower-tour matches have less data, model is weaker on returning players from injury, etc.)

Trust comes from honesty, not from bragging. WinnerOdds wins customers by promising a refund if you don't profit. We can win customers by being the only site that openly says where the model is weak.

**Effort: small.**

## 2.3 Visual polish pass

The site is functional but not yet *credible-looking*. Specifically:

- Typography hierarchy: headlines vs body vs captions. Currently feels flat.
- Spacing rhythm: consistent vertical spacing between sections.
- Colour usage: surface badges and edge indicators should feel branded and intentional.
- Loading states: skeleton placeholders, not just spinners.
- Error states: friendly, useful messages instead of raw 500s.
- Empty states: tell the user *why* something is empty (no matches scheduled vs data missing).

This is where TennisBrain currently fails — the data is good, the presentation kills credibility.

**Effort: medium (a week or so of design + implementation).**

## 2.4 Mobile-first review

Most rivals have weak mobile experiences. If we're sharp on mobile, we win the casual share-from-Twitter audience that Tennis Explorer is too dated to capture.

Every page should be tested at 375px wide (iPhone SE size). Match cards, charts, tabs — all of it.

**Effort: small to medium depending on what's broken.**

---

# Phase 3 — Make it different

**Goal: features no competitor has all at once.**

Pulled from the competitive research below. Listed in priority order — ones at the top have the best ratio of impact to effort.

## 3.1 Player comparison tool

Pick two players, see RTT scores, surface ratings, and skill ratings side by side. Big visual, headline winner-prediction at the top. This out-flanks Tennis Explorer's H2H feature on design alone, and H2H is *their* hero feature.

**Why this matters:** it's the most shareable feature in tennis content. People love comparing players. Every "Sinner vs Alcaraz on clay" search query is a potential entry point to the site.

## 3.2 Set-score probability distribution

Predixsport does this. We have the data. On the match page, instead of "Player A 67%", show:

- 6-3 6-4: 18%
- 6-4 6-2: 15%
- 6-3 6-3: 12%
- ... etc

Visual: a heatmap or distribution chart. Looks like serious data science, increases time on page.

## 3.3 Multi-bookmaker odds comparison

The Odds API connection already exists. Instead of showing one bookmaker, show the spread across 5–10 books, highlight the best price on each side, and compare against our model's fair price. This is what bettors actually want.

## 3.4 Watchlist / favourite players

Universal gap in this space — nobody does personalisation. Logged-in users can "follow" players and see them surfaced in a personalised section on the homepage. Drives return visits.

**Effort: medium.** Requires user auth, which is a meaningful build.

## 3.5 Serve-zone visualisation

TennisViz makes this look great. We have access to Match Charting Project data through Sackmann. A heatmap showing where a player serves on key points (wide / body / T) by surface and side of court is a genuine "wow" feature.

**Effort: medium-large.** Charting Project data needs to be joined to our players table, then visualised.

## 3.6 Power Rankings page

Top 100 RTT scores on a single page, surface filterable, with biggest movers highlighted. Evergreen content that ranks in search and gives people a reason to visit weekly.

## 3.7 AI chat / "ask the model"

SportBot AI's "AI Sports Desk" is genuinely useful — ask "why is the model picking Sinner today?" and get a plain-English answer that references the actual features. Fits naturally on top of the existing Intelligence tab.

**Effort: medium.** Requires an LLM integration and a layer that grounds responses in our data.

## 3.8 Tournament-level forecast / bracket

For an active tournament, simulate the bracket forward and show probability of each player winning the tournament. Updates after every match. Ultimate Tennis Statistics does it; nobody does it well.

## 3.9 Mobile app or PWA

Only Ultimate Tennis Statistics has a real mobile app. Even a Progressive Web App (installable from the browser, no app store) would be more than the field offers.

---

# Reference: competitive analysis (May 2026)

The full research that informed this roadmap.

## The landscape

Tennis prediction sites fall into four camps:

- **Old database sites** — Tennis Explorer, Tennis Abstract, Ultimate Tennis Statistics. Huge stat depth, free, ageing design, beloved by hardcore fans. Tennis Explorer is by far the biggest by traffic.
- **ML black-box subscription services** — TennisBrain, WinnerOdds. Paid, claim a model edge, pitch themselves to value bettors. Light on visual design, heavy on data.
- **Newer AI-first sites** — Predixsport, SportBot AI, TennisPredictions.ai. Modern look, full probability distributions, often free at the edges with paid tiers.
- **Pro-grade tools** — TennisViz. Sells to broadcasters and players' coaches. Not a direct competitor, but the inspiration for shot-zone analytics.

## The five named competitors

**TennisBrain** — ML/AI engine, 10+ years of iteration, Betfair odds updated every 30 min, monthly subscription. Methodology is solid. But the site looks tired. No public Trustpilot/Reddit reputation, low traffic visibility on Similarweb. Biggest weakness: it doesn't *look* credible at first glance.

**TennisViz** — Pro-grade analytics with Hawk-Eye-style ball tracking, shot quality scored 0–10. Sells via Performance Portal (players/coaches) and Media Portal (broadcasters). Not a direct competitor — they're B2B.

**Tennis Explorer** — The giant. ~45,000 global Similarweb rank, miles ahead of everyone else. 35,000-player database, free, no signup. Hero feature: H2H comparison. Audience skews 55–64 male. Reviews say "interface overloaded and complex" and "insufficient depth despite breadth." A beatable incumbent.

**WinnerOdds** — Premium ML service, €99/month or €65/month on a 6-month plan. Analyses 1M+ matches with neural nets. Money-back guarantee if you don't profit over 6 months with 1,000+ bets. Public P&L tracker (claim £40k profit since launch). Trust signal: huge. Design: utilitarian.

**Matchstat** — H2H specialist, 20+ years of stats. Smaller traffic (~355,000 global rank) but more modern feel than Tennis Explorer. 90% male audience, 35–44. Free, with editorial-style match previews.

## Other competitors worth tracking

- **Tennis Abstract** (Jeff Sackmann) — built on the *same data we use*. Free, gold-standard for stat geeks. Player pages are the heart. Match Charting Project for shot-by-shot data. Design is "spreadsheet on a webpage."
- **Ultimate Tennis Statistics** — Elo ratings, GOAT list, tournament forecasts via "Tennis Crystal Ball." Has an iOS app. ATP only.
- **Predixsport** — Newer, slick. 500+ features, surface-aware, full probability distributions over set scores, public backtest of all historical predictions. Closest to what we're building.
- **SportBot AI** — Elo++ with 13 signals including SPW/RPW. Has an "AI Sports Desk" chatbot. Modern UX, free tier with verified ROI claims. Aggregates 50+ bookmakers.
- **Long tail** — TennisPredictions.ai, Tennis Tonic, Tennis Insight, Dimers, Steve G Tennis, TennisPrediction.com. Editorial picks, community forums, general sportsbook content.

## Traffic ranking (approximate)

1. Tennis Explorer (~45K global Similarweb rank — biggest by far)
2. Tennis Abstract (steady niche traffic from data community)
3. Matchstat (~355K)
4. WinnerOdds (small but premium / different game)
5. TennisBrain (no meaningful Similarweb signal)
6. TennisViz (B2B, not consumer)

The pattern: free + comprehensive + dated = big audience (Tennis Explorer); paid + premium + niche = small but profitable (WinnerOdds). The *worst* spot to occupy is paid subscription with mediocre design — roughly where TennisBrain sits.

The newer AI sites (Predixsport, SportBot AI) are still sub-scale, but they're playing our game and are who we should benchmark against.

## UX ranking

Nobody is brilliant in this category. The bar is genuinely low. Roughly:

1. **SportBot AI / Predixsport** — modern, clean, dark themes, AI-pitched. Best in class.
2. **Matchstat** — content-led, blog-style, readable. Not flashy but feels current.
3. **WinnerOdds** — utilitarian but professional. Trust-first design.
4. **Tennis Abstract** — ugly but the navigation is honest and fast. "Anti-design" works for its audience.
5. **TennisBrain** — product story is good but the visuals undermine it.
6. **Tennis Explorer** — biggest audience, most dated UX. Reviews call it "overloaded and complex" with broken search.

## Feature gaps RTT can fill

Ranked roughly by impact-to-effort (high to low):

1. Public predictions tracker / verified P&L *(phase 2.1)*
2. Player comparison tool *(phase 3.1)*
3. Set-score probability distribution *(phase 3.2)*
4. Multi-bookmaker odds comparison *(phase 3.3)*
5. Power Rankings / leaderboards *(phase 3.6)*
6. Watchlist / favourite players *(phase 3.4)*
7. Serve-zone / shot placement visualisation *(phase 3.5)*
8. AI chat / "ask the model" *(phase 3.7)*
9. Tournament-level forecast bracket *(phase 3.8)*
10. Mobile app or PWA *(phase 3.9)*

## The wedge

None of the existing sites combine all four of:

- A modern, branded, designed UX
- A transparent published model record
- A clear "is there value here?" headline answer on every match
- Plain-English reasoning, not just numbers

If RTT delivers all four, we're visibly best-in-class on UX *and* most explainable model in one product. That's a strong wedge — but only after phase 1 is solved, because none of it survives a sub-50% win rate.

---

## Sources for the competitive research

- [TennisBrain](https://www.tennisbrain.com/)
- [TennisViz](https://tennisviz.com/)
- [Tennis Explorer](https://www.tennisexplorer.com/)
- [WinnerOdds](https://winnerodds.com/tennis/)
- [Matchstat](https://matchstat.com/)
- [Tennis Abstract](https://www.tennisabstract.com/)
- [Ultimate Tennis Statistics](https://www.ultimatetennisstatistics.com/)
- [Predixsport](https://www.predixsport.com/tennis_predictions)
- [SportBot AI](https://www.sportbotai.com/tennis)
- [WinnerOdds review (Smart Sports Trader)](https://smartsportstrader.com/winnerodds-review/)
- [Tennis Explorer review (vp-bet)](https://vp-bet.com/ng/wiki/reviews-of-betting-services/tennis-explorer-statistical-service-review)
- [Similarweb — Tennis Explorer](https://www.similarweb.com/website/tennisexplorer.com/)
- [Similarweb — Matchstat](https://www.similarweb.com/website/matchstat.com/)
