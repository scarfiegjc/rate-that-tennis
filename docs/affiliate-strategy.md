# Affiliate Programme Research — ratethat.tennis

> Research compiled May 2026. Focus: bookmaker affiliate programmes that pair with live tennis odds, with a preference for lifetime revenue share (LRS) wherever it still exists.

---

## TL;DR for ratethat.tennis

1. **Lifetime revshare is not dead — but it's narrower than five years ago.** True LRS still exists at bet365 (UK/EU), Pinnacle (global), Unibet, and most of the crypto books (Stake, Sportsbet.io, BC.Game, Cloudbet). What you've lost is the casual "everyone offers it" market — Betfair officially exited UK/IE affiliate marketing in July 2025, and several US books are CPA-only.
2. **The cleanest delivery path is The Odds API widget**, not deals direct with each bookmaker. It's a drop-in HTML tag that pulls live odds from 100+ books and lets you wire your own affiliate links into the click-through. One integration, many bookmakers, and you're not begging each bookmaker individually for a feed.
3. **Your edge audience is sharps and value-seekers** (that's the whole RTT pitch). The right primary partner for them is Pinnacle — best lines, no limits on winning players, 30–35% lifetime revshare. The right secondary partners are crypto books (Stake/Sportsbet.io) for international users and DraftKings/FanDuel CPA for US users.
4. **Beware the UK trap.** UKGC tightened affiliate rules in January 2026 (mixed-product incentive ban, 10x wagering caps, stricter disclosure). Operators are now liable for affiliate breaches, so they're picky about who they take on. You'll need a UKGC-aware compliance baseline before applying.

---

## Reality check on lifetime revshare in 2026

| Programme | Still LRS? | Key catch |
|---|---|---|
| **bet365 Partners** | Yes — 30–35% for life | Negative carryover **across all brands** (casino losses can offset sport gains for months) |
| **Pinnacle Affiliates** | Yes — 30–35% for life | Tier drops to 0% if you bring fewer than 5 new depositors in a 3-month window |
| **Unibet (Kindred Affiliates)** | Yes — up to 40% lifetime | Tiered, based on monthly NRC |
| **Stake.com** | Yes — default 10%, custom up to ~45% | Lifetime as long as the player is active; commission tied to house edge (3% on sport) |
| **Sportsbet.io / Bitcasino.io (Partners.io)** | Yes — up to 45% | Some directories report session-based tracking — verify in T&Cs |
| **BC.Game** | Yes — 25% default, 35–50% negotiable | **No negative carryover** (rare and excellent) |
| **Cloudbet** | Yes — 25% default | Carries negative balances forward indefinitely |
| **Betway** | Up to 40%, "lifetime" advertised | Negative carryover applies |
| **LeoVegas** | Up to 40% | **No negative carryover** (rare for a UK-licensed operator) |
| **BetVictor** | 30%+ negotiable | Hybrid deals available |
| **888sport** | Up to 35% | RevShare/CPA/Hybrid options |
| **DraftKings (US)** | No — CPA $100–$300 sport | Some legacy revshare deals exist for big affiliates only |
| **FanDuel (US)** | Hybrid available | CPA $25–$500 + 35% revshare on top tier |
| **Caesars (US)** | Yes — 20–40% | CPA $100–$400 alongside |
| **BetMGM (US)** | Hybrid available | Apply at BetMGMPartners.com |
| **Betfair Partnerships** | Closed for UK/IE since July 2025 | Still active in regulated EU markets at 25–35% |

**The "negative carryover" issue**, in plain English: if your referred players have a winning month against the bookmaker, you owe the bookmaker that month, and any positive months that follow are eaten until you've cleared the deficit. This matters a *lot* for a value-betting audience like ratethat.tennis — your users are exactly the customers most likely to win, which makes carryover bookmakers a poor fit. **Pick programmes with no negative carryover** (LeoVegas, BC.Game) or programmes that don't care about player win rate (Pinnacle — they don't limit winners). Avoid bet365 and Cloudbet for sharp-leaning traffic.

---

## Recommended approach for ratethat.tennis

A three-tier setup that hedges across markets and deal types:

### Tier 1 — Headline partner: Pinnacle

Pinnacle is the natural home for RTT's audience. They're known for the sharpest lines, accept big stakes, and famously don't restrict winning players. Their affiliate programme pays 30% in months 0–3 then up to 35% based on new depositor volume — and importantly, Pinnacle's traders price tighter than soft books, so even though your edge bettors win more, the bookmaker still makes margin via volume. That makes the LRS sustainable on both sides.

**Apply:** pinnacle.com/affiliates — direct programme, run on their own platform.

**Caveat:** Pinnacle is restricted in the UK (no UKGC licence). UK-located users will see a country block. Use Pinnacle for international/EU traffic and pair it with a UKGC-licensed partner for UK users.

### Tier 2 — UK fallback: a UKGC-licensed bookmaker with no negative carryover

For UK users, the right pairing depends on your appetite for compliance work:
- **LeoVegas** — 40% revshare, no negative carryover, active in UK. Good fit if your audience accepts a casino-led brand.
- **BetVictor** — 30%+ revshare, willing to negotiate hybrid deals, established UK tennis market presence.
- **888sport** — 35% revshare available, sportsbook-led brand, broader product suite.

Avoid bet365 for UK affiliate traffic despite its market share — the bundled negative carryover across casino + sport will hurt you when sharp tennis bettors win.

### Tier 3 — Crypto / international: Stake + Sportsbet.io

For users outside UK/EU/US (or anyone who prefers crypto), crypto books offer the most generous deals and the fewest compliance hoops:
- **Stake.com** — lifetime 10% default, custom up to ~45% if you can negotiate. Largest crypto sportsbook by far, deep tennis markets.
- **Sportsbet.io** — up to 45% revshare advertised, tennis live streaming, no quotas mentioned.
- **BC.Game** — only one with explicit no-negative-carryover policy, plus negotiable up to 35–50%.

### Tier 4 — US: hybrid CPA where available

For US-located users (state-by-state legality), revshare is rare and CPA dominates:
- **DraftKings** — $100–$300 CPA per qualified depositor, optional revshare for big affiliates.
- **FanDuel** — $25–$500 CPA, 35% revshare on top tier.
- **Caesars** — 20–40% revshare *and* $100–$400 CPA — best dual structure of the US market.
- **BetMGM** — hybrid deals available.

US affiliate marketing is its own legal beast (you typically need to register state-by-state as a vendor to operators in regulated states like NJ, PA, NY). Worth treating as a Phase 2 expansion rather than launch-day priority.

---

## Odds delivery: API/widget options

This is the part that often kills DIY bookmaker integrations. You don't need to negotiate odds feeds individually. Use a wholesale provider:

### The Odds API (recommended for launch)
- **Site:** the-odds-api.com
- **Tennis coverage:** ATP, WTA, Grand Slams, Challengers (live + pre-match)
- **Bookmakers:** 100+ globally
- **Affiliate integration:** built-in. Drop in their HTML widget, paste your bookmaker affiliate links into your subscription dashboard, and clicks are attributed automatically.
- **Pricing:** free tier for small sites, then usage-based. Each widget impression = 1 visit from your quota.
- **Why it's the right pick:** zero engineering for a fully-featured live odds widget on every match page. Your existing FastAPI / React stack stays clean; the widget is independent.

### odds-api.io (alternative, more bookmakers)
- **Bookmakers:** 265+ — wider coverage including some bzzoiro-style sources
- **Free tier:** 100 requests/hour, all sports including tennis
- **WebSocket feed:** live in-play tennis odds pushed in real time (no polling needed)
- **Affiliate model:** less integrated than The Odds API — you'd build the UI yourself and route clicks through your own affiliate links
- **Use case:** if you want to render odds *yourself* using your existing component library and brand, rather than embed a third-party widget.

### SportsGameOdds
- **Pricing:** $99/month minimum (Rookie tier) — paid only, no real free tier
- **Affiliate programme:** offers a 20% recurring commission for *referring other developers* to their API (i.e. you can earn from devs you send their way, in addition to whatever you do with the odds themselves)
- **Tennis included** in all tiers

### OpticOdds
- **Pricing:** sales-led, no published rates. 200+ sportsbooks.
- **Use case:** enterprise-grade. Probably overkill until ratethat.tennis is doing meaningful traffic.

**My recommendation for ratethat.tennis:** Start with The Odds API widget on match pages (cheapest, fastest) and keep odds-api.io in your back pocket for when you want a fully custom-rendered odds component that matches your dark theme.

---

## UK regulatory must-knows (UKGC)

Since January 2026 the UKGC tightened the rules in ways that affect affiliates directly. The key ones that apply to ratethat.tennis:

- **Mixed-product incentives are banned** — e.g. you can't promote "deposit on sport, get casino free spins". This affects what creatives you can run.
- **Wagering requirements on bonus funds capped at 10x** — terms must be displayed prominently.
- **Operators are now jointly liable for affiliate breaches** — meaning operators are picky about who they take on. Good affiliates with clean compliance practices are favoured; programmes are increasingly closed-door.
- **Mandatory age-gating on all gambling content** — affects your homepage and any preview cards that appear in social/search snippets.
- **You must clearly identify commercial relationships** — every affiliate link needs disclosure.
- **No "gambling solves financial problems" framing** — applies to any value/edge messaging. RTT can talk about model edge and expected value, but you can't say "make money betting tennis".

Practical implications for the site:
1. Add a `/responsible-gambling` page linking to GamCare, BeGambleAware, GamStop.
2. Age-gate the homepage if any odds or bookmaker logos appear above the fold (a single "I confirm I am 18+" modal on first visit covers this).
3. Add affiliate disclosure to every page that shows odds or bookmaker links: "ratethat.tennis is supported by affiliate commissions from partner bookmakers. This does not affect our model or ratings."
4. Don't make "easy money" claims anywhere. Talk about model accuracy, edge, and expected value — never "win" or "guaranteed profit".

---

## Tennis-specific opportunity: prediction-aggregator partnerships

Beyond bookmakers, there's a small ecosystem of tennis-data partners that fits your model output naturally:

- **Matchstat** — runs an affiliate programme for their tennis prediction service. Could syndicate your RTT scores in exchange for clicks back, or partner on cross-promotion. They are also a competitor, so structure carefully.
- **Steve G Tennis** — offers a 50% lifetime commission on subscribers referred to their H2H predictions service. Less of a fit (they're a tipster, you're a model), but their commission rate shows what's achievable in tennis-prediction subscriber economics if you ever launch a paid tier.

**Strategic note:** Your strongest long-term monetisation is probably *not* affiliate revenue — it's a paid Pro tier where you charge your serious users £10–£20/month for deeper model output (Kelly stake recommendations, line movement alerts, custom alerts). Affiliate revenue is the floor; subscription is the ceiling. Worth thinking about now even if you don't launch it on day one.

---

## Concrete action plan

In the order I'd actually do them:

1. **Apply to Pinnacle Affiliates** today. They're the natural primary partner for your audience. Approval is usually within a week. (`pinnacle.com/affiliates`)
2. **Sign up for The Odds API** and prototype a widget on a single match detail page. Free tier is enough to validate. (`the-odds-api.com`)
3. **Apply to LeoVegas + BetVictor** for UK coverage. LeoVegas first (no negative carryover is a real edge for sharp traffic).
4. **Apply to Stake + Sportsbet.io** for international/crypto coverage.
5. **Set up UKGC-compliant disclosures** before going live with any bookmaker links: age gate, responsible gambling page, affiliate disclosure footer.
6. **Defer US partnerships** until you have a meaningful US user base — the per-state registration overhead isn't worth it on day one.
7. **Track everything via UTM**. Even when bookmakers give you native tracking, layer your own UTM tags so you have a single source of truth on which programmes convert.
8. **Phase 2: Pro subscription tier**. Once you've got 6 months of model performance data showing real edge, consider launching a paid tier alongside affiliate revenue.

---

## Sources

- [Best Sports Betting Affiliate Programs UK 2026 — The Punters Page](https://www.thepunterspage.com/sports-betting-affiliate-programs/)
- [UK Sportsbook Affiliate Programs: Top 10 Operators Ranked — Post Affiliate Pro](https://www.postaffiliatepro.com/blog/uk-sportsbook-affiliate-programs/)
- [Pinnacle Affiliates Commission Structure](https://www.pinnacle.com/affiliates/commission-structure)
- [Pinnacle Affiliates FAQ](https://www.pinnacle.com/affiliates/faq)
- [Bet365 Partners — StatsDrone Review](https://statsdrone.com/affiliate-programs/bet365-partners/)
- [Bet365 Partners — Affiliate Program Review (FindMyAff)](https://findmyaff.com/affiliate-programs/bet365/)
- [Bet365 Affiliate Program Details — getlasso.co](https://getlasso.co/affiliate/bet365/)
- [LeoVegas Affiliates Review — StatsDrone](https://statsdrone.com/affiliate-programs/leovegas-affiliates/)
- [BetVictor Affiliates Review — StatsDrone](https://statsdrone.com/affiliate-programs/betvictor-affiliates/)
- [Betfair Affiliates — official partnerships site](https://partnerships.betfair.com/)
- [Betfair Affiliates Review — StatsDrone (notes UK exit July 2025)](https://statsdrone.com/affiliate-programs/betfair-affiliates/)
- [Stake.com Affiliate Program — official](https://stake.com/affiliate/overview)
- [Stake Affiliates Review — StatsDrone](https://statsdrone.com/affiliate-programs/stake-affiliates/)
- [Cloudbet Affiliates FAQ](https://www.cloudbet.com/en/affiliates/faq)
- [Cloudbet — negative carryover details (LTC Casino review)](https://www.ltccasino.io/cryptocasino/cloudbet-casino-affiliate-program-review/)
- [BC.Game / Stake / Top Competitors comparison (CryptoDeepIn)](https://cryptodeepin.com/2052.html)
- [DraftKings Affiliate Program — Sportsbook API](https://sportsbookapi.com/affiliate-programs/draftkings/)
- [Caesars Sportsbook & Casino Affiliate Program — Sportsbook API](https://sportsbookapi.com/affiliate-programs/caesars/)
- [Legal US Sportsbook Affiliate Programs — Lineups](https://www.lineups.com/betting/legal-us-sportsbook-affiliate-programs/)
- [Sports Betting Affiliate Marketing 2026 — BettingUSA](https://www.bettingusa.com/affiliate/)
- [Tennis Odds API — The Odds API](https://the-odds-api.com/sports/tennis-odds.html)
- [Odds Widget — The Odds API](https://the-odds-api.com/widget/)
- [Integrating Odds on Your Website — The Odds API guide](https://the-odds-api.com/guide/website-odds-integration.html)
- [How to Monetize Odds Data — The Odds API](https://the-odds-api.com/sports-odds-data/how-to-monetize-odds-data.html)
- [Tennis Odds API — odds-api.io](https://odds-api.io/sports/tennis)
- [odds-api.io free tier](https://odds-api.io/pricing/free)
- [SportsGameOdds Pricing](https://sportsgameodds.com/pricing/)
- [SportsGameOdds Affiliate Program](https://sportsgameodds.com/partner/)
- [OpticOdds Pricing](https://opticodds.com/pricing)
- [UKGC promotion rules 2026 — AffRate](https://affrate.com/guides-playbooks/compliance-rg/ukgc-promo-rules-2026-mixed-product-incentives-affiliates/)
- [UKGC — Affiliates or third parties guidance](https://www.gamblingcommission.gov.uk/licensees-and-businesses/guide/page/affiliates-or-third-parties)
- [Highest Paying Tennis Betting Affiliate Programs — Matchstat](https://matchstat.com/predictions-tips/what-are-the-highest-paying-tennis-betting-affiliate-programs/)
- [Steve G Tennis Predictions Affiliate Program](https://www.stevegtennis.com/h2h-predictions/affiliate-area/)
