from copy import deepcopy
import json
import re
import unittest

import analyst
import dashboard
import loss_analysis
import practice
from test_analyst import snapshot


class DashboardTests(unittest.TestCase):
    def make_profile(self):
        records = [
            snapshot(((0, 0),), line=1),
            snapshot(((0, 1),), line=2, LastPointReason="SenderLoss_DidNotHitFarSide"),
            snapshot(((5, 11), (8, 11)), winner="2", line=3),
            snapshot(((0, 0),), line=4, MatchId="124", Ranked="True"),
            snapshot(((1, 0),), line=5, MatchId="124", Ranked="True"),
            snapshot(((11, 5), (11, 8)), winner="1909208", line=6, MatchId="124", Ranked="True"),
        ]
        result = analyst.make_profile([], records, analyst.DEFAULT_PLAYER_ID)
        loss_analysis.attach(result)
        return result

    def test_scoped_counts_and_results_do_not_leak_other_mode(self):
        result = dashboard.build_data(self.make_profile())
        self.assertEqual(result["views"]["all"]["summary"]["completed"], 2)
        self.assertEqual(result["views"]["ranked"]["summary"]["wins"], 1)
        self.assertEqual(result["views"]["ranked"]["summary"]["losses"], 0)
        self.assertEqual(result["views"]["unranked"]["summary"]["wins"], 0)
        self.assertEqual(result["views"]["unranked"]["summary"]["losses"], 1)
        self.assertEqual(result["views"]["ranked"]["loss_analysis"]["observed_lost_points"], 0)
        self.assertEqual(result["views"]["unranked"]["loss_analysis"]["observed_lost_points"], 1)
        self.assertEqual(len(result["matches"]), 2)

    def test_dashboard_does_not_mutate_persistent_profile(self):
        profile = self.make_profile()
        original = deepcopy(profile)
        dashboard.build_data(profile)
        self.assertEqual(profile, original)

    def test_glossary_pilot_and_player_preference_are_embedded(self):
        profile = self.make_profile()
        data = dashboard.build_data(profile)
        self.assertEqual(data["player"]["handedness"], "right")
        self.assertEqual(dashboard.player_context({"id": "999"})["handedness"], "unknown")
        for mode in ("all", "ranked", "unranked"):
            self.assertIn("serve_reception_pilot", data["views"][mode])
        html = analyst.render_html(profile)
        for element in ('id="spin-canvas"', 'id="spin-play"', 'id="pilot-form"', 'id="pilot-feed"'):
            self.assertIn(element, html)
        self.assertNotIn("@@SPIN_SCRIPT@@", html)
        self.assertNotIn("@@PILOT_SCRIPT@@", html)

    def test_glossary_can_render_without_logged_matches(self):
        profile = analyst.make_profile([], [], analyst.DEFAULT_PLAYER_ID)
        html = analyst.render_html(profile)
        self.assertIn('id="spin-canvas"', html)
        data = dashboard.build_data(profile)
        self.assertEqual(data["views"]["all"]["serve_reception_pilot"]["receiving_attempts"], 0)

    def test_hero_review_is_inline_and_keeps_real_validation_pending(self):
        html = analyst.render_html(self.make_profile())
        for element in ("hero-review-shot", "hero-review-form", "hero-review-synthetic"):
            self.assertIn(f'id="{element}"', html)
        self.assertNotIn("@@HERO_REVIEW_SCRIPT@@", html)
        self.assertLess(html.index("root.ElevenHeroReview="), html.index("root.ElevenHero="))
        self.assertIn("Real placement, length and spin validation: pending.", html)

    def test_catalogue_is_embedded_once_with_no_named_shot_diagnoses(self):
        profile = self.make_profile()
        before = deepcopy(profile)
        data = dashboard.build_data(profile)
        self.assertEqual(data["shot_catalogue"]["taxonomy_version"], "shot-lexicon-1")
        self.assertEqual(len(data["shot_catalogue"]["categories"]), 12)
        for scope in data["views"].values():
            self.assertNotIn("shot_catalogue", scope)
        html = analyst.render_html(profile)
        self.assertIn('id="catalogue-selected-name"', html)
        self.assertIn("ElevenCatalogue.initialize", html)
        self.assertNotIn("@@CATALOGUE_SCRIPT@@", html)
        self.assertEqual(profile, before)

    def test_payload_is_inline_valid_json_with_no_external_assets(self):
        html = analyst.render_html(self.make_profile())
        match = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match)
        data = json.loads(match[1])
        self.assertEqual(data["format"], "11analyst.dashboard")
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link rel="stylesheet"', html)
        self.assertNotIn("@@DATA@@", html)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("JavaScript is disabled", html)

    def test_html_and_json_script_injection_are_escaped(self):
        profile = self.make_profile()
        hostile = '</script><img src=x onerror="alert(1)">'
        profile["player"]["observed_names"] = [hostile]
        profile["matches"][0]["opponent_name"] = hostile
        html = analyst.render_html(profile)
        self.assertNotIn(hostile, html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;/script&gt;", html)
        payload = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, re.S)[1]
        self.assertEqual(json.loads(payload)["player"]["observed_names"], [hostile])

    def test_empty_mode_has_null_rates_not_zero_and_no_false_training_priority(self):
        profile = analyst.make_profile([], [snapshot()], analyst.DEFAULT_PLAYER_ID)
        data = dashboard.build_data(profile)
        ranked = data["views"]["ranked"]
        self.assertIsNone(ranked["summary"]["point_win_rate"])
        self.assertEqual(ranked["loss_analysis"]["observed_points"], 0)
        self.assertIsNone(ranked["training_plan"][0]["category_id"])

    def test_mode_recalculates_priority_threshold_not_just_display_counts(self):
        records = []
        for mid, ranked in (("100", False), ("101", False), ("102", True)):
            for index in range(4):
                records.append(snapshot(
                    ((0, index),), line=len(records) + 1, MatchId=mid,
                    Ranked=str(ranked), LastPointReason="SenderLoss_DidNotHitFarSide",
                ))
        profile = analyst.make_profile([], records, analyst.DEFAULT_PLAYER_ID)
        profile["practice_patterns"] = practice.build(profile)
        data = dashboard.build_data(profile)
        self.assertEqual(data["views"]["all"]["training_plan"][0]["category_id"], "shot-landing")
        self.assertEqual(data["views"]["unranked"]["training_plan"][0]["category_id"], "shot-landing")
        self.assertIsNone(data["views"]["ranked"]["training_plan"][0]["category_id"])
        self.assertEqual(data["views"]["ranked"]["loss_analysis"]["observed_lost_points"], 3)
        self.assertEqual([item["id"] for item in data["publishing"]["plans"]], ["plan-shot-landing"])
        self.assertTrue(data["views"]["unranked"]["training_plan"][0]["machine_practice_eligible"])
        self.assertFalse(data["views"]["ranked"]["training_plan"][0].get("machine_practice_eligible"))
        self.assertEqual(data["views"]["ranked"]["opponent_opportunities"], [])

    def test_point_identity_and_evidence_survive_compaction(self):
        profile = self.make_profile()
        data = dashboard.build_data(profile)
        point = data["matches"][0]["points"][0]
        self.assertEqual(point["id"], "123:1:0:1")
        self.assertEqual(point["loss"]["category"], "shot-landing")
        self.assertEqual(point["source"], "test.log")
        self.assertEqual(point["line"], 2)

    def test_publishing_revisions_are_stable_content_hashes_without_mutation(self):
        profile = self.make_profile()
        profile["practice_patterns"] = {"settings_candidates": practice.candidate_settings()}
        original = deepcopy(profile)
        first = dashboard.build_data(profile)["publishing"]["candidate_sha256"]
        self.assertEqual(profile, original)
        self.assertRegex(first["repeatable-contact"], r"^[a-f0-9]{64}$")
        settings = profile["practice_patterns"]["settings_candidates"][0]["settings"]
        profile["practice_patterns"]["settings_candidates"][0]["settings"] = dict(reversed(list(settings.items())))
        self.assertEqual(first, dashboard.build_data(profile)["publishing"]["candidate_sha256"])
        settings["shots"]["data"]["ANLY01"]["speedAndRate"]["raw"]["speed"] = "9"
        changed = dashboard.build_data(profile)["publishing"]["candidate_sha256"]
        self.assertNotEqual(first["repeatable-contact"], changed["repeatable-contact"])
        self.assertEqual(first["two-location-recovery"], changed["two-location-recovery"])

    def test_invalid_candidate_cannot_be_presented_as_prepared_for_publishing(self):
        profile = self.make_profile()
        candidates = practice.candidate_settings()
        candidates[0]["settings"]["shuffle"] = True
        profile["practice_patterns"] = {"settings_candidates": candidates}
        with self.assertRaisesRegex(ValueError, "string boolean"):
            dashboard.build_data(profile)

    def test_publishing_interface_is_embedded_and_does_not_enable_network_uploads(self):
        html = analyst.render_html(self.make_profile())
        self.assertIn('id="publishing-workbench"', html)
        self.assertIn("globalThis.ElevenPublishing", html)
        self.assertIn("Local server required", html)
        self.assertIn("Only see Download?", html)
        self.assertNotIn("@@PUBLISHING_SCRIPT@@", html)
        self.assertIn("connect-src 'none'", html)

    def test_key_generation_is_primary_and_files_are_advanced(self):
        html = analyst.render_html(self.make_profile())
        self.assertIn("Generate Ball Machine Key", html)
        self.assertIn('id="cloud-copy"', html)
        advanced = html.index('<details id="publishing-advanced" class="method-note">')
        self.assertLess(html.index('id="publish-collection"'), advanced)
        self.assertLess(html.index('id="cloud-upload"'), advanced)
        self.assertGreater(html.index('id="publish-download"'), advanced)
        self.assertGreater(html.index('id="cloud-export"'), advanced)
        self.assertEqual(html.count('id="publish-collection"'), 1)

    def test_graphics_are_embedded_offline_before_dashboard_initialization(self):
        html = analyst.render_html(self.make_profile())
        self.assertNotIn("@@GRAPHICS_SCRIPT@@", html)
        self.assertIn("root.ElevenGraphics = api", html)
        self.assertLess(html.index("root.ElevenGraphics = api"), html.index("const graphics = ElevenGraphics"))
        self.assertIn('id="publish-graphic"', html)
        self.assertIn("Shot graphics", html)
        self.assertIn("not a calibrated table view", html)
        self.assertIn("connect-src 'none'", html)


if __name__ == "__main__":
    unittest.main()
