from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import analyst
import loss_analysis
import shot_catalogue
from test_loss_analysis import event, point, match, profile


class ShotCatalogueTests(unittest.TestCase):
    def test_starter_categories_are_named_unique_and_not_diagnoses(self):
        catalogue = shot_catalogue.build()
        self.assertEqual(len(catalogue["categories"]), 12)
        self.assertEqual(len({category["id"] for category in catalogue["categories"]}), 12)
        first = catalogue["categories"][0]
        self.assertEqual(first["name"], "Long sidespin serve to the backhand side (sidespin direction unspecified)")
        self.assertTrue(first["milestone_example"])
        for category in catalogue["categories"]:
            self.assertEqual(category["evidence_status"], "not_classified")
            self.assertIsNone(category["observed_attempts"])
            self.assertIsNone(category["observed_failures"])
            self.assertIsNone(category["observed_matches"])
            self.assertFalse(category["machine_key_eligible"])
            self.assertTrue(category["counter_play"])
            self.assertTrue(category["recognition"])
            self.assertTrue(category["success_criteria"])

    def test_invalid_context_lengths_directions_and_fields_are_rejected(self):
        original = shot_catalogue.build()["categories"][0]["facets"]
        for change in ({"length": "deep"}, {"spin": "top"}, {"direction": "not_applicable"},
                       {"pace": "enormous"}, {"placement": None}, {"arbitrary": "value"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                shot_catalogue.describe({**original, **change})
        with self.assertRaises(ValueError):
            shot_catalogue.describe({})

    def test_unknown_not_zero_and_direction_qualifier_explicit(self):
        first = shot_catalogue.build()["categories"][0]["facets"]
        cw = shot_catalogue.describe({**first, "direction": "clockwise"})
        self.assertIn("clockwise viewed from above", cw["name"])
        self.assertNotIn("left sidespin", cw["name"])
        unknown = shot_catalogue.describe({**first, "length": "unknown", "placement": "unknown",
                                          "spin": "unknown", "direction": "not_applicable"})
        self.assertIn("unclassified", unknown["name"])
        self.assertNotIn("negligible", unknown["name"])

    def test_catalogue_is_fresh_and_does_not_label_broad_serve_evidence(self):
        first = shot_catalogue.build()
        original = deepcopy(first)
        first["categories"][0]["facets"]["pace"] = "fast"
        first["facets"]["spin"]["values"][0]["definition"] = "changed"
        self.assertEqual(shot_catalogue.build(), original)
        result = profile([match(1, [point(events=[event("2", "serve")])])])
        loss_analysis.attach(result)
        self.assertEqual(result["serve_reception_pilot"]["receiving_attempts"], 1)
        self.assertIsNone(result["shot_catalogue"]["categories"][0]["observed_attempts"])

    def test_catalogue_persists_with_empty_log_profile(self):
        result = analyst.make_profile([], [], analyst.DEFAULT_PLAYER_ID)
        loss_analysis.attach(result)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            analyst.persist(output, result, [])
            self.assertEqual(json.loads((output / "shot_catalogue.json").read_text()), result["shot_catalogue"])
            self.assertEqual(json.loads((output / "profile.json").read_text())["shot_catalogue"], result["shot_catalogue"])
            self.assertIn('id="shot-catalogue"', (output / "report.html").read_text())
