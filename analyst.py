"""Local, standard-library-only Eleven Table Tennis log analysis."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
from html import escape
import json
import logging
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

import practice
import telemetry
import loss_analysis
import dashboard

LOG = logging.getLogger("11analyst")
DEFAULT_PLAYER_ID = "1909208"
STAMP = re.compile(r"^\[(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\]")
TAG = re.compile(r"^\[[^\]]+\]\[[^\]]+\]\[([^\]]+)\]")
SNAPSHOT_MARKER = "FullSnapshot reads "
SCHEMA_VERSION = 2


@dataclass
class Source:
    path: str
    sha256: str
    size_bytes: int
    lines: int = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    snapshots: int = 0
    player_snapshots: int = 0
    status: str = "no_match_snapshots"
    duplicate_of: str | None = None
    categories: dict[str, int] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    telemetry_diagnostics: list[str] = field(default_factory=list)
    local_player_id: str | None = None
    ball_machine_diagnostics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Snapshot:
    match_id: str
    timestamp: str
    source: str
    line: int
    player_ids: tuple[str, str]
    player_names: tuple[str, str]
    elos: tuple[int, int]
    scores: tuple[tuple[int, int], ...]
    ranked: bool
    best_of: int
    winner: str | None
    reason: str


def integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ValueError(f"{name} must be a nonnegative integer")
    return int(value)


def boolean(value: Any, name: str) -> bool:
    if value is True or value == "True":
        return True
    if value is False or value == "False":
        return False
    raise ValueError(f"{name} must be True or False")


def pair(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must contain two values")
    return value


def decode_snapshot(data: Any, timestamp: str, source: str, line: int) -> Snapshot:
    if not isinstance(data, dict):
        raise ValueError("snapshot must be a JSON object")
    ids = tuple(str(integer(v, "PlayerIds")) for v in pair(data["PlayerIds"], "PlayerIds"))
    if len(set(ids)) != 2 or "0" in ids:
        raise ValueError("PlayerIds must contain two distinct nonzero IDs")
    names = pair(data["PlayerNames"], "PlayerNames")
    if not all(isinstance(v, str) and v for v in names):
        raise ValueError("PlayerNames must contain nonempty strings")
    elos = tuple(integer(v, "PlayerELOs") for v in pair(data["PlayerELOs"], "PlayerELOs"))
    raw_scores = data["RoundScores"]
    if not isinstance(raw_scores, list):
        raise ValueError("RoundScores must be an array")
    scores = tuple(
        tuple(integer(v, "RoundScores") for v in pair(score, "RoundScores"))
        for score in raw_scores
    )
    best_of = integer(data["BestOf"], "BestOf")
    if best_of < 1 or best_of % 2 != 1 or len(scores) > best_of:
        raise ValueError("invalid BestOf or too many rounds")
    match_id = str(integer(data["MatchId"], "MatchId"))
    if match_id == "0":
        raise ValueError("MatchId must be nonzero")
    winner = str(data["MatchWinner"])
    if winner in ("0", "-1", "NULL", "None"):
        winner = None
    elif winner not in ids:
        raise ValueError("MatchWinner is not a participant")
    reason = data["LastPointReason"]
    if not isinstance(reason, str):
        raise ValueError("LastPointReason must be a string")
    return Snapshot(
        match_id, timestamp, source, line, ids, tuple(names), elos, scores,
        boolean(data["Ranked"], "Ranked"), best_of, winner, reason,
    )


def read_source(
    path: Path, player_id: str, seen: dict[str, str], collector: telemetry.Collector | None = None,
    templates: practice.TemplateCollector | None = None,
) -> tuple[Source, list[Snapshot]]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    source = Source(str(path.resolve()), digest, path.stat().st_size)
    if digest in seen:
        source.status = "duplicate_file"
        source.duplicate_of = seen[digest]
        return source, []
    seen[digest] = source.path
    snapshots = []
    categories: Counter[str] = Counter()
    timestamp = None
    with path.open(encoding="utf-8-sig") as stream:
        for number, text in enumerate(stream, 1):
            source.lines = number
            stamp = STAMP.match(text)
            if stamp:
                timestamp = datetime.strptime(stamp[1], "%m/%d/%Y %H:%M:%S").isoformat()
                source.first_timestamp = source.first_timestamp or timestamp
                source.last_timestamp = timestamp
            tag = TAG.match(text)
            if tag:
                categories[tag[1]] += 1
            if collector is not None:
                collector.feed(source.path, number, text.rstrip("\r\n"), timestamp)
            if templates is not None:
                templates.feed(source.path, number, text, timestamp, stamp is not None)
            # Only local full snapshots, never server friend-list JSON or arbitrary match objects.
            if not text.lstrip().startswith(SNAPSHOT_MARKER):
                continue
            source.snapshots += 1
            try:
                if timestamp is None:
                    raise ValueError("snapshot has no preceding timestamp")
                data = json.loads(text.lstrip()[len(SNAPSHOT_MARKER):])
                snapshot = decode_snapshot(data, timestamp, source.path, number)
            except (ValueError, KeyError, TypeError) as exc:
                message = f"line {number}: invalid snapshot: {exc}"
                source.diagnostics.append(message)
                LOG.warning("%s: %s", path.name, message)
                continue
            if player_id in snapshot.player_ids:
                source.player_snapshots += 1
                snapshots.append(snapshot)
    if collector is not None:
        collector.finish(source.path)
        source.telemetry_diagnostics = collector.diagnostics[source.path]
        ids = collector.identities[source.path]
        source.local_player_id = next(iter(ids)) if len(ids) == 1 else None
    if templates is not None:
        templates.finish(source.path)
        source.ball_machine_diagnostics = templates.diagnostics.get(source.path, [])
    source.categories = dict(categories)
    if source.diagnostics:
        source.status = "parse_warnings"
    elif source.player_snapshots:
        source.status = "player_gameplay"
    elif source.snapshots:
        source.status = "other_player_gameplay"
    elif source.lines == 1:
        source.status = "header_only"
    elif source.lines == 0:
        source.status = "empty"
    return source, snapshots


def game_winner(score: tuple[int, int]) -> int | None:
    a, b = score
    if max(a, b) >= 11 and abs(a - b) >= 2:
        # A standard game stops at 11, or the first two-point lead after deuce.
        if max(a, b) == 11 or abs(a - b) == 2:
            return 0 if a > b else 1
    return None


def single_point(
    before: tuple[tuple[int, int], ...], after: tuple[tuple[int, int], ...],
) -> tuple[int, int] | None:
    """Return round index and winning player index for an unambiguous increment."""
    old = before or ((0, 0),)
    new = after
    if len(new) == len(old) + 1 and new[-1] == (0, 0):
        if game_winner(new[-2]) is None:
            return None
        new = new[:-1]
    if len(old) != len(new) or not new or old[:-1] != new[:-1]:
        return None
    if game_winner(old[-1]) is not None:
        return None
    delta = tuple(b - a for a, b in zip(old[-1], new[-1]))
    if delta not in ((1, 0), (0, 1)):
        return None
    return len(new) - 1, 0 if delta[0] else 1


def summarize_match(snapshots: list[Snapshot], player_id: str) -> dict[str, Any]:
    snapshots.sort(key=lambda s: (s.timestamp, s.source, s.line))
    first = snapshots[0]
    index = first.player_ids.index(player_id)
    opponent = 1 - index
    issues: list[str] = []
    metadata = (first.player_ids, first.ranked, first.best_of)
    if any((s.player_ids, s.ranked, s.best_of) != metadata for s in snapshots):
        issues.append("Participant order, ranked flag, or match format changed; metrics excluded.")
    finals = [s for s in snapshots if s.winner is not None]
    if len({(s.winner, s.scores) for s in finals}) > 1:
        issues.append("Conflicting final results; metrics excluded.")
    latest = finals[-1] if finals else snapshots[-1]
    if finals and any(s.scores != latest.scores for s in snapshots[snapshots.index(finals[-1]) + 1:]):
        issues.append("Scores changed after the final result; metrics excluded.")
    rounds = [game_winner(score) for score in latest.scores]
    if finals:
        winner_index = first.player_ids.index(latest.winner) if latest.winner in first.player_ids else -1
        target = first.best_of // 2 + 1
        if (
            None in rounds or rounds.count(winner_index) != target
            or not rounds or rounds[-1] != winner_index
            or rounds[:-1].count(winner_index) >= target
            or rounds.count(1 - winner_index) >= target
        ):
            issues.append("Final scores do not confirm a standard completed match; metrics excluded.")
    status = "inconsistent" if issues else ("completed" if finals else "incomplete")
    points: dict[tuple[int, tuple[int, int]], dict[str, Any]] = {}
    gaps = 0
    before: Snapshot | None = None
    seen_scores: set[tuple[tuple[int, int], ...]] = set()
    if not issues:
        for current in snapshots:
            if current.scores in seen_scores:
                continue
            seen_scores.add(current.scores)
            if before is None:
                if sum(sum(score) for score in current.scores) > 0:
                    gaps += 1
                before = current
                continue
            transition = single_point(before.scores, current.scores)
            if transition:
                round_index, point_winner = transition
                score = current.scores[round_index]
                points[(round_index, score)] = {
                    "round": round_index + 1,
                    "score": list(score),
                    "winner_id": current.player_ids[point_winner],
                    "timestamp": current.timestamp,
                    "raw_reason": current.reason,
                    "source": current.source,
                    "line": current.line,
                    "start_source": before.source,
                    "start_line": before.line,
                }
            elif not (
                len(current.scores) == len(before.scores) + 1
                and current.scores[:-1] == before.scores
                and current.scores[-1] == (0, 0)
            ):
                gaps += 1
            before = current
    scored_points = sum(sum(score) for score in latest.scores)
    own_points = sum(score[index] for score in latest.scores)
    return {
        "match_id": first.match_id,
        "first_observed": first.timestamp,
        "last_observed": snapshots[-1].timestamp,
        "ranked": first.ranked,
        "best_of": first.best_of,
        "status": status,
        "winner_id": latest.winner,
        "won": latest.winner == player_id if status == "completed" else None,
        "player_elo": first.elos[index],
        "opponent_id": first.player_ids[opponent],
        "opponent_name": first.player_names[opponent],
        "opponent_elo": first.elos[opponent],
        "elo_gap": first.elos[opponent] - first.elos[index],
        "scores": [[score[index], score[opponent]] for score in latest.scores],
        "games_won": rounds.count(index) if status == "completed" else None,
        "games_lost": rounds.count(opponent) if status == "completed" else None,
        "points_won": own_points if status == "completed" else None,
        "points_lost": scored_points - own_points if status == "completed" else None,
        "observed_points": list(points.values()),
        "score_transition_gaps": gaps,
        "point_coverage": len(points) / scored_points if scored_points and not issues else None,
        "snapshot_count": len(snapshots),
        "sources": sorted({s.source for s in snapshots}),
        "issues": issues,
    }


def result_stats(matches: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [m for m in matches if m["status"] == "completed"]
    wins = sum(m["won"] for m in completed)
    points_won = sum(m["points_won"] for m in completed)
    points_lost = sum(m["points_lost"] for m in completed)
    return {
        "matches": len(completed),
        "wins": wins,
        "losses": len(completed) - wins,
        "win_rate": wins / len(completed) if completed else None,
        "games_won": sum(m["games_won"] for m in completed),
        "games_lost": sum(m["games_lost"] for m in completed),
        "points_won": points_won,
        "points_lost": points_lost,
        "point_win_rate": points_won / (points_won + points_lost) if points_won + points_lost else None,
    }


def make_profile(
    sources: list[Source], snapshots: list[Snapshot], player_id: str,
) -> dict[str, Any]:
    grouped: dict[str, list[Snapshot]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.match_id].append(snapshot)
    matches = sorted(
        (summarize_match(values, player_id) for values in grouped.values()),
        key=lambda m: (m["first_observed"], m["match_id"]),
    )
    completed = [m for m in matches if m["status"] == "completed"]
    daily = []
    for day in sorted({m["first_observed"][:10] for m in matches}):
        daily_matches = [m for m in matches if m["first_observed"].startswith(day)]
        daily.append({
            "date": day, **result_stats(daily_matches),
            "ranked": result_stats([m for m in daily_matches if m["ranked"]]),
            "unranked": result_stats([m for m in daily_matches if not m["ranked"]]),
        })
    opposition = {}
    for label in ("lower", "similar", "higher"):
        selected = [
            m for m in completed
            if loss_analysis.opponent_band(m["elo_gap"]) == label
        ]
        opposition[label] = result_stats(selected)
    opponents = []
    for opponent_id in sorted({m["opponent_id"] for m in matches}):
        selected = [m for m in matches if m["opponent_id"] == opponent_id]
        opponents.append({
            "id": opponent_id, "name": selected[-1]["opponent_name"],
            "last_observed_elo": selected[-1]["opponent_elo"], **result_stats(selected),
        })
    close_scores = [
        score for m in completed for score in m["scores"]
        if abs(score[0] - score[1]) == 2
    ]
    close_wins = sum(a > b for a, b in close_scores)
    ordered = sorted(snapshots, key=lambda s: (s.timestamp, s.source, s.line))
    names = sorted({s.player_names[s.player_ids.index(player_id)] for s in ordered})
    rating_observations = []
    for snapshot in ordered:
        elo = snapshot.elos[snapshot.player_ids.index(player_id)]
        if not rating_observations or rating_observations[-1]["elo"] != elo:
            rating_observations.append({
                "timestamp": snapshot.timestamp, "elo": elo,
                "match_id": snapshot.match_id, "source": snapshot.source, "line": snapshot.line,
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "player": {"id": player_id, "observed_names": names},
        "summary": {
            **result_stats(matches),
            "observed_matches": len(matches),
            "incomplete_matches": sum(m["status"] == "incomplete" for m in matches),
            "inconsistent_matches": sum(m["status"] == "inconsistent" for m in matches),
            "unique_opponents": len(opponents),
        },
        "by_mode": {
            "ranked": result_stats([m for m in matches if m["ranked"]]),
            "unranked": result_stats([m for m in matches if not m["ranked"]]),
        },
        "by_opponent_strength": opposition,
        "opponent_strength_definition": "similar = within 100 Elo inclusive; gap uses first observed match ratings",
        "daily_results": daily,
        "opponents": opponents,
        "rating_observations": rating_observations,
        "close_games": {"definition": "completed games with a final margin of two points",
                        "wins": close_wins, "losses": len(close_scores) - close_wins},
        "data_quality": {
            "input_files": len(sources),
            "duplicate_files": sum(s.status == "duplicate_file" for s in sources),
            "files_with_player_snapshots": sum(s.player_snapshots > 0 for s in sources),
            "invalid_snapshots": sum(len(s.diagnostics) for s in sources),
            "observed_single_point_transitions": sum(len(m["observed_points"]) for m in matches),
            "score_transition_gaps": sum(m["score_transition_gaps"] for m in matches),
        },
        "limitations": [
            "Only local FullSnapshot records are used; friend activity and server match lists are excluded.",
            "No snapshots means no analyzable match evidence, not proof that no play occurred.",
            "Incomplete or inconsistent matches are excluded from win/loss, game, and final-score point statistics.",
            "Observed point events require a single score increment; missing points are not fabricated.",
            "Raw point-ending reasons are preserved but are not attributed to player technique.",
            "Serve/return rates, complete rally length, stroke type, and physical speed/spin units are not yet validated.",
            "Ratings are observed snapshot values, not a verified rating-change ledger or current live rating.",
            "Dates use log-local time with unknown timezone; elapsed log time is not active training time.",
            "Daily results are descriptive; opponent mix, mode, repeated partners, and small samples limit trend conclusions.",
        ],
        "training_plan": [],
        "matches": matches,
        "sources": [asdict(s) for s in sources],
    }


def percent(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "N/A"


def html_table(headers: list[str], rows: list[list[Any]]) -> str:
    return "<table><thead><tr>" + "".join(f"<th>{escape(str(h))}</th>" for h in headers) + (
        "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows
        ) + "</tbody></table>"
    )


def render_html(profile: dict[str, Any]) -> str:
    return dashboard.render(profile)


def atomic_text(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def persist(output: Path, profile: dict[str, Any], snapshots: list[Snapshot]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(profile, indent=2, ensure_ascii=True, allow_nan=False)
    report = render_html(profile)
    connection = sqlite3.connect(output / "analyst.sqlite3")
    try:
        with connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, SCHEMA_VERSION):
                raise ValueError(f"Unsupported database schema version {version}")
            connection.execute("CREATE TABLE IF NOT EXISTS sources (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, status TEXT NOT NULL, data_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS snapshots (source TEXT NOT NULL, line INTEGER NOT NULL, match_id TEXT NOT NULL, timestamp TEXT NOT NULL, data_json TEXT NOT NULL, PRIMARY KEY (source, line))")
            connection.execute("CREATE INDEX IF NOT EXISTS snapshots_match ON snapshots(match_id)")
            connection.execute("CREATE TABLE IF NOT EXISTS matches (match_id TEXT PRIMARY KEY, status TEXT NOT NULL, data_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS profiles (player_id TEXT PRIMARY KEY, data_json TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS points (match_id TEXT NOT NULL, round_number INTEGER NOT NULL, score_a INTEGER NOT NULL, score_b INTEGER NOT NULL, telemetry_status TEXT NOT NULL, data_json TEXT NOT NULL, PRIMARY KEY (match_id, round_number, score_a, score_b))")
            # Each run is a complete materialized view of the selected input directory.
            for table in ("sources", "snapshots", "matches", "profiles", "points"):
                connection.execute(f"DELETE FROM {table}")
            connection.executemany("INSERT INTO sources VALUES (?, ?, ?, ?)", [
                (s["path"], s["sha256"], s["status"], json.dumps(s)) for s in profile["sources"]
            ])
            connection.executemany("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)", [
                (s.source, s.line, s.match_id, s.timestamp, json.dumps(asdict(s))) for s in snapshots
            ])
            connection.executemany("INSERT INTO matches VALUES (?, ?, ?)", [
                (m["match_id"], m["status"], json.dumps(m)) for m in profile["matches"]
            ])
            connection.execute("INSERT INTO profiles VALUES (?, ?)", (profile["player"]["id"], payload))
            connection.executemany("INSERT INTO points VALUES (?, ?, ?, ?, ?, ?)", [
                (m["match_id"], p["round"], *p["score"],
                 p.get("telemetry", {}).get("status", "unavailable"), json.dumps(p))
                for m in profile["matches"] for p in m["observed_points"]
            ])
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        atomic_text(output / "profile.json", payload + "\n")
        atomic_text(output / "report.html", report)
        if "shot_catalogue" in profile:
            atomic_text(output / "shot_catalogue.json",
                        json.dumps(profile["shot_catalogue"], indent=2, allow_nan=False) + "\n")
        if "practice_patterns" in profile:
            atomic_text(output / "practice_patterns.json",
                        json.dumps(profile["practice_patterns"], indent=2, allow_nan=False) + "\n")
            settings_dir = output / "ball_machine"
            settings_dir.mkdir(exist_ok=True)
            for candidate in profile["practice_patterns"]["settings_candidates"]:
                practice.validate_settings(candidate["settings"])
                atomic_text(settings_dir / f"{candidate['recipe_id']}.candidate.json",
                            json.dumps(candidate["settings"], indent=2, allow_nan=False) + "\n")
            generated_ids = {candidate["recipe_id"] for candidate in profile["practice_patterns"]["settings_candidates"]}
            for collection_id in ("serve-returns", "combined", *(f"plan-{category}" for category in practice.PLAN_SOURCES)):
                if collection_id not in generated_ids:
                    (settings_dir / f"{collection_id}.candidate.json").unlink(missing_ok=True)
    finally:
        connection.close()


def analyze(input_dir: Path, output_dir: Path, player_id: str = DEFAULT_PLAYER_ID) -> dict[str, Any]:
    if not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    if not re.fullmatch(r"[1-9]\d*", player_id):
        raise ValueError("Player ID must be a positive integer")
    paths = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".log")
    if not paths:
        raise ValueError(f"No .log files found in {input_dir}")
    seen: dict[str, str] = {}
    sources = []
    snapshots = []
    collector = telemetry.Collector()
    templates = practice.TemplateCollector()
    for path in paths:
        source, records = read_source(path, player_id, seen, collector, templates)
        sources.append(source)
        snapshots.extend(records)
        LOG.info("%s: %s (%d player snapshots)", path.name, source.status, source.player_snapshots)
    if not snapshots:
        raise ValueError(f"No valid local match snapshots found for player {player_id}; existing outputs were not changed")
    profile = make_profile(sources, snapshots, player_id)
    telemetry.attach(profile, collector)
    loss_analysis.attach(profile)
    profile["practice_patterns"] = practice.build(profile, templates.latest_serve())
    persist(output_dir, profile, snapshots)
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, default=Path("11TTLogs"), help="Input directory (default: 11TTLogs)")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Generated output directory (default: output)")
    parser.add_argument("--player-id", default=DEFAULT_PLAYER_ID, help="Stable player ID (default: DigitalByooki)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        profile = analyze(args.logs, args.output, args.player_id)
    except (OSError, UnicodeError, ValueError, sqlite3.Error) as exc:
        LOG.error("Analysis failed: %s", exc)
        return 1
    summary = profile["summary"]
    LOG.info("Profile: %d completed matches, %d wins, %d losses, %d incomplete, %d inconsistent",
             summary["matches"], summary["wins"], summary["losses"],
             summary["incomplete_matches"], summary["inconsistent_matches"])
    LOG.info("Report written to %s", (args.output / "report.html").resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
