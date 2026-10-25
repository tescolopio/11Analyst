from copy import deepcopy
import unittest

import loss_analysis
import practice


def event(actor="1909208", phase="rally", attempt=1, line=10):
    return {"kind": "hit", "actor_id": actor, "phase": phase, "attempt": attempt,
            "line": line, "before": None, "after": None}


def point(index=1, reason="SenderLoss_DidNotHitFarSide", won=False, events=None, status="bounded"):
    return {
        "round": 1, "score": [0, index], "winner_id": "1909208" if won else "2",
        "timestamp": "2026-10-24T08:00:00", "raw_reason": reason,
        "source": "test.log", "line": 100 + index,
        "telemetry": {
            "status": status, "attempts": 1, "events": events if events is not None else [event()],
            "parse_warning_count": 0, "measurement_status": "no_detected_gaps",
        },
    }


def match(match_id, points, ranked=False, gap=0, status="completed"):
    return {
        "match_id": str(match_id), "observed_points": points, "ranked": ranked,
        "elo_gap": gap, "opponent_id": "2", "status": status,
    }


def profile(matches):
    return {"player": {"id": "1909208"}, "matches": matches}


class LossClassificationTests(unittest.TestCase):
    def test_loss_families(self):
        for reason, expected in (
            ("SenderLoss_DidNotHitFarSide", "shot-landing"),
            ("ServiceFault_DidNotHitNearSide", "serve-legality"),
            ("ServiceFault_DidNotHitFarSide", "serve-legality"),
            ("SenderLoss_HitOutOfTurn", "contact-rules"),
            ("SenderLoss_MultiHit", "contact-rules"),
            ("ReceiverLoss_HitOutOfTurn", "contact-rules"),
            ("NEW_UNKNOWN_REASON", "unclassified"),
        ):
            with self.subTest(reason=reason):
                result = loss_analysis.classify(point(reason=reason), "1909208", "2")
                self.assertEqual(result["category"], expected)

    def test_return_phase_requires_consistent_final_opponent_hit(self):
        for phase, expected in (("serve", "serve-reception"), ("rally", "rally-reception"),
                                (None, "return-unspecified")):
            p = point(reason="ReceiverLoss_DidNotHitBallAfterBounce", events=[event("2", phase)])
            self.assertEqual(loss_analysis.classify(p, "1909208", "2")["category"], expected)
            p["telemetry"]["measurement_status"] = "gaps_detected"
            self.assertEqual(loss_analysis.classify(p, "1909208", "2")["category"], "return-unspecified")
        p = point(reason="ReceiverLoss_DidNotHitBallAfterBounce")
        result = loss_analysis.classify(p, "1909208", "2")
        self.assertEqual(result["category"], "return-unspecified")
        self.assertEqual(result["contact_corroboration"], "final_hit_disagrees")

    def test_terminal_attempt_only(self):
        p = point(reason="ReceiverLoss_DidNotHitBallAfterBounce", events=[event("2", "serve")],
                  status="bounded_multiple_attempts")
        p["telemetry"]["attempts"] = 2
        self.assertEqual(loss_analysis.classify(p, "1909208", "2")["category"], "return-unspecified")

    def test_net_contact_is_observed_not_inferred(self):
        net = {"kind": "collision", "collision_type": "Net", "attempt": 1, "line": 12}
        p = point(events=[event(), net])
        self.assertTrue(loss_analysis.classify(p, "1909208", "2")["net_contact_after_final_player_hit"])
        p["telemetry"]["events"] = [net, event(line=14)]
        self.assertFalse(loss_analysis.classify(p, "1909208", "2")["net_contact_after_final_player_hit"])
        p["telemetry"]["measurement_status"] = "gaps_detected"
        self.assertIsNone(loss_analysis.classify(p, "1909208", "2")["net_contact_after_final_player_hit"])

    def test_unknown_actor_and_missing_event_not_false_contradiction(self):
        p = point(events=[event(None)])
        self.assertEqual(loss_analysis.classify(p, "1909208", "2")["contact_corroboration"], "unavailable")
        p = point(events=[event("2")])
        p["telemetry"]["parse_warning_count"] = 1
        self.assertEqual(loss_analysis.classify(p, "1909208", "2")["contact_corroboration"], "unavailable_due_to_gaps")


