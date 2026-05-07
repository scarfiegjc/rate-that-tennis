"""
ratethat.tennis — Bookmaker affiliate configuration
====================================================
Maps each bookmaker (key returned by The Odds API) to:
  - display_name      : human-readable name shown to users
  - affiliate_enabled : True only when we have a confirmed tracking URL
  - affiliate_url     : tracking URL with {match_url} placeholder if relevant
  - sportsbook_url    : fallback URL (used when affiliate_enabled=False)
  - notes             : internal notes (not shown to users)

Until an affiliate application is approved, set affiliate_enabled=False and the
frontend will display the odds for comparison but suppress the "Bet Now" CTA.

When applications come through, swap in the real tracking URL and flip
affiliate_enabled=True. No code changes needed elsewhere.
"""
from __future__ import annotations
from typing import Optional

# ─── The Odds API bookmaker keys ─────────────────────────────────────────────
# See: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
# Keys are stable lowercase strings (e.g. "leovegas", "bet365").

BOOKMAKERS: dict[str, dict] = {
    # ── Primary affiliate targets (apply for these — see docs/affiliate-applications.md)
    "leovegas": {
        "display_name":      "LeoVegas",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.leovegas.com/en/sport/tennis",
        "notes":             "No negative carryover. 40% revshare. Top affiliate pick.",
    },
    "unibet": {
        "display_name":      "Unibet",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.unibet.co.uk/betting/sports/filter/tennis",
        "notes":             "Strong EU footprint. Up to 40% lifetime revshare.",
    },
    "unibet_us": {
        "display_name":      "Unibet (US)",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://nj.unibet.com/sports/#filter/tennis",
        "notes":             "US-region variant served by The Odds API.",
    },
    "888sport": {
        "display_name":      "888sport",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.888sport.com/tennis/",
        "notes":             "35% revshare. Sport-led brand.",
    },
    "betvictor": {
        "display_name":      "BetVictor",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.betvictor.com/en-gb/sports/tennis",
        "notes":             "Backup option. 30%+ revshare, hybrid deals available.",
    },
    "betway": {
        "display_name":      "Betway",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sports.betway.com/en/sports/cat/tennis",
        "notes":             "Backup option. Up to 40% revshare.",
    },

    # ── Comparison only (no affiliate — shown for price reference)
    "pinnacle": {
        "display_name":      "Pinnacle",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.pinnacle.com/en/tennis",
        "notes":             "Sharpest lines, useful for comparison. Affiliate currently closed.",
    },
    "bet365": {
        "display_name":      "Bet365",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.bet365.com/#/AC/B91/C1/D8/E150/F2/",
        "notes":             "Negative carryover bundles casino+sport — not ideal for sharp traffic. Comparison only for now.",
    },
    "williamhill": {
        "display_name":      "William Hill",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sports.williamhill.com/betting/en-gb/tennis",
        "notes":             "Comparison only.",
    },
    "marathonbet": {
        "display_name":      "Marathonbet",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.marathonbet.com/en/popular/Tennis",
        "notes":             "Comparison only.",
    },
    "betfair": {
        "display_name":      "Betfair",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.betfair.com/sport/tennis",
        "notes":             "Exited UK/IE affiliate market July 2025. Comparison only.",
    },
    "ladbrokes": {
        "display_name":      "Ladbrokes",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sports.ladbrokes.com/sport/tennis",
        "notes":             "Comparison only.",
    },
    "coral": {
        "display_name":      "Coral",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sports.coral.co.uk/sport/tennis",
        "notes":             "Comparison only.",
    },
    "skybet": {
        "display_name":      "Sky Bet",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.skybet.com/tennis",
        "notes":             "Comparison only.",
    },
    "boylesports": {
        "display_name":      "BoyleSports",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.boylesports.com/sportsbook/tennis",
        "notes":             "Comparison only.",
    },
    "paddypower": {
        "display_name":      "Paddy Power",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.paddypower.com/tennis",
        "notes":             "Comparison only.",
    },
    "matchbook": {
        "display_name":      "Matchbook",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.matchbook.com/exchange/sports/tennis",
        "notes":             "Exchange — comparison only.",
    },
    "smarkets": {
        "display_name":      "Smarkets",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://smarkets.com/listing/sport/tennis",
        "notes":             "Exchange — comparison only.",
    },

    # ── US sportsbooks (Phase 2 — state-by-state vendor registration required)
    "draftkings": {
        "display_name":      "DraftKings",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sportsbook.draftkings.com/leagues/tennis",
        "notes":             "US Phase 2. CPA $100-$300.",
    },
    "fanduel": {
        "display_name":      "FanDuel",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sportsbook.fanduel.com/navigation/tennis",
        "notes":             "US Phase 2. CPA $25-$500.",
    },
    "betmgm": {
        "display_name":      "BetMGM",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sports.betmgm.com/en/sports/tennis-5",
        "notes":             "US Phase 2.",
    },
    "caesars": {
        "display_name":      "Caesars",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.caesars.com/sportsbook-and-casino/sports/tennis",
        "notes":             "US Phase 2. CPA $100-$400 + revshare.",
    },
    "bovada": {
        "display_name":      "Bovada",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.bovada.lv/sports/tennis",
        "notes":             "Comparison only.",
    },
    "betrivers": {
        "display_name":      "BetRivers",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.betrivers.com/online-sports-betting/tennis",
        "notes":             "Comparison only.",
    },
    "pointsbetus": {
        "display_name":      "PointsBet (US)",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://nj.pointsbet.com/sports/tennis",
        "notes":             "Comparison only.",
    },
    "wynnbet": {
        "display_name":      "WynnBET",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://wynnbet.com/sports/",
        "notes":             "Comparison only.",
    },
    "twinspires": {
        "display_name":      "TwinSpires",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.twinspires.com/sports/tennis",
        "notes":             "Comparison only.",
    },
    "barstool": {
        "display_name":      "Barstool",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.barstoolsportsbook.com/sports/tennis",
        "notes":             "Comparison only.",
    },
    "superbook": {
        "display_name":      "SuperBook",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://co.superbook.com/sports/tennis",
        "notes":             "Comparison only.",
    },
    "lowvig": {
        "display_name":      "LowVig",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.lowvig.ag/sports/tennis",
        "notes":             "Comparison only.",
    },
    "betonlineag": {
        "display_name":      "BetOnline",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.betonline.ag/sportsbook/tennis",
        "notes":             "Comparison only.",
    },
    "mybookieag": {
        "display_name":      "MyBookie",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://mybookie.ag/sportsbook/tennis/",
        "notes":             "Comparison only.",
    },
    "intertops": {
        "display_name":      "Intertops",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://sports.intertops.eu/en/sports/tennis",
        "notes":             "Comparison only.",
    },
    "gtbets": {
        "display_name":      "GTbets",
        "affiliate_enabled": False,
        "affiliate_url":     None,
        "sportsbook_url":    "https://www.gtbets.eu/sports/tennis",
        "notes":             "Comparison only.",
    },
}


