from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import analyst
import practice
import telemetry
from test_analyst import data, snapshot


def header(message, tag="MPMatch", tick=100, frame=10):
    return f"[10/24/2026 07:00:01][{tick},{frame}][{tag}]{message}"


BEFORE = "{pos:(0,1,-2),vel:(0,-3,4),rRate:(1,2,2),Rot:(0,0,0,1),Time:(0.5)}"
AFTER = "{pos:(0,1,-2),vel:(0,0,6),rRate:(0,3,4),Rot:(0,0,0,1),Time:(0)}"
LOCAL_HIT = "Sending ball hit to opponent: p:(0,1,-2)  v:(0,0,6)  r:(0,3,4)"
REMOTE_HIT = "Received ball hit from opponent: pos:(0,1,2) vel:(0,0,-5) rrate:(1,2,2)"
START = header("ShotClockMessage OnPointStarted", tick=90, frame=9)
END = header("Changing [pointRunning] from [True] to [False] from changeIndex:1007",
             tag="GameLogic", tick=200, frame=20)


def auth(user_id="1909208"):
    return header(json.dumps({"data": [{"response": "Authenticated", "user": {"Id": user_id}}]}),
                  tag="TCPSERVERCOMMUNICATIONS")


def local_hit(phase="PostHit"):
    return [
        header("Dynamic Collision...", "Physics-BallCollisions"),
        header("..preCollisionState:" + BEFORE, "Physics-BallCollisions"),
        header("..postCollisionState:" + AFTER, "Physics-BallCollisions"),
        f"  has paddleSignal with stateAtEvent{phase}:",
        header(LOCAL_HIT),
    ]


def collect(lines):
    collector = telemetry.Collector()
    for number, line in enumerate(lines, 2):
        collector.feed("test.log", number, line, "2026-10-24T07:00:01")
    collector.finish("test.log")
    return collector


def point_profile(lines, player_id="1909208"):
    collector = collect(lines)
    profile = analyst.make_profile([], [
        snapshot(((0, 0),), line=1),
        snapshot(((1, 0),), line=len(lines) + 2),
    ], player_id)
    telemetry.attach(profile, collector)
    return profile, collector


