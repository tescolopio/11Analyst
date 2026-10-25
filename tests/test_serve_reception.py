from copy import deepcopy
import unittest

import serve_reception
from test_loss_analysis import event, point, match, profile


class ServeReceptionTests(unittest.TestCase):
    def analyze(self, points):
        return serve_reception.analyze(profile([match(1, points)]))

    def test_resolved_outcomes_include_wins_and_later_rally_losses(self):
        serve, returned, opponent = event("2", "serve"), event(line=11), event("2", "rally", line=12)
        points = [
            point(1, reason="ReceiverLoss_DidNotHitBallAfterBounce", events=[serve]),
            point(2, events=[serve, returned]),
            point(3, reason="ReceiverLoss_DidNotHitBallAfterBounce", won=True, events=[serve, returned]),
            point(4, events=[serve, returned, opponent, event(line=13)]),
            point(5, won=True, events=[serve, returned, opponent]),
            point(6, reason="Unknown", events=[serve, returned]),
        ]
        original = deepcopy(points)
        result = self.analyze(points)
        self.assertEqual(result["receiving_attempts"], 6)
        self.assertEqual(result["resolved_attempts"], 5)
        self.assertEqual(result["confirmed_failures"], 2)
        self.assertEqual(result["counts"]["return_continued"], 2)
        self.assertEqual(result["unknown_outcomes"], 1)
        self.assertEqual(result["failure_fraction_of_resolved_attempts"], 2 / 5)
        self.assertEqual(points, original)
        self.assertEqual(result["examples"][0]["serve_line"], 10)

    def test_contact_alone_is_not_success_and_rule_losses_are_unknown(self):
        for reason, won in (("ReceiverLoss_HitOutOfTurn", True), ("SenderLoss_MultiHit", False),
                            ("Unknown", True)):
            p = point(reason=reason, won=won, events=[event("2", "serve"), event()])
            self.assertEqual(self.analyze([p])["unknown_outcomes"], 1)
        p = point(reason="SenderLoss_MultiHit", events=[event("2", "serve"), event(), event("2")])
        self.assertEqual(self.analyze([p])["unknown_outcomes"], 1)

    def test_earlier_attempt_does_not_inherit_terminal_loss(self):
        p = point(reason="ReceiverLoss_DidNotHitBallAfterBounce", status="bounded_multiple_attempts",
                  events=[event("2", "serve"), event("2", "serve", attempt=2)])
        p["telemetry"]["attempts"] = 2
        result = self.analyze([p])
        self.assertEqual(result["receiving_attempts"], 1)
        self.assertEqual(result["confirmed_failures"], 1)
        self.assertEqual(result["examples"][0]["attempt"], 2)
        self.assertEqual(result["exclusions"]["nonterminal_opponent_serve_attempt"], 1)

    def test_faults_gaps_unbounded_own_and_unknown_serves_excluded(self):
        points = [
            point(1, reason="ServiceFault_DidNotHitFarSide", events=[event("2", "serve")]),
            point(2, status="partial"), point(3, events=[event("2", "serve")]),
            point(4, events=[event(phase="serve")]), point(5, events=[event(None, "serve")]),
            point(6, events=[event("2", None)]),
        ]
        points[2]["telemetry"]["measurement_status"] = "gaps_detected"
        result = self.analyze(points)
        self.assertEqual(result["receiving_attempts"], 0)
        for reason in ("own_serve_attempt", "serve_attempt_with_unknown_actor", "attempt_without_confirmed_initial_serve"):
            self.assertEqual(result["exclusions"][reason], 1)
        self.assertIsNone(result["failure_fraction_of_resolved_attempts"])
        self.assertIsNone(result["outcome_coverage"])

    def test_dedup_incomplete_included_and_inconsistent_excluded(self):
        p = point(events=[event("2", "serve")])
        result = serve_reception.analyze(profile([
            match(1, [p, deepcopy(p)]), match(2, [p], status="incomplete"),
            match(3, [p], status="inconsistent"),
        ]))
        self.assertEqual(result["observed_points"], 2)
        self.assertEqual(result["receiving_attempts"], 2)

    def test_scope_recomputes_without_mutation(self):
        import loss_analysis
        p = point(events=[event("2", "serve")])
        source = profile([match(1, [p], ranked=True), match(2, [deepcopy(p)])])
        original = deepcopy(source)
        result = loss_analysis.for_mode(source, "ranked")
        self.assertEqual(result["serve_reception_pilot"]["receiving_attempts"], 1)
        self.assertEqual(source, original)
