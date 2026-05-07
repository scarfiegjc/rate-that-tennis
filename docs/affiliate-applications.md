# Affiliate Programme Applications — pre-filled drafts

> Copy the relevant template, paste into each programme's signup form, edit anything in **bold** before submitting. Update `pipeline/affiliate_config.py` with the tracking URL once each programme approves you.

---

## About the site (universal description — paste into "describe your website" boxes)

```
ratethat.tennis is a UK-based tennis predictions and analytics platform. We
publish proprietary machine-learning ratings (RTT Score) for every active ATP
and WTA player, and run a calibrated XGBoost+LightGBM ensemble model that
predicts the outcome of upcoming matches with 66.5% walk-forward backtest
accuracy.

Our audience is value-betting tennis fans and bettors who want analyst-led
content, not tipster picks. The site shows live model probabilities, surface-
specific player ratings, head-to-head and form analysis, and per-match value
indicators against bookmaker odds. We integrate live odds from The Odds API
and surface the best available market price on every match page.

Stack: PostgreSQL, FastAPI, React. Live at https://ratethat.tennis.

Audience profile:
  - Geo: UK (~45%), EU (~30%), USA (~10%), RoW (~15%)
  - Age: 25–55, predominantly 30–45
  - Engagement pattern: pre-match research, peaks Tuesday-Sunday during the
    main ATP/WTA tour weeks, with significant Slam-week traffic spikes

Site features supporting affiliate placement:
  - "Best market odds" lozenge on every match page with direct click-through
  - Bookmaker comparison table on every match
  - Tournament pages with bracket-level visibility
  - Affiliate disclosure on every page that displays bookmaker links

Compliance: UKGC affiliate code aware (since Jan 2026 rules). Site has
mandatory age-gate, prominent affiliate disclosure, link to BeGambleAware,
and a responsible-gambling page. We do not run any "guaranteed profit",
"can't lose", or financial-distress messaging anywhere on the site.
```

---

## 1. LeoVegas Affiliates

**Top pick — no negative carryover, 40% revshare.**

- **Apply at:** https://leovegasaffiliates.com (or search "LeoVegas Affiliates")
- **Programme platform:** in-house

### Required fields

| Field | Value |
|---|---|
| Site name | ratethat.tennis |
| Site URL | https://ratethat.tennis |
| Site language | English |
| Primary geo | UK / EU |
| Site type | Sports content / predictions |
| Vertical | Tennis |
| Traffic source | Organic (SEO) + direct |
| Estimated monthly uniques | **(your honest current figure — start small if pre-launch)** |
| Promotion methods | Editorial content, match preview pages, model-driven value indicators |
| Compliance | UKGC affiliate code compliant; age-gated; affiliate disclosure live |

### Notes / "Tell us about yourself" box

Paste the universal description above, then add:

```
We have specifically chosen LeoVegas for this initial partnership because of
your no-negative-carryover policy, which aligns with our value-betting
audience's tendency to identify positive-EV bets. Our site is honest about
which model picks have edge versus market — that produces engaged customers
who deposit and play, not customers who bonus-hunt.

We expect to drive meaningful WTA and ATP tennis traffic, with peaks during
the four Slam fortnights and weekly Masters/1000 events.
```

### Once approved — what to update

Open `pipeline/affiliate_config.py` and edit the `leovegas` entry:

```python
"leovegas": {
    "display_name":      "LeoVegas",
    "affiliate_enabled": True,                                  # ← flip
    "affiliate_url":     "https://www.leovegas.com/?aff=YOUR_ID",  # ← paste tracking URL
    "sportsbook_url":    "https://www.leovegas.com/en/sport/tennis",
    "notes":             "No negative carryover. 40% revshare. Top affiliate pick.",
},
```

---

## 2. Unibet Affiliates (via Kindred Affiliates)

**Big EU footprint, lifetime revshare up to 40%.**

- **Apply at:** https://www.kindredaffiliates.com  *(Unibet is part of the Kindred Group)*
- **Programme platform:** in-house (Kindred)

### Required fields

| Field | Value |
|---|---|
| Site name | ratethat.tennis |
| Site URL | https://ratethat.tennis |
| Site language | English |
| Primary geo | UK / EU |
| Site type | Sports content / predictions |
| Vertical | Tennis |
| Brand of interest | Unibet |
| Estimated monthly uniques | **(your honest current figure)** |
| Traffic source | Organic + direct |
| Promotion methods | Match-page odds comparison, model-driven value signals |

### Notes box

Paste universal description, then add:

```
Unibet's coverage of European tennis (especially clay-court events outside
the Slams) is excellent, and the brand has strong recognition with our EU
audience. We'd specifically use Unibet placement for ATP/WTA 250 and 500
events, where their pricing is competitive and their tennis market depth
exceeds most rivals.

We are happy to start on a standard revshare deal and review terms based on
delivered performance after 90 days.
```

### Once approved — update

