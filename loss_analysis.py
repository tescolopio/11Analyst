"""Evidence-backed, equally weighted point-loss priorities."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable

import serve_reception
import shot_catalogue


MIN_LOSSES = 5
MIN_MATCHES = 2
RETURN_CATEGORIES = frozenset(("shot-landing", "rally-reception", "serve-reception", "return-unspecified"))
PATTERNS = {
    "shot-landing": {
        "focus": "Land your shots reliably",
        "interpretation": "The logged outcome is failure to hit the far side. This does not distinguish "
                          "an unforced error from a difficult incoming ball, nor identify forehand/backhand.",
        "practice": "Start with the repeatable-contact feed. Count legal far-side returns separately from target-zone hits. "
                    "After a stable baseline, add controlled placement variation without increasing speed.",
        "recipe_ids": ["repeatable-contact", "controlled-variation"],
    },
    "rally-reception": {
        "focus": "Return more incoming rally balls",
        "interpretation": "The opponent's final observed hit was a rally shot and the logged outcome says no return after the bounce. "
                          "This does not establish whether timing, reach, positioning, or tracking was responsible.",
        "practice": "Calibrate two manageable feed locations and allow comfortable recovery time. Count returns for each location "
                    "before adding variation. Treat movement as a practice variable, not a diagnosed fault.",
        "recipe_ids": ["two-location-recovery"],
    },
    "serve-legality": {
        "focus": "Reduce point-losing serve faults",
        "interpretation": "These faults accompany actual lost score points. They are not a count of all failed serve attempts "
                          "and do not establish the probability of a fault per serve.",
        "practice": "Use the game's serve-practice mode, not the forehand-drive machine preset. Choose one familiar serve, "
                    "record whether both required bounces are legal, and establish consistency before adding spin or speed.",
        "recipe_ids": ["serve-legality"],
    },
    "serve-reception": {
        "focus": "Put more opponent serves back on the table",
        "interpretation": "The opponent's final observed hit was a serve and the logged outcome says no return after the bounce. "
                          "The evidence does not identify a particular spin family.",
        "practice": "Select one familiar serve template manually, begin with limited variation, and measure legal returns. "
                    "Then vary one placement or spin control at a time. Do not use the supplied rally feed as a serve simulator.",
        "recipe_ids": ["serve-reception"],
    },
    "return-unspecified": {
        "focus": "Improve return consistency; verify the incoming-shot context",
        "interpretation": "A missed return is logged, but the final hit cannot reliably distinguish serve from rally.",
        "practice": "Review the linked point examples and collect complete contact telemetry before choosing a serve-specific drill. "
                    "Use a predictable return feed only as a general baseline.",
        "recipe_ids": ["repeatable-contact"],
    },
    "contact-rules": {
        "focus": "Review contact-order and multiple-hit losses",
        "interpretation": "The log records a contact-rule loss; it does not establish a recurring technique defect.",
        "practice": "Review the recorded examples and reproduce the rule situation at a comfortable pace in manual practice.",
        "recipe_ids": [],
    },
    "unclassified": {
        "focus": "Unclassified point losses",
        "interpretation": "The score confirms a lost point, but the logged reason is absent or unsupported.",
        "practice": "Collect or inspect the missing evidence rather than prescribe a specific technical correction.",
        "recipe_ids": [],
    },
}


def opponent_band(gap: int) -> str:
    return "higher" if gap > 100 else "lower" if gap < -100 else "similar"


def classify(point: dict[str, Any], player_id: str, opponent_id: str) -> dict[str, Any]:
    reason = point["raw_reason"]
    telemetry = point.get("telemetry", {})
    bounded = telemetry.get("status") in ("bounded", "bounded_multiple_attempts")
    events = [
        event for event in telemetry.get("events", [])
        if event["attempt"] == telemetry.get("attempts")
    ] if bounded else []
    hits = [event for event in events if event["kind"] == "hit"]
    last = hits[-1] if hits else None
    expected_actor = None
    if reason == "SenderLoss_DidNotHitFarSide":
        category = "shot-landing"
        expected_actor = player_id
    elif reason in ("ServiceFault_DidNotHitFarSide", "ServiceFault_DidNotHitNearSide"):
        category = "serve-legality"
        expected_actor = player_id
    elif reason == "ReceiverLoss_DidNotHitBallAfterBounce":
        category = "return-unspecified"
        expected_actor = opponent_id
    elif reason in ("SenderLoss_HitOutOfTurn", "ReceiverLoss_HitOutOfTurn", "SenderLoss_MultiHit"):
        category = "contact-rules"
    else:
        category = "unclassified"
    corroboration = "not_applicable" if expected_actor is None else "unavailable"
    if expected_actor is not None and last is not None and last["actor_id"] is not None:
        if last["actor_id"] == expected_actor:
            corroboration = "supported_by_final_hit"
        elif telemetry.get("parse_warning_count", 0) or telemetry.get("measurement_status") == "gaps_detected":
            corroboration = "unavailable_due_to_gaps"
        else:
            corroboration = "final_hit_disagrees"
    # Only refine return context when the terminal attempt has no known measurement gaps.
    if category == "return-unspecified" and corroboration == "supported_by_final_hit":
        if telemetry.get("measurement_status") != "gaps_detected" and not telemetry.get("parse_warning_count", 0):
            if last["phase"] == "serve":
                category = "serve-reception"
            elif last["phase"] == "rally":
                category = "rally-reception"
    net_contact = None
    if category == "shot-landing" and corroboration == "supported_by_final_hit":
        net_contact = any(
            event["kind"] == "collision" and event["collision_type"] == "Net" and event["line"] > last["line"]
            for event in events
        )
        if not net_contact and telemetry.get("measurement_status") == "gaps_detected":
            net_contact = None
    own_serve = bool(last and last["actor_id"] == player_id and last["phase"] == "serve")
    return_eligible = category in RETURN_CATEGORIES and not own_serve and corroboration != "final_hit_disagrees"
    incoming = None
    if return_eligible and not telemetry.get("parse_warning_count", 0) and telemetry.get("measurement_status") != "gaps_detected":
        if category in ("serve-reception", "rally-reception"):
            incoming = last
        elif category == "shot-landing" and corroboration == "supported_by_final_hit":
            if len(hits) >= 2 and hits[-2]["actor_id"] == opponent_id:
                incoming = hits[-2]
    return {
        "category": category,
        "raw_reason": reason,
        "score_confirms_loss": True,
        "contact_corroboration": corroboration,
        "net_contact_after_final_player_hit": net_contact,
        "final_hit_source_line": last["line"] if last else None,
        "return_practice_eligible": return_eligible,
        "incoming_context": incoming["phase"] if incoming and incoming["phase"] in ("serve", "rally") else "unknown",
        "incoming_hit_source_line": incoming["line"] if incoming else None,
        "interpretation": PATTERNS[category]["interpretation"],
    }


def context_counts(records: list[dict[str, Any]], category: str) -> dict[str, Any]:
    losses = [record for record in records if record["lost"]]
    count = sum(record["category"] == category for record in losses)
    return {
        "observed_points": len(records), "lost_points": len(losses), "category_losses": count,
        "share_of_lost_points": count / len(losses) if losses else None,
        "losses_per_100_observed_points": 100 * count / len(records) if records else None,
    }


def opponent_opportunities(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        diagnosis = record["diagnosis"]
        if diagnosis and diagnosis["return_practice_eligible"]:
            key = (record["opponent_id"], diagnosis["incoming_context"])
            groups.setdefault(key, []).append(record)
    opportunities = []
    for (opponent_id, context), selected in groups.items():
        match_count = len({record["match_id"] for record in selected})
        if len(selected) < MIN_LOSSES or match_count < MIN_MATCHES:
            continue
        opportunities.append({
            "id": f"opponent-{opponent_id}-{context}",
            "opponent_id": opponent_id, "opponent_name": selected[-1]["opponent_name"],
            "incoming_context": context, "losses": len(selected), "distinct_matches": match_count,
            "missed_returns": sum(r["category"] != "shot-landing" for r in selected),
            "failed_landings": sum(r["category"] == "shot-landing" for r in selected),
            "examples": [
                {"match_id": r["match_id"], "round": r["point"]["round"], "score": r["point"]["score"],
                 "source": r["point"]["source"], "line": r["point"]["line"],
                 "incoming_hit_source_line": r["diagnosis"]["incoming_hit_source_line"]}
                for r in selected[:5]
            ],
            "key_status": "withheld_unvalidated_reproduction",
            "limitation": "These are observed return losses, not a return-error rate or an identified spin/serve family. "
                          "A player-specific key is withheld until ball-machine reproduction is validated.",
        })
    return sorted(opportunities, key=lambda item: (-item["losses"], item["id"]))


def for_mode(profile: dict[str, Any], mode: str = "all") -> dict[str, Any]:
    if mode not in ("all", "ranked", "unranked"):
        raise ValueError(f"Unknown match mode: {mode}")
    scope = {
        "player": profile["player"],
        "matches": [
            {**match, "observed_points": [dict(point) for point in match["observed_points"]]}
            for match in profile["matches"]
            if mode == "all" or match["ranked"] == (mode == "ranked")
        ],
    }
    attach(scope)
    return scope


def attach(profile: dict[str, Any]) -> None:
    player_id = profile["player"]["id"]
    records = []
    seen = set()
    for match in profile["matches"]:
        if match["status"] == "inconsistent":
            continue
        for point in match["observed_points"]:
            key = (match["match_id"], point["round"], tuple(point["score"]))
            if key in seen:
                continue
            seen.add(key)
            lost = point["winner_id"] != player_id
            diagnosis = classify(point, player_id, match["opponent_id"]) if lost else None
            point["loss_analysis"] = diagnosis
            records.append({
                "lost": lost, "category": diagnosis["category"] if diagnosis else None,
                "diagnosis": diagnosis, "point": point, "match_id": match["match_id"],
                "match_status": match["status"], "mode": "ranked" if match["ranked"] else "unranked",
                "band": opponent_band(match["elo_gap"]), "opponent_id": match["opponent_id"],
                "opponent_name": match.get("opponent_name", match["opponent_id"]),
                "date": point["timestamp"][:10],
            })
    lost_records = [record for record in records if record["lost"]]
    categories = []
    for category, definition in PATTERNS.items():
        selected = [record for record in lost_records if record["category"] == category]
        if not selected:
            continue
        matches = {record["match_id"] for record in selected}
        evidence_counts = Counter(record["diagnosis"]["contact_corroboration"] for record in selected)
        return_losses = [record for record in selected if record["diagnosis"]["return_practice_eligible"]]
        return_matches = len({record["match_id"] for record in return_losses})
        ranked = category != "unclassified" and len(selected) >= MIN_LOSSES and len(matches) >= MIN_MATCHES
        categories.append({
            "id": category, "focus": definition["focus"],
            **context_counts(records, category),
            "distinct_matches": len(matches),
            "distinct_opponents": len({record["opponent_id"] for record in selected}),
            "contact_evidence_counts": dict(evidence_counts),
            "net_contact_observed": sum(record["diagnosis"]["net_contact_after_final_player_hit"] is True for record in selected),
            "net_contact_not_observed": sum(record["diagnosis"]["net_contact_after_final_player_hit"] is False for record in selected),
            "net_contact_unknown": sum(record["diagnosis"]["net_contact_after_final_player_hit"] is None for record in selected),
            "raw_reason_counts": dict(Counter(record["point"]["raw_reason"] for record in selected)),
            "by_mode": {mode: context_counts([r for r in records if r["mode"] == mode], category)
                        for mode in ("ranked", "unranked")},
            "by_opponent_strength": {band: context_counts([r for r in records if r["band"] == band], category)
                                     for band in ("lower", "similar", "higher")},
            "daily": [
                {"date": date, **context_counts([r for r in records if r["date"] == date], category)}
                for date in sorted({r["date"] for r in records})
            ],
            "examples": [
                {"match_id": r["match_id"], "round": r["point"]["round"], "score": r["point"]["score"],
                 "source": r["point"]["source"], "line": r["point"]["line"],
                 "contact_corroboration": r["diagnosis"]["contact_corroboration"]}
                for r in selected[:3]
            ],
            "priority": None, "eligible_for_priority": ranked,
            "machine_practice_eligible": len(return_losses) >= MIN_LOSSES and return_matches >= MIN_MATCHES,
            "machine_practice_losses": len(return_losses), "machine_practice_matches": return_matches,
            "interpretation": definition["interpretation"], "recipe_ids": definition["recipe_ids"],
        })
    categories.sort(key=lambda item: (-item["category_losses"], item["id"]))
    priorities = []
    for category in categories:
        if not category["eligible_for_priority"]:
            continue
        definition = PATTERNS[category["id"]]
        category["priority"] = len(priorities) + 1
        count = category["category_losses"]
        priorities.append({
            "priority": category["priority"], "category_id": category["id"],
            "focus": category["focus"],
            "evidence": f"{count} of {len(lost_records)} observed lost points "
                        f"({category['share_of_lost_points']:.1%}), across {category['distinct_matches']} matches "
                        f"and {category['distinct_opponents']} opponents.",
            "interpretation": definition["interpretation"],
            "practice": definition["practice"],
            "measure": "Record practice successes out of attempts. After another block of at least 100 observed match points, "
                       "compare this category's losses per 100 points, keeping mode and opponent strength visible. "
                       "This is a proposed review interval, not a promised improvement.",
            "recipe_ids": definition["recipe_ids"],
            "priority_basis": "observed lost-point count; not estimated recoverable points",
            "machine_practice_eligible": category["machine_practice_eligible"],
            "machine_practice_losses": category["machine_practice_losses"],
            "machine_practice_matches": category["machine_practice_matches"],
        })
    profile["loss_analysis"] = {
        "version": 1,
        "ranking_policy": "All observed points have equal weight, with no ranked-mode, recency, or Elo multiplier. "
                          "Longer matches contribute more observed points. Validated points from incomplete matches are included.",
        "minimum_evidence": {"losses": MIN_LOSSES, "distinct_matches": MIN_MATCHES},
        "observed_points": len(records),
        "observed_lost_points": len(lost_records),
        "completed_match_lost_points": sum(r["match_status"] == "completed" for r in lost_records),
        "incomplete_match_lost_points": sum(r["match_status"] == "incomplete" for r in lost_records),
        "unclassified_lost_points": sum(r["category"] == "unclassified" for r in lost_records),
        "categories": categories,
        "limits": [
            "Lost points are counted once, using single-step score changes. Missing score transitions cannot contribute a loss diagnosis.",
            "Loss counts measure observed cost, not technical causality, avoidability, or points guaranteed to be recovered.",
            "The denominator is observed points or observed losses as labeled, never serves attempted or shots attempted.",
            "Serve-versus-rally missed returns require a consistent final opponent hit with no known measurement gaps.",
            "Net contact is supporting evidence, not proof of an unforced net error; no observed net contact does not mean a long or wide miss.",
            "Small-sample and unclassified patterns remain visible but do not outrank supported training priorities.",
        ],
    }
    profile["training_plan"] = priorities or [{
        "priority": 1, "category_id": None, "focus": "Collect enough point-loss evidence",
        "evidence": f"{len(lost_records)} observed lost points; no classified pattern meets {MIN_LOSSES} losses across {MIN_MATCHES} matches.",
        "interpretation": "No specific technical priority is established by this sample.",
        "practice": "Record more complete match points and inspect missing or unsupported loss reasons.",
        "measure": "Reassess when a loss pattern reaches the displayed evidence threshold.",
        "recipe_ids": [],
    }]
    profile["opponent_opportunities"] = opponent_opportunities(records)
    profile["serve_reception_pilot"] = serve_reception.analyze(profile)
    profile["shot_catalogue"] = shot_catalogue.build()


def render_section(
    profile: dict[str, Any], table: Callable[[list[str], list[list[Any]]], str],
    escape: Callable[..., str],
) -> str:
    analysis = profile.get("loss_analysis")
    if analysis is None:
        return ""
    categories = analysis["categories"]
    parts = [
        "<h2>Highest-priority training from lost points</h2>",
        f"<p>{analysis['observed_lost_points']} lost points across {analysis['observed_points']} observed points: "
        f"{analysis['completed_match_lost_points']} losses in completed matches and "
        f"{analysis['incomplete_match_lost_points']} in incomplete matches.</p>",
        f"<p>{escape(analysis['ranking_policy'])}</p>",
        f"<p>Priorities require at least {MIN_LOSSES} classified losses across {MIN_MATCHES} matches. "
        "Ranking measures observed point cost, not recoverable points or a proven stroke defect.</p>",
        table(["Priority", "Training focus", "Lost points", "Share of losses", "Matches", "Opponents"], [
            [c["priority"] or "Monitor / unclassified", c["focus"], c["category_losses"],
             f"{c['share_of_lost_points']:.1%}", c["distinct_matches"], c["distinct_opponents"]]
            for c in sorted(categories, key=lambda c: (c["priority"] is None, c["priority"] or 0, -c["category_losses"]))
        ]),
    ]
    for category in categories:
        parts.append(f"<details><summary>{escape(category['focus'])}: evidence and context</summary>")
        parts.append(f"<p>{escape(category['interpretation'])}</p>")
        if category["id"] == "shot-landing":
            parts.append(f"<p>After your final observed hit: net contact recorded in {category['net_contact_observed']} losses; "
                         f"not recorded in {category['net_contact_not_observed']}; unknown in {category['net_contact_unknown']}. "
                         "No net contact recorded does not establish a long/wide miss.</p>")
        parts.append(table(["Contact corroboration", "Losses"], [[k, v] for k, v in category["contact_evidence_counts"].items()]))
        for label, values in (("Mode", category["by_mode"]), ("Opponent strength", category["by_opponent_strength"])):
            parts.append(table([label, "Observed points", "All losses", "Pattern losses", "Pattern losses / 100 points"], [
                [key, value["observed_points"], value["lost_points"], value["category_losses"],
                 f"{value['losses_per_100_observed_points']:.1f}" if value["losses_per_100_observed_points"] is not None else "N/A"]
                for key, value in values.items()
            ]))
        parts.append(table(["Example match", "Round", "Score (participant order)", "Source", "Line"], [
            [e["match_id"], e["round"], "-".join(map(str, e["score"])), Path(e["source"]).name, e["line"]]
            for e in category["examples"]
        ]))
        parts.append("</details>")
    return "\n".join(parts)
