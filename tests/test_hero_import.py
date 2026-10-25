from copy import deepcopy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import analyst
import dashboard
import hero_import as hero
import loss_analysis
from test_analyst import snapshot


MATCH = "00000000-0000-4000-8000-000000000001"


def row(index=1, player=1909208, **changes):
    return {
        "id": f"shot-{index}", "pointId": "point-1", "playerId": player,
        "beginAt": "2026-10-22T00:25:36.555123456Z", "contactType": "Hit",
        "playerIsHome": player != 1909208,
        "posX": 0.2, "posY": 1.4, "posZ": -1.9, "velX": 0.7, "velY": 2.2, "velZ": 0.1,
        "rrateX": -5313.3, "rrateY": 7701.6, "rrateZ": -5056.5, "rrateSqrt": 29.5,
        "spinDirection": "BottomLeft", "shotType": "Serve", "direction": "Mid", "distance": "Long",
        "height": None, "isServe": True, "isSuccess": False, "rallyCount": 0, **changes,
    }


def entry():
    return {"path": Path("synthetic.json"), "provider_match_id": MATCH,
            "source_url": f"https://11hero.com/matches/{MATCH}", "retrieved_at": None,
            "participant_ids": ["1909208", "2"], "discovery_name": None,
            "metadata": {"notes": "Synthetic score mismatch; do not reconcile automatically"}}


def parse(rows):
    return hero.parse_export(json.dumps(rows).encode(), entry(), "1909208")


class HeroParserTests(unittest.TestCase):
    def test_preserves_provider_fields_opponents_tosses_and_precision_without_inference(self):
        rows = [row(extra={"future": [1, "retained"]}),
                row(2, 2, contactType="Toss", shotType="Toss", isServe=True)]
        result = parse(rows)
        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["counts"]["hits"], 1)
        self.assertEqual(result["counts"]["tosses"], 1)
        self.assertEqual(result["counts"]["opponent_rows"], 1)
        self.assertEqual(result["counts"]["point_groups"], 1)
        for index, record in enumerate(result["records"]):
            self.assertEqual(record["provider_fields"], rows[index])
            self.assertEqual(record["begin_at"], rows[index]["beginAt"])
            self.assertIsNone(record["analyst_labels"])
            self.assertIsNone(record["return_outcome"])
            self.assertIsNone(record["point_outcome"])
            self.assertFalse(record["machine_key_eligible"])
            self.assertNotIn("raw_reason", record)
            self.assertNotIn("engine_tick", record)
        self.assertEqual(result["records"][0]["player_id"], "1909208")
        self.assertEqual(result["records"][0]["numeric_vectors"]["rrate"], [-5313.3, 7701.6, -5056.5])
        self.assertFalse(result["included_in_local_analysis"])

    def test_required_identifiers_timezone_membership_booleans_and_numbers(self):
        for change in [
            {"id": None}, {"pointId": ""}, {"playerId": True}, {"playerId": 3}, {"contactType": None},
            {"beginAt": "2026-10-22T00:25:36"}, {"beginAt": "2026-99-99T00:25:36Z"},
            {"isSuccess": "false"}, {"isServe": 1}, {"playerIsHome": 0},
            {"velX": "7.0"}, {"posX": False}, {"rrateSqrt": float("nan")},
            {"velX": float("inf")}, {"rallyCount": 0.5}, {"rallyCount": -1},
            {"direction": 3}, {"height": []}, {"unknown": {"nested": float("inf")}},
            {"bmSpeed": 10 ** 500},
        ]:
            with self.subTest(change=change):
                result = parse([row(**change)])
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(len(result["rejected_rows"]), 1)
                self.assertEqual(result["records"], [])

    def test_unknown_enums_and_missing_optional_values_remain_unknown(self):
        source = {key: row()[key] for key in ("id", "pointId", "playerId", "beginAt", "contactType")}
        source.update(contactType="FutureContact", shotType="FutureShot", spinDirection="FutureSpin",
                      direction=None, height="FutureHeight", isSuccess=None)
        result = parse([source])
        self.assertEqual(result["status"], "imported_with_diagnostics")
        record = result["records"][0]
        self.assertEqual(record["contact_type"], "FutureContact")
        self.assertIsNone(record["numeric_vectors"]["vel"])
        self.assertIsNone(record["provider_annotations"]["isSuccess"])
        self.assertIsNone(record["provider_annotations"]["isWinningShot"])
        self.assertEqual(result["counts"]["other_contacts"], 1)
        self.assertGreaterEqual(len(result["diagnostics"]), 4)

    def test_duplicate_ids_deduplicate_only_identical_rows_and_quarantine_all_conflicts(self):
        result = parse([row(), row()])
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(len(result["records"]), 1)
        result = parse([row(), row(isSuccess=True), row(2)])
        self.assertEqual([record["id"] for record in result["records"]], ["shot-2"])
        self.assertEqual(len(result["rejected_rows"]), 2)
        result = parse([row(), row(isSuccess="invalid")])
        self.assertEqual(len(result["rejected_rows"]), 2)
        self.assertEqual(result["records"], [])

    def test_bad_roots_duplicate_json_keys_and_empty_exports_are_rejected(self):
        for raw in (b'{}', b'null', b'"text"', b'[', b'\xff',
                    b'[{"id":"one","id":"two"}]', b'[]'):
            with self.subTest(raw=raw):
                result = hero.parse_export(raw, entry(), "1909208")
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())

    def test_multiple_participants_and_home_contradictions_are_explicit(self):
        metadata = entry()
        metadata["participant_ids"] = None
        result = hero.parse_export(json.dumps([row(), row(2, 2), row(3, 3)]).encode(), metadata, "1909208")
        self.assertEqual(result["status"], "rejected")
        result = parse([row(), row(2, playerIsHome=True)])
        self.assertTrue(any("Contradictory" in issue["message"] for issue in result["diagnostics"]))

    def test_match_namespace_keeps_same_shot_ids_separate(self):
        a = parse([row()])
        metadata = entry()
        metadata["provider_match_id"] = "00000000-0000-4000-8000-000000000002"
        b = hero.parse_export(json.dumps([row()]).encode(), metadata, "1909208")
        self.assertNotEqual(a["records"][0]["provider_key"], b["records"][0]["provider_key"])
        self.assertNotEqual(a["records"][0]["point_key"], b["records"][0]["point_key"])


class HeroArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.source = self.root / "shots.json"
        self.source.write_text(json.dumps([row(), row(2, 2, contactType="Toss")]))
        self.manifest = self.root / "manifest.json"
        self.manifest_value = {
            "format": "11analyst.hero-manifest", "version": 1, "player_id": "1909208",
            "matches": [{**{key: value for key, value in entry().items() if key != "path"}, "file": "shots.json"}],
        }
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.manifest_value))

    def run_import(self):
        return hero.import_manifest(self.manifest, self.output, "1909208")

    def test_idempotency_raw_bytes_metadata_revisions_and_hero_only_report(self):
        first = self.run_import()
        self.assertEqual(first["imported_revisions"], 1)
        original = hero.load_evidence(self.output, "1909208")
        self.assertEqual(self.run_import()["unchanged_files"], 1)
        self.assertEqual(hero.load_evidence(self.output, "1909208"), original)
        with closing(sqlite3.connect(self.output / "hero_imports.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT raw_json FROM hero_revisions").fetchone()[0], self.source.read_bytes())
        self.source.write_text(json.dumps([row(isSuccess=True), row(2, 2)]))
        self.run_import()
        evidence = hero.load_evidence(self.output, "1909208")
        self.assertEqual(len(evidence["revisions"]), 2)
        self.assertEqual(evidence["revisions"][0], original["revisions"][0])
        self.assertEqual(evidence["revisions"][1]["revision_number"], 2)
        self.manifest_value["matches"][0]["metadata"]["notes"] = "Updated declaration"
        self.write_manifest()
        self.run_import()
        self.assertEqual(len(hero.load_evidence(self.output, "1909208")["revisions"]), 3)
        profile = json.loads((self.output / "profile.json").read_text())
        self.assertEqual(profile["matches"], [])
        self.assertEqual(profile["loss_analysis"]["observed_lost_points"], 0)
        self.assertIn('id="hero-evidence"', (self.output / "report.html").read_text())

    def test_existing_profile_local_database_and_rerun_contracts_are_preserved(self):
        snapshots = [snapshot()]
        profile = analyst.make_profile([], snapshots, "1909208")
        loss_analysis.attach(profile)
        analyst.persist(self.output, profile, snapshots)
        protected = {name: (self.output / name).read_bytes() for name in ("profile.json", "analyst.sqlite3", "shot_catalogue.json")}
        self.run_import()
        for name, raw in protected.items():
            self.assertEqual((self.output / name).read_bytes(), raw)
        before = (self.output / "hero_imports.sqlite3").read_bytes()
        analyst.persist(self.output, profile, snapshots)
        self.assertEqual((self.output / "hero_imports.sqlite3").read_bytes(), before)
        html = (self.output / "report.html").read_text()
        self.assertIn('"source_kind":"hero_export"', html)
        with closing(sqlite3.connect(self.output / "analyst.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 1)

    def test_rejected_input_is_archived_exactly_and_retry_keeps_diagnostics(self):
        raw = b'[{"id":"broken","posX":NaN}]'
        self.source.write_bytes(raw)
        with self.assertLogs("11analyst.hero", level="WARNING"):
            result = self.run_import()
        self.assertEqual(result["failed_files"], 1)
        with closing(sqlite3.connect(self.output / "hero_imports.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT raw_json FROM hero_revisions").fetchone()[0], raw)
        with self.assertLogs("11analyst.hero", level="WARNING"):
            again = self.run_import()
        self.assertEqual(again["unchanged_files"], 1)
        self.assertEqual(again["failed_files"], 1)

    def test_missing_file_reports_failure_but_other_files_import(self):
        self.manifest_value["matches"].append({**self.manifest_value["matches"][0], "file": "missing.json"})
        self.write_manifest()
        with self.assertLogs("11analyst.hero", level="ERROR"):
            result = self.run_import()
        self.assertEqual(result["failed_files"], 1)
        self.assertEqual(result["imported_revisions"], 1)

    def test_manifest_validation_and_player_isolation(self):
        for change in ({"version": True}, {"player_id": "2"}, {"matches": []}, {"unrecognized": "metadata"}):
            with self.subTest(root_change=change):
                self.manifest.write_text(json.dumps({**self.manifest_value, **change}))
                with self.assertRaises(ValueError):
                    self.run_import()
        for change in ({"provider_match_id": "not-uuid"}, {"source_url": "https://other.invalid"},
                       {"participant_ids": ["2", "3"]}, {"participant_ids": ["1909208", "1909208"]},
                       {"retrieved_at": "2026-10-25"}, {"metadata": []}, {"file": None},
                       {"discovery_name": False}, {"unexpected": True}):
            with self.subTest(change=change):
                value = deepcopy(self.manifest_value)
                value["matches"][0].update(change)
                self.manifest.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    self.run_import()
        self.write_manifest()
        self.run_import()
        self.assertEqual(hero.load_evidence(self.output, "2")["revisions"], [])
        profile_path = self.output / "profile.json"
        other = json.loads(profile_path.read_text())
        other["player"]["id"] = "2"
        profile_path.write_text(json.dumps(other))
        with self.assertRaisesRegex(ValueError, "another player"):
            self.run_import()

    def test_dashboard_escapes_provider_fields_and_preserves_local_scopes(self):
        self.source.write_text(json.dumps([row(shotType='</script><img src=x onerror="alert(1)">')]))
        with self.assertLogs("11analyst.hero", level="WARNING"):
            self.run_import()
        evidence = hero.load_evidence(self.output, "1909208")
        profile = json.loads((self.output / "profile.json").read_text())
        before = deepcopy(profile)
        html = dashboard.render(profile, hero_evidence=evidence)
        self.assertNotIn('</script><img', html)
        self.assertIn("connect-src 'none'", html)
        self.assertEqual(profile, before)
        self.assertEqual(dashboard.build_data(profile)["views"]["all"]["loss_analysis"]["observed_lost_points"], 0)
        evidence["player_id"] = "2"
        with self.assertRaisesRegex(ValueError, "another player"):
            dashboard.render(profile, hero_evidence=evidence)