def get_bookmaker(key: str) -> Optional[dict]:
    """Return the affiliate config dict for a bookmaker key, or None."""
    return BOOKMAKERS.get((key or "").lower().strip())


def display_name(key: str) -> str:
    """Pretty bookmaker name, fallback to a title-cased key."""
    cfg = get_bookmaker(key)
    if cfg:
        return cfg["display_name"]
    return (key or "").replace("_", " ").title()


def click_url(key: str) -> Optional[str]:
    """
    Return the URL to send a user to when they click "Bet Now".
    - If an affiliate deal is live, returns the tracking URL.
    - Otherwise returns the public sportsbook URL (still useful for value
      bettors who want to verify the price).
    Returns None if the bookmaker is unknown.
    """
    cfg = get_bookmaker(key)
    if not cfg:
        return None
    if cfg.get("affiliate_enabled") and cfg.get("affiliate_url"):
        return cfg["affiliate_url"]
    return cfg.get("sportsbook_url")


def is_affiliate(key: str) -> bool:
    """True only when we have a real tracking URL set up for this bookmaker."""
    cfg = get_bookmaker(key)
    return bool(cfg and cfg.get("affiliate_enabled") and cfg.get("affiliate_url"))


def all_bookmakers() -> dict[str, dict]:
    """Full config dict, keyed by bookmaker key."""
    return BOOKMAKERS
