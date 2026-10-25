from dataclasses import replace
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import analyst


def data(**changes):
    value = {
        "PlayerIds": [1909208, 2], "PlayerNames": ["DigitalByooki", "Opponent"],
        "PlayerELOs": [2100, 2200], "RoundScores": [], "MatchId": "123",
        "Ranked": "False", "BestOf": "3", "MatchWinner": "0", "LastPointReason": "NULL",
    }
    value.update(changes)
    return value


def snapshot(scores=(), winner="0", line=1, **changes):
    values = data(RoundScores=[list(s) for s in scores], MatchWinner=winner)
    values.update(changes)
    return analyst.decode_snapshot(
        values,
        "2026-10-24T07:00:00", "test.log", line,
    )


def log_text(records):
    return '[10/24/2026 07:00:00]Beginning of log "ALL"\n' + "".join(
        "[10/24/2026 07:00:01][1,1][MPMatch]Writing state:\n"
        "    FullSnapshot reads " + json.dumps(record) + "\n" for record in records
    )


class SchemaTests(unittest.TestCase):
    def test_strict_snapshot_validation(self):
        for changes in (
            {"Ranked": "maybe"}, {"RoundScores": [[-1, 0]]},
            {"RoundScores": [[1.5, 0]]}, {"PlayerIds": [2, 2]},
            {"MatchWinner": "999"}, {"BestOf": "2"}, {"PlayerNames": ["one"]},
            {"PlayerELOs": [True, 100]}, {"RoundScores": "not scores"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                snapshot(**changes)

    def test_score_winner(self):
        for scores, expected in (((11, 9), 0), ((10, 11), None), ((15, 17), 1),
                                 ((12, 3), None), ((10, 10), None)):
            self.assertEqual(analyst.game_winner(scores), expected)

    def test_single_point_and_game_boundaries(self):
        self.assertEqual(analyst.single_point(((2, 3),), ((3, 3),)), (0, 0))
        self.assertEqual(analyst.single_point(((10, 9),), ((11, 9), (0, 0))), (0, 0))
        self.assertEqual(analyst.single_point((), ((0, 1),)), (0, 1))
        self.assertIsNone(analyst.single_point(((1, 1),), ((3, 1),)))
        self.assertIsNone(analyst.single_point(((3, 1),), ((2, 1),)))
        self.assertIsNone(analyst.single_point(((11, 9),), ((12, 9),)))
        self.assertIsNone(analyst.single_point(((1, 0),), ((2, 0), (0, 0))))


class MatchTests(unittest.TestCase):
    def test_complete_match_and_player_second(self):
        s = snapshot(((11, 5), (11, 8)), winner="2", PlayerIds=[2, 1909208])
        result = analyst.summarize_match([s], analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["won"])
        self.assertEqual(result["scores"], [[5, 11], [8, 11]])
        self.assertEqual(result["points_won"], 13)
        self.assertEqual(result["opponent_id"], "2")

    def test_incomplete_not_counted_as_loss(self):
        result = analyst.summarize_match([snapshot(((4, 5),))], analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["won"])
        stats = analyst.result_stats([result])
        self.assertEqual(stats["matches"], 0)
        self.assertIsNone(stats["win_rate"])

    def test_conflicting_finals_excluded(self):
        a = snapshot(((11, 5), (11, 8)), winner="1909208")
        b = snapshot(((5, 11), (8, 11)), winner="2", line=2)
        result = analyst.summarize_match([a, b], analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["status"], "inconsistent")
        self.assertTrue(result["issues"])

    def test_inconsistent_winner_and_scores(self):
        result = analyst.summarize_match(
            [snapshot(((3, 1),), winner="1909208")], analyst.DEFAULT_PLAYER_ID,
        )
        self.assertEqual(result["status"], "inconsistent")

    def test_deduplication_and_gaps(self):
        snapshots = [
            snapshot(((0, 0),), line=1), snapshot(((1, 0),), line=2),
            snapshot(((1, 0),), line=3), snapshot(((3, 0),), line=4),
            snapshot(((3, 1),), line=5),
        ]
        result = analyst.summarize_match(snapshots, analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(len(result["observed_points"]), 2)
        self.assertEqual(result["score_transition_gaps"], 1)
        self.assertEqual(result["point_coverage"], 0.5)

    def test_changed_metadata_excluded(self):
        a = snapshot()
        b = replace(snapshot(((1, 0),), line=2), ranked=True)
        result = analyst.summarize_match([a, b], analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["status"], "inconsistent")

    def test_full_point_coverage_including_round_boundary(self):
        records = [snapshot(line=1), snapshot(((0, 0),), line=2)]
        for score in range(1, 12):
            scores = ((score, 0),) if score < 11 else ((11, 0), (0, 0))
            records.append(snapshot(scores, line=len(records) + 1))
        for score in range(1, 12):
            records.append(snapshot(
                ((11, 0), (score, 0)), line=len(records) + 1,
                winner="1909208" if score == 11 else "0",
            ))
        records.append(replace(records[-1], source="z-copy.log"))
        result = analyst.summarize_match(records, analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["observed_points"]), 22)
        self.assertEqual(result["score_transition_gaps"], 0)
        self.assertEqual(result["point_coverage"], 1.0)

    def test_best_of_five(self):
        s = snapshot(((11, 5), (2, 11), (11, 8), (11, 9)),
                     winner="1909208", BestOf="5")
        result = analyst.summarize_match([s], analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["games_won"], 3)

    def test_profile_modes_and_strength_boundary(self):
        a = snapshot(((11, 5), (11, 8)), winner="1909208")
        b = snapshot(((5, 11), (8, 11)), winner="2", MatchId="124",
                     Ranked="True", PlayerELOs=[2100, 2201])
        result = analyst.make_profile([], [a, b], analyst.DEFAULT_PLAYER_ID)
        self.assertEqual(result["summary"]["wins"], 1)
        self.assertEqual(result["summary"]["losses"], 1)
        self.assertEqual(result["by_mode"]["ranked"]["losses"], 1)
        self.assertEqual(result["by_opponent_strength"]["similar"]["wins"], 1)
        self.assertEqual(result["by_opponent_strength"]["higher"]["losses"], 1)


class PipelineTests(unittest.TestCase):
    def test_pipeline_repeatable_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            records = [data(), data(RoundScores=[[0, 0]]),
                       data(RoundScores=[[1, 0]]),
                       data(RoundScores=[[11, 5], [11, 8]], MatchWinner="1909208")]
            text = log_text(records)
            (logs / "game.log").write_text(text, encoding="utf-8")
            (logs / "copy.log").write_text(text, encoding="utf-8")
            (logs / "empty.log").write_text('[10/24/2026 07:00:00]Beginning of log\n', encoding="utf-8")
            # A server record with the same shape must not become a local match.
            (logs / "friend.log").write_text(
                '[10/24/2026 07:00:00][1,1][TCPSERVERCOMMUNICATIONS]' +
                json.dumps(data(MatchId="999")) + "\n", encoding="utf-8",
            )
            output = root / "output"
            for _ in range(2):
                profile = analyst.analyze(logs, output)
                self.assertEqual(profile["summary"]["matches"], 1)
                self.assertEqual(profile["data_quality"]["duplicate_files"], 1)
                self.assertEqual(profile["data_quality"]["observed_single_point_transitions"], 1)
                with closing(sqlite3.connect(output / "analyst.sqlite3")) as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 4)
                    stored = json.loads(connection.execute("SELECT data_json FROM profiles").fetchone()[0])
                self.assertEqual(stored, json.loads((output / "profile.json").read_text(encoding="utf-8")))
                self.assertTrue((output / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>"))

    def test_malformed_snapshot_reported_and_other_player_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.log"
            path.write_text(log_text([
                data(PlayerIds=[7, 8]), data(RoundScores=[[-1, 0]]), data(),
            ]), encoding="utf-8")
            with self.assertLogs("11analyst", level="WARNING"):
                source, snapshots = analyst.read_source(path, analyst.DEFAULT_PLAYER_ID, {})
            self.assertEqual(source.status, "parse_warnings")
            self.assertEqual(len(source.diagnostics), 1)
            self.assertEqual(len(snapshots), 1)

    def test_no_player_data_preserves_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "empty.log").write_text("header\n", encoding="utf-8")
            output = root / "output"
            output.mkdir()
            report = output / "report.html"
            report.write_text("existing", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No valid local match snapshots"):
                analyst.analyze(root, output)
            self.assertEqual(report.read_text(encoding="utf-8"), "existing")

    def test_html_escapes_untrusted_names(self):
        s = snapshot(PlayerNames=["DigitalByooki", "<script>alert(1)</script>"])
        html = analyst.render_html(analyst.make_profile([], [s], analyst.DEFAULT_PLAYER_ID))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_missing_and_malformed_json_are_diagnosed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.log"
            path.write_text(
                'FullSnapshot reads {}\n'
                '[10/24/2026 07:00:00][1,1][MPMatch]Writing state:\n'
                'FullSnapshot reads {"broken"\n'
                'FullSnapshot reads {}\n', encoding="utf-8",
            )
            with self.assertLogs("11analyst", level="WARNING"):
                source, snapshots = analyst.read_source(path, analyst.DEFAULT_PLAYER_ID, {})
            self.assertEqual(source.snapshots, 3)
            self.assertEqual(len(source.diagnostics), 3)
            self.assertEqual(snapshots, [])

    def test_unknown_database_version_preserves_data(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with closing(sqlite3.connect(output / "analyst.sqlite3")) as connection:
                connection.execute("PRAGMA user_version = 999")
            profile = analyst.make_profile([], [snapshot()], analyst.DEFAULT_PLAYER_ID)
            with self.assertRaisesRegex(ValueError, "Unsupported database"):
                analyst.persist(output, profile, [])
            self.assertFalse((output / "profile.json").exists())
            with closing(sqlite3.connect(output / "analyst.sqlite3")) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 999)


if __name__ == "__main__":
    unittest.main()