class LossRankingTests(unittest.TestCase):
    def test_loss_counts_ranked_not_match_wins_and_mode_weighting_equal(self):
        p = profile([
            match(1, [point(i) for i in range(1, 5)] + [point(5, won=True)], ranked=False, gap=100),
            match(2, [point(1), point(2, reason="ServiceFault_DidNotHitNearSide")], ranked=True, gap=101),
            match(3, [point(i, reason="ServiceFault_DidNotHitFarSide") for i in range(1, 7)]),
        ])
        loss_analysis.attach(p)
        self.assertEqual([item["category_id"] for item in p["training_plan"]], ["serve-legality", "shot-landing"])
        self.assertEqual(p["loss_analysis"]["observed_points"], 13)
        self.assertEqual(p["loss_analysis"]["observed_lost_points"], 12)
        landing = next(c for c in p["loss_analysis"]["categories"] if c["id"] == "shot-landing")
        self.assertEqual(landing["category_losses"], 5)
        self.assertAlmostEqual(landing["share_of_lost_points"], 5 / 12)
        self.assertEqual(landing["by_mode"]["ranked"]["category_losses"], 1)
        self.assertEqual(landing["by_mode"]["unranked"]["category_losses"], 4)
        self.assertEqual(landing["by_opponent_strength"]["similar"]["category_losses"], 4)
        self.assertEqual(landing["by_opponent_strength"]["higher"]["category_losses"], 1)
        self.assertIsNone(p["matches"][0]["observed_points"][-1]["loss_analysis"])

    def test_sample_threshold_and_unclassified_do_not_become_technical_priority(self):
        p = profile([
            match(1, [point(i) for i in range(1, 11)]),
            match(2, [point(i, reason="unknown") for i in range(1, 11)]),
            match(3, [point(i, reason="unknown") for i in range(1, 11)]),
        ])
        loss_analysis.attach(p)
        self.assertIsNone(p["training_plan"][0]["category_id"])
        self.assertEqual(p["loss_analysis"]["unclassified_lost_points"], 20)
        self.assertTrue(all(c["priority"] is None for c in p["loss_analysis"]["categories"]))

    def test_dedup_and_incomplete_points_included_but_inconsistent_excluded(self):
        first = point()
        p = profile([
            match(1, [first, deepcopy(first)]),
            match(2, [point()], status="incomplete"),
            match(3, [point()], status="inconsistent"),
        ])
        loss_analysis.attach(p)
        self.assertEqual(p["loss_analysis"]["observed_points"], 2)
        self.assertEqual(p["loss_analysis"]["completed_match_lost_points"], 1)
        self.assertEqual(p["loss_analysis"]["incomplete_match_lost_points"], 1)

    def test_zero_losses_no_division_by_zero_or_false_weakness(self):
        p = profile([match(1, [point(won=True)])])
        loss_analysis.attach(p)
        self.assertEqual(p["loss_analysis"]["categories"], [])
        self.assertIsNone(p["training_plan"][0]["category_id"])

    def test_priorities_link_to_real_recipes_not_fabricated_serve_settings(self):
        points = [point(i, reason="ServiceFault_DidNotHitFarSide") for i in range(1, 4)]
        p = profile([match(1, deepcopy(points)), match(2, deepcopy(points))])
        loss_analysis.attach(p)
        recipes = practice.build(p)
        serve = next(r for r in recipes["recipes"] if r["id"] == "serve-legality")
        self.assertEqual(serve["training_priorities"][0]["priority"], 1)
        self.assertFalse(serve["settings_candidate_available"])
        self.assertNotIn("serve-legality", [c["recipe_id"] for c in recipes["settings_candidates"]])