class TelemetryTests(unittest.TestCase):
    def test_ball_vectors_and_nonfinite_rejection(self):
        self.assertEqual(telemetry.ball_state(BEFORE)["velocity"], [0, -3, 4])
        for text in ("1,2", "1,2,", "1,nan,3", "1,inf,3"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                telemetry.vector(text)
        with self.assertRaises(ValueError):
            telemetry.ball_state(BEFORE.replace("0.5", "nan"))

    def test_paired_hit_features_and_ownership(self):
        profile, _ = point_profile([auth(), START, *local_hit(), END])
        point = profile["matches"][0]["observed_points"][0]
        result = point["telemetry"]
        self.assertEqual(result["status"], "bounded")
        self.assertEqual(result["paired_player_hits"], 1)
        hit = next(event for event in result["events"] if event["kind"] == "hit")
        self.assertEqual(hit["actor_id"], "1909208")
        self.assertEqual(hit["phase"], "rally")
        self.assertEqual(hit["features"]["incoming_speed_raw"], 5)
        self.assertEqual(hit["features"]["outgoing_speed_raw"], 6)
        self.assertEqual(hit["features"]["outgoing_spin_magnitude_raw"], 5)
        self.assertEqual(hit["features"]["velocity_change_raw"], [0, 3, 2])
        self.assertIsNone(hit["features"]["paddle_face_angle"])
        self.assertEqual(hit["after"]["orientation"], [0, 0, 0, 1])

    def test_serve_phase(self):
        profile, _ = point_profile([auth(), START, *local_hit("PostServiceHit"), END])
        hit = next(e for e in profile["matches"][0]["observed_points"][0]["telemetry"]["events"] if e["kind"] == "hit")
        self.assertEqual(hit["phase"], "serve")

    def test_selected_opponent_does_not_become_local_player(self):
        profile, _ = point_profile(
            [auth(), START, *local_hit(), header(REMOTE_HIT, tick=150, frame=15), END], player_id="2",
        )
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["observed_player_hits"], 1)
        self.assertEqual(result["observed_opponent_hits"], 1)
        self.assertEqual(result["paired_player_hits"], 0)

    def test_unverified_account_stays_unattributed(self):
        profile, _ = point_profile([START, *local_hit(), END])
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["observed_player_hits"], 0)
        self.assertTrue(any("unverified" in item for item in result["issues"]))
        self.assertEqual(profile["ball_telemetry"]["bounded_hit_counts"]["unattributed"], 1)

    def test_duplicate_hits_and_starts_not_counted_twice(self):
        profile, _ = point_profile([auth(), START, START, *local_hit(), header(LOCAL_HIT), END])
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["observed_hits"], 1)
        self.assertEqual(result["paired_player_hits"], 1)

    def test_free_play_outside_point_is_excluded(self):
        profile, _ = point_profile([auth(), header(LOCAL_HIT, tick=1), START, *local_hit(), END,
                                    header(LOCAL_HIT, tick=300)])
        self.assertEqual(profile["ball_telemetry"]["bounded_hit_counts"]["player"], 1)

    def test_missing_end_is_partial_and_excluded_from_aggregate(self):
        profile, _ = point_profile([auth(), START, *local_hit()])
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["events"], [])
        self.assertEqual(profile["ball_telemetry"]["player_outgoing_speed_raw"]["count"], 0)

    def test_missing_start_is_unavailable(self):
        profile, _ = point_profile([auth(), *local_hit(), END])
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["status"], "unavailable")

    def test_multiple_attempts_preserved(self):
        profile, _ = point_profile([auth(), START, *local_hit(), END,
                                    header("ShotClockMessage OnPointStarted", tick=300, frame=30),
                                    header(REMOTE_HIT, tick=350, frame=35),
                                    header("Changing [pointRunning] from [True] to [False]",
                                           "GameLogic", tick=400, frame=40)])
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["status"], "bounded_multiple_attempts")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["observed_hits"], 2)

    def test_physics_pair_requires_matching_frame_and_vectors(self):
        for lines in (
            local_hit()[:-1] + [header(LOCAL_HIT, frame=11)],
            local_hit()[:-1] + [header(LOCAL_HIT.replace("v:(0,0,6)", "v:(0,0,7)"))],
        ):
            profile, _ = point_profile([auth(), START, *lines, END])
            result = profile["matches"][0]["observed_points"][0]["telemetry"]
            self.assertEqual(result["paired_player_hits"], 0)
            self.assertEqual(result["measurement_status"], "gaps_detected")

    def test_local_collision_only_and_previous_sender_not_actor(self):
        fields = [
            " gameTime:1", " position:(0,1,0)", " velocity:(0,0,1)",
            " rotationRate:(0,0,0)", " relativeSender:SideB", " pongGameCollisionType:Net",
        ]
        collector = collect([
            header("0-0 : MyCollision:", "GameLogic"), *fields,
            header("0-0 : YourCollision:", "GameLogic"), *fields,
        ])
        self.assertEqual(len(collector.events["test.log"]), 1)
        event = collector.events["test.log"][0]
        self.assertEqual(event.relative_sender_raw, "SideB")
        self.assertIsNone(event.actor)
        self.assertEqual(event.collision_type, "Net")

    def test_malformed_raw_measurement_is_flagged_per_point(self):
        with self.assertLogs("11analyst", level="WARNING"):
            profile, _ = point_profile([
                auth(), START, header(REMOTE_HIT.replace("rrate:(1,2,2)", "rrate:(1,2,)")), END,
            ])
        result = profile["matches"][0]["observed_points"][0]["telemetry"]
        self.assertEqual(result["parse_warning_count"], 1)
        self.assertEqual(result["measurement_status"], "gaps_detected")
        self.assertEqual(result["observed_hits"], 0)

    def test_cross_file_point_not_linked(self):
        profile, collector = point_profile([auth(), START, *local_hit(), END])
        point = profile["matches"][0]["observed_points"][0]
        point["start_source"] = "different.log"
        telemetry.attach(profile, collector)
        self.assertEqual(point["telemetry"]["status"], "unavailable")
        self.assertEqual(point["telemetry"]["events"], [])

    def test_incomplete_collision_at_eof_is_explicit(self):
        with self.assertLogs("11analyst", level="WARNING"):
            collector = collect([header("0-0 : MyCollision:", "GameLogic"), " position:(1,2,3)"])
        self.assertEqual(len(collector.diagnostics["test.log"]), 1)


