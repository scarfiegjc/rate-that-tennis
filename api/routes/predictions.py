"""
ratethat.tennis API — Predictions tracker + systems routes.

GET /predictions/today
GET /predictions/history?date=YYYY-MM-DD&limit=…
GET /predictions/stats
GET /systems
GET /systems/{code}/picks?status=open|settled
GET /systems/{code}/stats
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.db import query, query_one


router = APIRouter(tags=["predictions"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_prediction_row(r: dict) -> dict:
    """Normalise a row from v_predictions_with_results for frontend use."""
    p1_prob = float(r["prob_first_player"]) if r.get("prob_first_player") is not None else None
    p2_prob = float(r["prob_second_player"]) if r.get("prob_second_player") is not None else None
    return {
        "match_id": r["match_id"],
        "event_date": str(r["event_date"]) if r.get("event_date") else None,
        "event_time": str(r["event_time"]) if r.get("event_time") else None,
        "event_status": r.get("event_status"),
        "tournament": r.get("tournament_name"),
        "surface": r.get("surface_name"),
        "round": r.get("tournament_round"),
        "p1": {
            "id": r.get("p1_id"),
            "name": r.get("p1_name"),
            "country_code": r.get("p1_country"),
            "prob": p1_prob,
        },
        "p2": {
            "id": r.get("p2_id"),
            "name": r.get("p2_name"),
            "country_code": r.get("p2_country"),
            "prob": p2_prob,
        },
        "confidence": r.get("confidence"),
        "predicted_winner": r.get("predicted_winner"),
        "actual_winner": r.get("actual_winner"),
        "is_correct": r.get("is_correct"),
        "settled_at": str(r["settled_at"]) if r.get("settled_at") else None,
        "predicted_at": str(r["predicted_at"]) if r.get("predicted_at") else None,
        "predictor_version": r.get("predictor_version"),
        "rtt_gap": float(r["rtt_gap"]) if r.get("rtt_gap") is not None else None,
        "surface_gap": float(r["surface_gap"]) if r.get("surface_gap") is not None else None,
        "form_gap": float(r["form_gap"]) if r.get("form_gap") is not None else None,
        "total_logit": float(r["total_logit"]) if r.get("total_logit") is not None else None,
        "key_factors": r.get("key_factors"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /predictions/today
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/today")
def predictions_today(
    days_ahead: int = Query(default=2, ge=0, le=7),
    include_settled: bool = Query(default=True),
):
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    rows = query(
        """
        SELECT *
        FROM v_predictions_with_results
        WHERE event_date BETWEEN %s AND %s
        ORDER BY event_date, event_time NULLS LAST, match_id
        """,
        (today, cutoff),
    )

    items = [_serialise_prediction_row(r) for r in rows]
    if not include_settled:
        items = [i for i in items if i["actual_winner"] is None]

    settled_count   = sum(1 for i in items if i["is_correct"] is not None)
    correct_count   = sum(1 for i in items if i["is_correct"])
    accuracy_pct    = round(100.0 * correct_count / settled_count, 1) if settled_count else None

    return {
        "date": str(today),
        "date_to": str(cutoff),
        "predictions": items,
        "summary": {
            "total":     len(items),
            "settled":   settled_count,
            "correct":   correct_count,
            "accuracy_pct": accuracy_pct,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /predictions/history
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/history")
def predictions_history(
    target_date: Optional[str] = Query(default=None, alias="date",
                                       description="Single date — YYYY-MM-DD"),
    days: int = Query(default=14, ge=1, le=90,
                      description="If date omitted, the last N days"),
):
    """Per-day rollup with all predictions for a given date or window."""
    if target_date:
        rows = query(
            """
            SELECT *
            FROM v_predictions_with_results
            WHERE event_date = %s
              AND settled_at IS NOT NULL
            ORDER BY event_time NULLS LAST, match_id
            """,
            (target_date,),
        )
        return {
            "date": target_date,
            "predictions": [_serialise_prediction_row(r) for r in rows],
        }

    today = date.today()
    earliest = today - timedelta(days=days)

    daily = query(
        """
        SELECT event_date, predictions, settled, correct, incorrect, accuracy_pct,
               high_conf, high_conf_correct, high_conf_accuracy_pct
        FROM v_predictions_daily
        WHERE event_date BETWEEN %s AND %s
        ORDER BY event_date DESC
        """,
        (earliest, today),
    )

    return {
        "from": str(earliest),
        "to": str(today),
        "days": [
            {
                "date": str(d["event_date"]),
                "predictions": d["predictions"],
                "settled": d["settled"],
                "correct": d["correct"],
                "incorrect": d["incorrect"],
                "accuracy_pct": float(d["accuracy_pct"]) if d.get("accuracy_pct") is not None else None,
                "high_conf": d["high_conf"],
                "high_conf_correct": d["high_conf_correct"],
                "high_conf_accuracy_pct": float(d["high_conf_accuracy_pct"]) if d.get("high_conf_accuracy_pct") is not None else None,
            }
            for d in daily
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /predictions/stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/predictions/stats")
def predictions_stats():
    """Overall and segmented accuracy."""
    overall = query_one(
        """
        SELECT
            COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions
        """,
    ) or {}

    by_confidence = query(
        """
        SELECT
            confidence,
            COUNT(*) FILTER (WHERE settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions
        WHERE confidence IS NOT NULL
        GROUP BY confidence
        ORDER BY CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
        """
    )

    by_surface = query(
        """
        SELECT
            s.name AS surface,
            COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL) AS settled,
            COUNT(*) FILTER (WHERE mp.is_correct)             AS correct,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE mp.is_correct)
                      / NULLIF(COUNT(*) FILTER (WHERE mp.settled_at IS NOT NULL), 0), 2
            ) AS accuracy_pct
        FROM model_predictions mp
        JOIN matches m ON m.id = mp.match_id
        JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s ON s.id = t.surface_id
        WHERE s.name IS NOT NULL
        GROUP BY s.name
        ORDER BY settled DESC
        """
    )

    return {
        "overall": {
            "settled": overall.get("settled") or 0,
            "correct": overall.get("correct") or 0,
            "accuracy_pct": float(overall["accuracy_pct"]) if overall.get("accuracy_pct") is not None else None,
        },
        "by_confidence": [
            {
                "confidence": r["confidence"],
                "settled": r["settled"],
                "correct": r["correct"],
                "accuracy_pct": float(r["accuracy_pct"]) if r.get("accuracy_pct") is not None else None,
            }
            for r in by_confidence
        ],
        "by_surface": [
            {
                "surface": r["surface"],
                "settled": r["settled"],
                "correct": r["correct"],
                "accuracy_pct": float(r["accuracy_pct"]) if r.get("accuracy_pct") is not None else None,
            }
            for r in by_surface
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems")
def list_systems():
    rows = query(
        """
        SELECT system_id AS id, code, name, description, icon, accent_colour,
               picks_total, picks_settled, picks_correct, accuracy_pct,
               profit_units, roi_pct
        FROM v_systems_stats
        ORDER BY picks_total DESC NULLS LAST, name
        """
    )
    return {
        "systems": [
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "description": r["description"],
                "icon": r["icon"],
                "accent_colour": r["accent_colour"],
                "picks_total": r["picks_total"] or 0,
                "picks_settled": r["picks_settled"] or 0,
                "picks_correct": r["picks_correct"] or 0,
                "accuracy_pct": float(r["accuracy_pct"]) if r.get("accuracy_pct") is not None else None,
                "profit_units": float(r["profit_units"]) if r.get("profit_units") is not None else None,
                "roi_pct": float(r["roi_pct"]) if r.get("roi_pct") is not None else None,
            }
            for r in rows
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems/{code}/picks
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems/{code}/picks")
def system_picks(
    code: str,
    status: str = Query(default="all", regex="^(all|open|settled)$"),
    limit: int = Query(default=50, ge=1, le=200),
):
    sys_row = query_one("SELECT id, name, description, icon, accent_colour FROM systems WHERE code = %s", (code,))
    if not sys_row:
        raise HTTPException(status_code=404, detail="System not found")

    where = ""
    if status == "open":
        where = "AND sp.settled_at IS NULL"
    elif status == "settled":
        where = "AND sp.settled_at IS NOT NULL"

    rows = query(
        f"""
        SELECT
            sp.id AS pick_id,
            sp.match_id,
            sp.pick,
            sp.confidence,
            sp.reason,
            sp.rationale,
            sp.pick_prob,
            sp.market_odds,
            sp.is_correct,
            sp.profit_loss,
            sp.settled_at,
            sp.picked_at,
            m.event_date, m.event_time, m.event_status,
            t.name AS tournament_name,
            s.name AS surface_name,
            m.tournament_round,
            p1.id AS p1_id, p1.name AS p1_name, p1.country_code AS p1_country,
            p2.id AS p2_id, p2.name AS p2_name, p2.country_code AS p2_country
        FROM system_picks sp
        JOIN matches m       ON m.id = sp.match_id
        LEFT JOIN tournaments t ON t.id = m.tournament_id
        LEFT JOIN surfaces s    ON s.id = t.surface_id
        LEFT JOIN players p1    ON p1.id = m.first_player_id
        LEFT JOIN players p2    ON p2.id = m.second_player_id
        WHERE sp.system_id = %s
        {where}
        ORDER BY m.event_date DESC, m.event_time NULLS LAST
        LIMIT %s
        """,
        (sys_row["id"], limit),
    )

    return {
        "system": sys_row,
        "picks": [
            {
                "pick_id": r["pick_id"],
                "match_id": r["match_id"],
                "event_date": str(r["event_date"]) if r.get("event_date") else None,
                "event_time": str(r["event_time"]) if r.get("event_time") else None,
                "event_status": r.get("event_status"),
                "tournament": r.get("tournament_name"),
                "surface": r.get("surface_name"),
                "round": r.get("tournament_round"),
                "pick": r["pick"],
                "confidence": r.get("confidence"),
                "reason": r.get("reason"),
                "rationale": r.get("rationale"),
                "pick_prob": float(r["pick_prob"]) if r.get("pick_prob") is not None else None,
                "market_odds": float(r["market_odds"]) if r.get("market_odds") is not None else None,
                "is_correct": r.get("is_correct"),
                "profit_loss": float(r["profit_loss"]) if r.get("profit_loss") is not None else None,
                "settled_at": str(r["settled_at"]) if r.get("settled_at") else None,
                "picked_at": str(r["picked_at"]) if r.get("picked_at") else None,
                "p1": {"id": r["p1_id"], "name": r["p1_name"], "country_code": r["p1_country"]},
                "p2": {"id": r["p2_id"], "name": r["p2_name"], "country_code": r["p2_country"]},
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /systems/{code}/stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/systems/{code}/stats")
def system_stats(code: str):
    row = query_one(
        """
        SELECT system_id AS id, code, name, description, icon, accent_colour,
               picks_total, picks_settled, picks_correct, accuracy_pct,
               profit_units, roi_pct
        FROM v_systems_stats
        WHERE code = %s
        """,
        (code,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="System not found")
    # Trend: last 30 days
    trend = query(
        """
        SELECT date_trunc('day', m.event_date)::date AS day,
               COUNT(*) FILTER (WHERE sp.settled_at IS NOT NULL) AS settled,
               COUNT(*) FILTER (WHERE sp.is_correct)             AS correct,
               SUM(sp.profit_loss) AS profit
        FROM system_picks sp
        JOIN systems sy ON sy.id = sp.system_id
        JOIN matches m  ON m.id = sp.match_id
        WHERE sy.code = %s
          AND m.event_date >= CURRENT_DATE - INTERVAL '60 days'
        GROUP BY day
        ORDER BY day
        """,
        (code,),
    )
    return {
        "system": {
            **{k: row[k] for k in ("id", "code", "name", "description", "icon", "accent_colour")},
            "picks_total": row["picks_total"] or 0,
            "picks_settled": row["picks_settled"] or 0,
            "picks_correct": row["picks_correct"] or 0,
            "accuracy_pct": float(row["accuracy_pct"]) if row.get("accuracy_pct") is not None else None,
            "profit_units": float(row["profit_units"]) if row.get("profit_units") is not None else None,
            "roi_pct": float(row["roi_pct"]) if row.get("roi_pct") is not None else None,
        },
        "trend": [
            {
                "day": str(t["day"]),
                "settled": t["settled"] or 0,
                "correct": t["correct"] or 0,
                "profit": float(t["profit"]) if t.get("profit") is not None else None,
            }
            for t in trend
        ],
    }