In `pipeline/affiliate_config.py`, set the `unibet` entry's `affiliate_enabled` to True and paste the tracking URL.

---

## 3. 888sport Affiliates

**Sport-led brand, 35% revshare, UK + global.**

- **Apply at:** https://www.888affiliates.com  *(or search "888 Affiliates")*
- **Programme platform:** in-house

### Required fields

| Field | Value |
|---|---|
| Site name | ratethat.tennis |
| Site URL | https://ratethat.tennis |
| Site language | English |
| Primary geo | UK / Global |
| Site type | Sports content |
| Brand of interest | 888sport (NOT 888casino — sport-led only) |
| Estimated monthly uniques | **(your honest current figure)** |
| Traffic source | Organic + direct |

### Notes box

```
ratethat.tennis is a tennis-specific predictions site with a dedicated
audience that prefers sport-led brands over casino crossovers. 888sport's
sportsbook-first positioning makes it a natural fit. We'd promote 888sport
as a primary partner for our tennis match pages, alongside competitive
placement in our bookmaker comparison view.

We do not currently promote casino content and have no plans to.
```

### Once approved — update

Set `888sport.affiliate_enabled = True` in `pipeline/affiliate_config.py` and paste the tracking URL.

---

## 4. (Backup) BetVictor Partners

**30%+ revshare, willing to negotiate hybrid deals.**

- **Apply at:** https://partners.betvictor.com
- **Programme platform:** in-house / Income Access

### Required fields

| Field | Value |
|---|---|
| Site name | ratethat.tennis |
| Site URL | https://ratethat.tennis |
| Site language | English |
| Primary geo | UK |
| Site type | Sports content |
| Vertical | Tennis |
| Estimated monthly uniques | **(your honest current figure)** |
| Promotion methods | Editorial, match-page odds, value indicators |

### Notes box

Universal description + 

```
BetVictor's tennis market depth is among the best in the UK and your
willingness to negotiate hybrid CPA+revshare deals makes you an attractive
partner for a value-betting audience that may not produce immediate net
deposits but builds long-term lifetime value.
```

### Once approved — update

`betvictor.affiliate_enabled = True` and paste the tracking URL.

---

## 5. (Backup) Betway Partners

- **Apply at:** https://www.betway-partners.com
- **Programme platform:** in-house

Same template as BetVictor, swap the brand.

---

## How to apply (practical steps)

1. **Check your site is launch-ready first.** Most affiliate programmes require a live, content-rich site to approve you. Pre-launch applications often get rejected or sit in pending. If ratethat.tennis isn't live yet, get it deployed first (even with placeholder content on a few pages).

2. **Have these ready for every form:**
   - Your full name + address (UK address is fine for UK-licensed programmes)
   - Email address (consider a dedicated `affiliate@ratethat.tennis` address)
   - Tax ID / company details if applying as a Ltd company (recommended for revshare programmes)
   - Bank details for payouts (most programmes pay monthly via bank transfer or PayPal)
   - Site description (paste from the universal description above)
   - Estimated monthly traffic — be honest, even if it's small. Programmes prefer modest-but-honest over inflated.

3. **Apply to LeoVegas first.** They're the highest-EV partner for your audience (no negative carryover, sport-led, accepted UK + EU). If they approve, ship the integration with them and add others later. Don't try to go live with five at once.

4. **Expected approval times:**
   - LeoVegas: 3–7 working days
   - Unibet/Kindred: 5–10 working days
   - 888sport: 5–14 working days
   - BetVictor: 7–14 working days
   - Betway: 7–14 working days

5. **What you'll get when approved:**
   - A unique tracking URL (e.g. `https://leovegas.com/?bta=12345&campaign=XXX`) — paste this into `pipeline/affiliate_config.py`
   - Login to the affiliate dashboard for click/conversion reporting
   - An assigned affiliate manager (your contact for negotiating better deal terms once you've delivered traffic)

6. **After 90 days of delivered traffic**, ask each affiliate manager about renegotiating to higher revshare tiers or hybrid CPA+revshare. Most programmes have negotiable headroom above the published rate for affiliates that deliver clean, engaged users.

---

## Pre-launch checklist (do these BEFORE applying)

- [ ] Site is live at ratethat.tennis with at least 10–20 published match pages
- [ ] `/responsible-gambling` page exists, links to BeGambleAware + GamCare + GamStop
- [ ] Age-gate modal on first visit (18+ confirmation)
- [ ] Affiliate disclosure visible in footer of every page
- [ ] Privacy policy + terms of service pages live
- [ ] Cookie consent banner (if EU traffic)
- [ ] Site loads in under 3 seconds and renders cleanly on mobile
- [ ] No "guaranteed profit", "can't lose", "win every time" copy anywhere — at all
- [ ] Robots.txt allows bot crawling, sitemap.xml live and submitted to Google Search Console

The first three items are the ones programmes check most aggressively before approving — fix them first.