class PracticeAndPersistenceTests(unittest.TestCase):
    def test_three_collections_with_real_serve_seed(self):
        seed = practice.candidate_settings()[0]["settings"]["shots"]["data"]["ANLY01"]
        seed["direction"]["raw"]["verticalAngle"] = "-18.0044250488281"
        seed["speedAndRate"]["raw"]["speed"] = "7.68551206588745"
        template = {"shot": seed, "source": "default.log", "line": 7, "preset_name": "Serve"}
        profile, _ = point_profile([auth(), START, *local_hit(), END])
        patterns = practice.build(profile, template)
        self.assertEqual([c["id"] for c in patterns["collections"]], ["serve-returns", "rally-practice", "combined"])
        self.assertTrue(all(c["settings_path"] for c in patterns["collections"]))
        combined = next(c for c in patterns["settings_candidates"] if c["recipe_id"] == "combined")
        shots = list(combined["settings"]["shots"]["data"].values())
        self.assertEqual(len(shots), 3)
        self.assertEqual(shots[0]["direction"]["raw"]["verticalAngle"], "-18.0044250488281")
        self.assertEqual(shots[0]["speedAndRate"]["raw"]["speed"], "7.68551206588745")
        self.assertEqual(shots[1]["speedAndRate"]["raw"]["speed"], "10.3590488433838")
        self.assertEqual(shots[2]["speedAndRate"]["raw"]["PostDelay"], "3")
        self.assertEqual(combined["settings"]["shuffle"], "False")
        self.assertEqual(template["shot"]["speedAndRate"]["raw"]["secondsPerLaunch"], "2")

    def test_missing_serve_seed_blocks_only_serve_collections(self):
        profile, _ = point_profile([auth(), START, *local_hit(), END])
        patterns = practice.build(profile)
        states = {c["id"]: c["status"] for c in patterns["collections"]}
        self.assertEqual(states["serve-returns"], "missing_serve_template")
        self.assertEqual(states["combined"], "missing_serve_template")
        self.assertEqual(states["rally-practice"], "candidate_requires_in_game_validation")
        self.assertNotIn("serve-returns", [c["recipe_id"] for c in patterns["settings_candidates"]])

    def test_stale_serve_candidates_removed_without_touching_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            seed = practice.candidate_settings()[0]["settings"]["shots"]["data"]["ANLY01"]
            template = {"shot": seed, "source": "default.log", "line": 7, "preset_name": "Serve"}
            profile, _ = point_profile([auth(), START, *local_hit(), END])
            profile["practice_patterns"] = practice.build(profile, template)
            analyst.persist(output, profile, [])
            self.assertTrue((output / "ball_machine" / "combined.candidate.json").exists())
            other = output / "ball_machine" / "my-settings.json"
            other.write_text("preserve", encoding="utf-8")
            stale_plan = output / "ball_machine" / "plan-shot-landing.candidate.json"
            stale_plan.write_text("{}", encoding="utf-8")
            profile["practice_patterns"] = practice.build(profile)
            analyst.persist(output, profile, [])
            self.assertFalse((output / "ball_machine" / "combined.candidate.json").exists())
            self.assertFalse((output / "ball_machine" / "serve-returns.candidate.json").exists())
            self.assertTrue((output / "ball_machine" / "rally-practice.candidate.json").exists())
            self.assertFalse(stale_plan.exists())
            self.assertEqual(other.read_text(encoding="utf-8"), "preserve")

    def test_default_template_extraction_with_provenance(self):
        seed = practice.candidate_settings()[0]["settings"]["shots"]["data"]["ANLY01"]
        seed["DataName"] = "Serve"
        seed["Description"] = "Original coaching description must not be copied."
        del seed["speedAndRate"]["raw"]["PostDelay"]
        del seed["speedAndRate"]["spread"]["PostDelay"]
        settings = practice.settings_root({"SOURCE": seed})
        collector = practice.TemplateCollector()
        collector.feed("settings.log", 5, "Loading Default Settings JSON for object:BallLauncherDeviceSettings",
                       "2026-10-24T08:00:00", True)
        collector.feed("settings.log", 6, json.dumps(settings), None, False)
        collector.finish("settings.log")
        result = collector.latest_serve()
        self.assertEqual(result["source"], "settings.log")
        self.assertEqual(result["line"], 5)
        self.assertEqual(result["preset_id"], "SOURCE")
        self.assertEqual(result["shot"]["speedAndRate"]["raw"]["PostDelay"], "0")
        self.assertNotIn("Original coaching", result["shot"]["Description"])

    def test_invalid_default_template_is_diagnosed(self):
        collector = practice.TemplateCollector()
        collector.feed("settings.log", 5, "Loading Default Settings JSON for object:BallLauncherDeviceSettings",
                       "2026-10-24T08:00:00", True)
        collector.feed("settings.log", 6, "{broken", None, False)
        with self.assertLogs("11analyst", level="WARNING"):
            collector.finish("settings.log")
        self.assertIsNone(collector.latest_serve())
        self.assertEqual(len(collector.diagnostics["settings.log"]), 1)

    def test_candidate_settings_preserve_strings_and_user_seed(self):
        candidates = practice.candidate_settings()
        self.assertEqual(len(candidates), 3)
        self.assertEqual([len(c["settings"]["shots"]["data"]) for c in candidates], [1, 2, 1])
        for candidate in candidates:
            practice.validate_settings(candidate["settings"])
            self.assertFalse(candidate["tested_in_game"])
            self.assertEqual(candidate["settings"]["ballCount"], "5")
            for shot in candidate["settings"]["shots"]["data"].values():
                self.assertEqual(shot["isActive"], "True")
                self.assertEqual(shot["speedAndRate"]["raw"]["speed"], "10.3590488433838")
                self.assertEqual(shot["speedAndRate"]["raw"]["secondsPerLaunch"], "2")
                self.assertEqual(shot["speedAndRate"]["raw"]["PostDelay"], "0")
                self.assertEqual(shot["spin"]["raw"]["topBottom"], "30.1296539306641")
                self.assertNotIn("forehand counter drive", shot["Description"])
        directions = [s["direction"]["raw"]["horizontalAngle"]
                      for s in candidates[1]["settings"]["shots"]["data"].values()]
        self.assertEqual(directions, ["-21.9228744506836", "-13.9228744506836"])
        self.assertEqual(next(iter(candidates[2]["settings"]["shots"]["data"].values()))["direction"]["spread"]["horizontalAngle"], "1.5")

    def test_candidate_validation_rejects_invalid_values(self):
        for bad_value in (True, 2, "NaN", "Infinity", "0", "-1"):
            settings = practice.candidate_settings()[0]["settings"]
            shot = next(iter(settings["shots"]["data"].values()))
            shot["speedAndRate"]["raw"]["secondsPerLaunch"] = bad_value
            with self.subTest(bad_value=bad_value), self.assertRaises(ValueError):
                practice.validate_settings(settings)
        settings = practice.candidate_settings()[0]["settings"]
        bad = deepcopy(settings)
        bad["shots"] = None
        with self.assertRaises(ValueError):
            practice.validate_settings(bad)
        next(iter(settings["shots"]["data"].values()))["direction"]["spread"]["horizontalAngle"] = "-1"
        with self.assertRaises(ValueError):
            practice.validate_settings(settings)

    def test_original_recipes_not_importable_and_sources_cited(self):
        profile, _ = point_profile([auth(), START, *local_hit(), END])
        recipes = practice.build(profile)
        self.assertFalse(recipes["game_importable"])
        self.assertEqual(len(recipes["recipes"]), 3)
        self.assertEqual(len(recipes["methodology_sources"]), 2)
        self.assertEqual(recipes["raw_contact_reference_samples"], [])  # Incomplete match.
        self.assertTrue(all(recipe["method_sources"] for recipe in recipes["recipes"]))

    def test_completed_rally_contacts_only_in_reference_samples(self):
        profile, _ = point_profile([auth(), START, *local_hit(), END])
        profile["matches"][0]["status"] = "completed"
        recipes = practice.build(profile)
        self.assertEqual(len(recipes["raw_contact_reference_samples"]), 3)
        hit = next(e for e in profile["matches"][0]["observed_points"][0]["telemetry"]["events"] if e["kind"] == "hit")
        hit["phase"] = "serve"
        self.assertEqual(practice.build(profile)["raw_contact_reference_samples"], [])

    def test_schema_one_migration_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            text = "\n".join([
                header("Writing state:"),
                " FullSnapshot reads " + json.dumps(data(RoundScores=[[0, 0]])),
                auth(), START, *local_hit(), END,
                header("Writing state:", tick=210, frame=21),
                " FullSnapshot reads " + json.dumps(data(RoundScores=[[1, 0]])),
            ])
            (logs / "game.log").write_text(text, encoding="utf-8")
            output = root / "output"
            output.mkdir()
            with closing(sqlite3.connect(output / "analyst.sqlite3")) as connection:
                connection.execute("PRAGMA user_version=1")
            for _ in range(2):
                profile = analyst.analyze(logs, output)
                with closing(sqlite3.connect(output / "analyst.sqlite3")) as connection:
                    self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                    rows = connection.execute("SELECT data_json FROM points").fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(json.loads(rows[0][0])["telemetry"]["paired_player_hits"], 1)
                self.assertEqual(json.loads((output / "practice_patterns.json").read_text(encoding="utf-8")),
                                 profile["practice_patterns"])
                report = (output / "report.html").read_text(encoding="utf-8")
                self.assertIn("Ball and contact measurements", report)
                self.assertIn("Ball-machine practice patterns", report)
                self.assertIn("Paired incoming/outgoing", report)
                self.assertEqual(profile["sources"][0]["local_player_id"], "1909208")
                for candidate in profile["practice_patterns"]["settings_candidates"]:
                    path = output / "ball_machine" / f"{candidate['recipe_id']}.candidate.json"
                    settings = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(settings, candidate["settings"])
                    practice.validate_settings(settings)


if __name__ == "__main__":
    unittest.main()
