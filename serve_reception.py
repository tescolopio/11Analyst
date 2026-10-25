"""Conservative, observed opponent-serve first-return pilot; not a spin classifier."""

from collections import Counter


FAILURES = ("missed_first_return", "first_return_failed_to_land")
RESOLVED = (*FAILURES, "return_continued", "point_won_on_first_return")
RULE_REASONS = {"SenderLoss_HitOutOfTurn", "ReceiverLoss_HitOutOfTurn", "SenderLoss_MultiHit"}


def analyze(profile):
    player = profile["player"]["id"]
    records, excluded, seen = [], Counter(), set()
    observed_points = 0
    for match in profile["matches"]:
        if match["status"] == "inconsistent":
            continue
        for point in match["observed_points"]:
            key = (match["match_id"], point["round"], tuple(point["score"]))
            if key in seen:
                continue
            seen.add(key)
            observed_points += 1
            telemetry = point.get("telemetry", {})
            if telemetry.get("status") not in ("bounded", "bounded_multiple_attempts"):
                excluded["unbounded_point"] += 1
                continue
            if telemetry.get("parse_warning_count") or telemetry.get("measurement_status") != "no_detected_gaps":
                excluded["point_with_measurement_gaps_or_unknown_quality"] += 1
                continue
            events = telemetry.get("events", [])
            terminal = telemetry.get("attempts")
            for attempt in sorted({event["attempt"] for event in events}):
                hits = [event for event in events if event["attempt"] == attempt and event["kind"] == "hit"]
                if not hits or hits[0].get("phase") != "serve":
                    excluded["attempt_without_confirmed_initial_serve"] += 1
                    continue
                if hits[0].get("actor_id") != match["opponent_id"]:
                    excluded["own_serve_attempt" if hits[0].get("actor_id") == player else "serve_attempt_with_unknown_actor"] += 1
                    continue
                if attempt != terminal:
                    excluded["nonterminal_opponent_serve_attempt"] += 1
                    continue
                reason = point["raw_reason"]
                if reason in ("ServiceFault_DidNotHitNearSide", "ServiceFault_DidNotHitFarSide"):
                    excluded["serve_fault_point"] += 1
                    continue
                won = point["winner_id"] == player
                outcome = "unknown"
                if len(hits) == 1 and not won and reason == "ReceiverLoss_DidNotHitBallAfterBounce":
                    outcome = "missed_first_return"
                elif len(hits) >= 2 and hits[1].get("actor_id") == player and hits[1].get("phase") == "rally":
                    if len(hits) == 2 and not won and reason == "SenderLoss_DidNotHitFarSide":
                        outcome = "first_return_failed_to_land"
                    elif len(hits) == 2 and won and reason == "ReceiverLoss_DidNotHitBallAfterBounce":
                        outcome = "point_won_on_first_return"
                    elif (len(hits) >= 3 and hits[2].get("actor_id") == match["opponent_id"]
                          and hits[2].get("phase") == "rally" and reason not in RULE_REASONS):
                        # A later rally loss must not be charged to the first return.
                        outcome = "return_continued"
                records.append({
                    "match_id": match["match_id"], "round": point["round"], "score": point["score"],
                    "opponent_id": match["opponent_id"], "opponent_name": match.get("opponent_name", match["opponent_id"]),
                    "source": point["source"], "line": point["line"], "serve_line": hits[0]["line"],
                    "attempt": attempt, "outcome": outcome, "point_won": won,
                })
    counts = Counter(record["outcome"] for record in records)
    resolved = sum(counts[outcome] for outcome in RESOLVED)
    failures = sum(counts[outcome] for outcome in FAILURES)
    return {
        "category": "opponent-serve-first-return", "classifier_version": "observed-first-return-1",
        "evidence_status": "conservative_observed_pilot_not_in_game_validated",
        "observed_points": observed_points, "receiving_attempts": len(records),
        "resolved_attempts": resolved, "unknown_outcomes": counts["unknown"],
        "confirmed_failures": failures, "counts": {name: counts[name] for name in (*RESOLVED, "unknown")},
        "failure_fraction_of_resolved_attempts": failures / resolved if resolved else None,
        "outcome_coverage": resolved / len(records) if records else None,
        "distinct_matches": len({record["match_id"] for record in records}),
        "exclusions": dict(excluded), "examples": records,
        "limits": [
            "Denominator: bounded terminal attempts with a confirmed initial opponent serve and no known measurement gaps; not all serves played.",
            "Known serve-fault points and nonterminal attempts (possible lets, faults or restarts) are excluded. Exclusion counts mix point-level and attempt-level reasons and must not be summed as one denominator.",
            "A continued return means an opponent rally contact was observed after your first return; it is not a measured placement or technique rating.",
            "Unknown outcomes remain separate. The resolved-attempt fraction is subject to missing-data selection and is not an all-match return-error rate.",
            "This broad pilot does not classify spin, serve length or backhand placement. Log units and their mapping to the glossary frame remain unvalidated.",
        ],
    }