class ReturnOpportunityTests(unittest.TestCase):
    def sample(self, events, reason="SenderLoss_DidNotHitFarSide"):
        return profile([match(mid, [point(i, reason=reason, events=deepcopy(events)) for i in range(1, 4)],
                              ranked=mid == 2) for mid in (1, 2)])

    def test_missed_and_contacted_serve_returns_share_opponent_context(self):
        p = self.sample([event("2", "serve"), event(line=11)])
        p["matches"][0]["observed_points"][0] = point(
            reason="ReceiverLoss_DidNotHitBallAfterBounce", events=[event("2", "serve")])
        loss_analysis.attach(p)
        opportunity = p["opponent_opportunities"][0]
        self.assertEqual(opportunity["incoming_context"], "serve")
        self.assertEqual((opportunity["losses"], opportunity["distinct_matches"]), (6, 2))
        self.assertEqual((opportunity["missed_returns"], opportunity["failed_landings"]), (1, 5))
        self.assertEqual(opportunity["examples"][0]["incoming_hit_source_line"], 10)
        self.assertEqual(opportunity["key_status"], "withheld_unvalidated_reproduction")
        self.assertNotIn("key", opportunity)

    def test_context_requires_terminal_attempt_without_gaps(self):
        p = self.sample([event("2", "serve"), event(line=11)])
        for m in p["matches"]:
            for item in m["observed_points"]:
                item["telemetry"]["parse_warning_count"] = 1
        loss_analysis.attach(p)
        self.assertEqual(p["opponent_opportunities"][0]["incoming_context"], "unknown")
        self.assertIsNone(p["opponent_opportunities"][0]["examples"][0]["incoming_hit_source_line"])

    def test_own_serves_conflicts_and_rules_never_become_return_practice(self):
        for reason, events in (
            ("ServiceFault_DidNotHitFarSide", [event(phase="serve")]),
            ("SenderLoss_DidNotHitFarSide", [event(phase="serve")]),
            ("SenderLoss_DidNotHitFarSide", [event("2")]),
            ("SenderLoss_MultiHit", [event()]),
            ("unknown", [event()]),
        ):
            with self.subTest(reason=reason, events=events):
                p = self.sample(events, reason)
                loss_analysis.attach(p)
                self.assertEqual(p["opponent_opportunities"], [])
                self.assertFalse(p["training_plan"][0].get("machine_practice_eligible"))
                self.assertEqual(practice.training_candidates(p, practice.candidate_settings()), [])

    def test_thresholds_apply_per_opponent_context_and_mode(self):
        p = self.sample([event("2", "serve")], "ReceiverLoss_DidNotHitBallAfterBounce")
        original = deepcopy(p)
        self.assertEqual(len(loss_analysis.for_mode(p)["opponent_opportunities"]), 1)
        self.assertEqual(loss_analysis.for_mode(p, "ranked")["opponent_opportunities"], [])
        self.assertEqual(p, original)
        p["matches"][1]["opponent_id"] = "3"
        for item in p["matches"][1]["observed_points"]:
            item["telemetry"]["events"][0]["actor_id"] = "3"
        self.assertEqual(loss_analysis.for_mode(p)["opponent_opportunities"], [])
        p = self.sample([event("2", "serve")], "ReceiverLoss_DidNotHitBallAfterBounce")
        p["matches"][1]["observed_points"].pop()
        self.assertEqual(loss_analysis.for_mode(p)["opponent_opportunities"][0]["losses"], 5)
        p["matches"][1]["observed_points"].pop()
        self.assertEqual(loss_analysis.for_mode(p)["opponent_opportunities"], [])

    def test_duplicate_won_and_inconsistent_points_do_not_add_opportunities(self):
        p = self.sample([event("2", "rally")], "ReceiverLoss_DidNotHitBallAfterBounce")
        p["matches"][0]["observed_points"].append(deepcopy(p["matches"][0]["observed_points"][0]))
        p["matches"][1]["observed_points"][0]["winner_id"] = "1909208"
        self.assertEqual(loss_analysis.for_mode(p)["opponent_opportunities"][0]["losses"], 5)
        p["matches"][1]["status"] = "inconsistent"
        self.assertEqual(loss_analysis.for_mode(p)["opponent_opportunities"], [])

    def test_general_plan_progression_and_stable_settings(self):
        p = self.sample([event("2", "rally"), event(line=11)])
        candidates = practice.training_candidates(p, practice.candidate_settings())
        self.assertEqual([c["recipe_id"] for c in candidates], ["plan-shot-landing"])
        candidate = candidates[0]
        self.assertEqual([s["isActive"] for s in candidate["settings"]["shots"]["data"].values()], ["True", "False"])
        self.assertEqual([s["feeds"] for s in candidate["stages"]], [[1], [2]])
        digest = practice.settings_digest(candidate["settings"])
        p["matches"][0]["observed_points"].append(point(4))
        self.assertEqual(practice.settings_digest(practice.training_candidates(p, practice.candidate_settings())[0]["settings"]), digest)

    def test_rally_and_unknown_context_plans_and_missing_serve_seed(self):
        for phase, expected, active_feeds in (("rally", "plan-rally-reception", 2),
                                              (None, "plan-return-unspecified", 1),
                                              ("serve", None, 0)):
            p = self.sample([event("2", phase)], "ReceiverLoss_DidNotHitBallAfterBounce")
            candidates = practice.training_candidates(p, practice.candidate_settings())
            self.assertEqual([c["recipe_id"] for c in candidates], [expected] if expected else [])
            if candidates:
                self.assertEqual(sum(s["isActive"] == "True" for s in candidates[0]["settings"]["shots"]["data"].values()), active_feeds)

    def test_serve_plan_uses_serve_source_not_rally_source(self):
        p = self.sample([event("2", "serve")], "ReceiverLoss_DidNotHitBallAfterBounce")
        sources = practice.candidate_settings()
        serve = deepcopy(sources[0]["settings"]["shots"]["data"]["ANLY01"])
        serve["position"]["raw"]["y"] = "0.12345"
        practice.build_collections(sources, {"shot": serve}, {})
        candidate = practice.training_candidates(p, sources)[0]
        self.assertEqual(candidate["recipe_id"], "plan-serve-reception")
        self.assertEqual(candidate["settings"]["shots"]["data"]["ANLY01"]["position"]["raw"]["y"], "0.12345")


if __name__ == "__main__":
    unittest.main()
