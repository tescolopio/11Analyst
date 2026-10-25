"""Collision telemetry in log coordinates; no inferred paddle pose or physical units."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
import logging
import math
import re
from statistics import median
from typing import Any, Callable


LOG = logging.getLogger("11analyst")
HEADER = re.compile(r"^\[[^\]]+\]\[(\d+),(\d+)\]\[([^\]]+)\](.*)")
STATE = re.compile(
    r"pos:\(([^)]+)\),vel:\(([^)]+)\),rRate:\(([^)]+)\),Rot:\(([^)]+)\),Time:\(([^)]+)\)"
)
HIT = re.compile(
    r"(Sending ball hit to opponent: p|Received ball hit from opponent: pos):"
    r"\(([^)]+)\)\s+(?:v|vel):\(([^)]+)\)\s+(?:r|rrate):\(([^)]+)\)"
)


def vector(text: str, size: int = 3) -> list[float]:
    values = [float(part) for part in text.split(",")]
    if len(values) != size or not all(math.isfinite(value) for value in values):
        raise ValueError(f"expected {size} finite vector components")
    return values


def ball_state(text: str) -> dict[str, Any]:
    match = STATE.fullmatch(text.strip().strip("{}"))
    if match is None:
        raise ValueError("invalid collision state")
    state_time = float(match[5])
    if not math.isfinite(state_time):
        raise ValueError("invalid state time")
    return {
        "position": vector(match[1]), "velocity": vector(match[2]),
        "rotation_rate": vector(match[3]), "orientation": vector(match[4], 4),
        "state_time_raw": state_time,
    }


@dataclass
class Event:
    kind: str
    source: str
    line: int
    timestamp: str | None
    engine_tick: int
    frame: int
    actor: str | None = None
    phase: str | None = None
    collision_type: str | None = None
    relative_sender_raw: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    physics_source_line: int | None = None


class Collector:
    def __init__(self) -> None:
        self.events: dict[str, list[Event]] = defaultdict(list)
        self.diagnostics: dict[str, list[str]] = defaultdict(list)
        self.diagnostic_records: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.identities: dict[str, set[str]] = defaultdict(set)
        self.physics: dict[str, dict[str, Any]] = {}
        self.collisions: dict[str, tuple[Event, dict[str, str]]] = {}
        self.phases: dict[str, str] = {}
        self.retained_events = 0

    def warning(self, source: str, line: int, message: str) -> None:
        diagnostic = f"line {line}: {message}"
        self.diagnostics[source].append(diagnostic)
        self.diagnostic_records[source].append((line, diagnostic))
        LOG.warning("%s: telemetry: %s", source, diagnostic)

    def finish_collision(self, source: str) -> None:
        pending = self.collisions.pop(source, None)
        if pending is None:
            return
        event, fields = pending
        try:
            event.collision_type = fields["pongGameCollisionType"]
            # Hits are represented once, by authoritative send/receive hit messages.
            if event.collision_type.startswith("Hit"):
                return
            if event.collision_type not in ("TableA", "TableB", "Net", "Other", "TossA", "TossB"):
                raise ValueError("unknown game collision type")
            event.relative_sender_raw = fields["relativeSender"]
            event.before = {
                "position": vector(fields["position"].strip("()")),
                "velocity": vector(fields["velocity"].strip("()")),
                "rotation_rate": vector(fields["rotationRate"].strip("()")),
                "orientation": None,
            }
            self.events[source].append(event)
        except (KeyError, ValueError) as exc:
            self.warning(source, event.line, f"invalid game collision: {exc}")

    def feed(self, source: str, line: int, text: str, timestamp: str | None) -> None:
        header = HEADER.match(text)
        if header is None:
            if source in self.collisions and ":" in text:
                key, value = text.strip().split(":", 1)
                if key in ("position", "velocity", "rotationRate", "relativeSender", "pongGameCollisionType"):
                    self.collisions[source][1][key] = value
            if "paddleSignal with stateAtEventPostServiceHit" in text or "paddleHitSignal...with gameStateAtEvent:PostServiceHit" in text:
                self.phases[source] = "serve"
            elif "paddleSignal with stateAtEventPostHit" in text or "paddleHitSignal...with gameStateAtEvent:PostHit" in text:
                self.phases[source] = "rally"
            return
        self.finish_collision(source)
        tick, frame, tag, message = int(header[1]), int(header[2]), header[3], header[4]
        event = Event("", source, line, timestamp, tick, frame)
        if tag == "TCPSERVERCOMMUNICATIONS" and '"Authenticated"' in message and '"user"' in message:
            try:
                response = json.loads(message[message.index("{"):])
                for item in response["data"]:
                    if isinstance(item, dict) and item.get("response") == "Authenticated":
                        user_id = str(item["user"]["Id"])
                        if not re.fullmatch(r"[1-9]\d*", user_id):
                            raise ValueError("invalid authenticated account ID")
                        self.identities[source].add(user_id)
            except (ValueError, KeyError, TypeError) as exc:
                self.warning(source, line, f"could not establish local account: {type(exc).__name__}")
        elif tag == "MPMatch" and message == "ShotClockMessage OnPointStarted":
            event.kind = "point_start"
            self.events[source].append(event)
            self.physics.pop(source, None)
            self.phases.pop(source, None)
        elif tag == "GameLogic" and "Changing [pointRunning] from [True] to [False]" in message:
            event.kind = "point_end"
            self.events[source].append(event)
        elif tag == "GameLogic" and " : MyCollision:" in message:
            event.kind = "collision"
            self.collisions[source] = (event, {})
        elif tag == "Physics-BallCollisions":
            if message == "Dynamic Collision...":
                self.physics[source] = {"frame": frame, "line": line}
            elif message.startswith(("..preCollisionState:", "..postCollisionState:")):
                pending = self.physics.get(source)
                if pending is None or pending["frame"] != frame:
                    self.warning(source, line, "collision state without same-frame dynamic collision")
                    return
                key = "before" if message.startswith("..preCollisionState:") else "after"
                try:
                    pending[key] = ball_state(message.split(":", 1)[1])
                except ValueError as exc:
                    self.warning(source, line, str(exc))
        elif tag == "MPMatch" and message.startswith(("Sending ball hit to opponent:", "Received ball hit from opponent:")):
            try:
                match = HIT.fullmatch(message.strip())
                if match is None:
                    raise ValueError("invalid ball hit message")
                event.kind = "hit"
                event.actor = "local" if match[1].startswith("Sending") else "remote"
                event.phase = self.phases.pop(source, None)
                event.after = {
                    "position": vector(match[2]), "velocity": vector(match[3]),
                    "rotation_rate": vector(match[4]), "orientation": None,
                }
                pending = self.physics.pop(source, None) if event.actor == "local" else None
                if pending and pending["frame"] == frame and "after" in pending:
                    if all(
                        all(math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6) for a, b in zip(
                            event.after[key], pending["after"][key],
                        )) for key in ("position", "velocity", "rotation_rate")
                    ):
                        event.before = pending.get("before")
                        event.after = pending["after"]
                        event.physics_source_line = pending["line"]
                self.events[source].append(event)
            except ValueError as exc:
                self.warning(source, line, str(exc))

    def finish(self, source: str) -> None:
        self.finish_collision(source)
        self.events[source].sort(key=lambda event: event.line)
        if len(self.identities[source]) > 1:
            self.warning(source, 0, "multiple authenticated accounts; hit ownership unavailable")


def describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {"count": len(values), "min": min(values), "median": median(values), "max": max(values)}


def hit_features(event: dict[str, Any]) -> dict[str, Any]:
    before, after = event["before"], event["after"]
    return {
        "incoming_speed_raw": math.hypot(*before["velocity"]) if before else None,
        "outgoing_speed_raw": math.hypot(*after["velocity"]) if after else None,
        "incoming_spin_magnitude_raw": math.hypot(*before["rotation_rate"]) if before else None,
        "outgoing_spin_magnitude_raw": math.hypot(*after["rotation_rate"]) if after else None,
        "velocity_change_raw": [b - a for a, b in zip(before["velocity"], after["velocity"])]
        if before and after else None,
        "contact_position_raw": after["position"] if after else None,
        "paddle_speed": None,
        "paddle_face_angle": None,
        "paddle_contact_location": None,
    }


def event_key(event: Event) -> str:
    state = event.after if event.kind == "hit" else event.before
    vectors = {key: state[key] for key in ("position", "velocity", "rotation_rate")} if state else None
    return json.dumps((event.kind, event.engine_tick, event.frame, event.actor, event.collision_type, vectors), sort_keys=True)


def attach(profile: dict[str, Any], collector: Collector) -> None:
    indexes = {source: [event.line for event in events] for source, events in collector.events.items()}
    qualities: Counter[str] = Counter()
    hit_counts: Counter[str] = Counter()
    incoming: list[float] = []
    outgoing: list[float] = []
    spin: list[float] = []
    contact_y: list[float] = []
    paired = 0
    retained = 0
    warned_points = 0
    selected_id = profile["player"]["id"]
    for match in profile["matches"]:
        for point in match["observed_points"]:
            result: dict[str, Any] = {
                "status": "unavailable", "issues": [], "attempts": 0, "events": [],
                "observed_hits": 0, "observed_player_hits": 0,
                "observed_opponent_hits": 0, "paired_player_hits": 0,
                "measurement_status": "unavailable", "parse_warning_count": 0,
            }
            point["telemetry"] = result
            source = point["source"]
            if source != point["start_source"]:
                result["issues"].append("Score snapshots cross files; no physics association attempted.")
            else:
                lines = indexes.get(source, [])
                events = collector.events.get(source, [])
                window = events[bisect_right(lines, point["start_line"]):bisect_left(lines, point["line"])]
                unique_window: dict[str, Event] = {}
                for event in window:
                    key = event_key(event)
                    if key not in unique_window:
                        unique_window[key] = event
                window = list(unique_window.values())
                warnings = [
                    message for line, message in collector.diagnostic_records.get(source, [])
                    if point["start_line"] < line < point["line"]
                ]
                result["parse_warning_count"] = len(warnings)
                result["issues"].extend(warnings)
                warned_points += bool(warnings)
                starts = [i for i, e in enumerate(window) if e.kind == "point_start"]
                if not starts:
                    result["issues"].append("No point-start marker between score snapshots.")
                else:
                    result["attempts"] = len(starts)
                    bounded = True
                    for attempt, start in enumerate(starts, 1):
                        stop = starts[attempt] if attempt < len(starts) else len(window)
                        segment = window[start:stop]
                        ends = [i for i, e in enumerate(segment) if e.kind == "point_end"]
                        if len(ends) != 1:
                            bounded = False
                            result["issues"].append(f"Attempt {attempt} has {len(ends)} end markers; telemetry excluded.")
                            continue
                        segment = segment[:ends[0] + 1]
                        for event in segment:
                            encoded = asdict(event)
                            encoded["attempt"] = attempt
                            identities = collector.identities.get(source, set())
                            local_id = next(iter(identities)) if len(identities) == 1 else None
                            actor_id = None
                            if local_id in (selected_id, match["opponent_id"]):
                                actor_id = local_id if event.actor == "local" else (
                                    match["opponent_id"] if local_id == selected_id else selected_id
                                ) if event.actor == "remote" else None
                            encoded["actor_id"] = actor_id
                            if event.kind == "hit":
                                encoded["features"] = hit_features(encoded)
                            result["events"].append(encoded)
                    result["status"] = ("bounded" if len(starts) == 1 else "bounded_multiple_attempts") if bounded else "partial"
            if result["status"] == "unavailable":
                qualities["unavailable"] += 1
                continue
            if not collector.identities.get(source) or len(collector.identities[source]) != 1:
                result["issues"].append("Local account unverified; player/opponent hit attribution unavailable.")
            hits = [event for event in result["events"] if event["kind"] == "hit"]
            own = [event for event in hits if event["actor_id"] == selected_id]
            result["observed_hits"] = len(hits)
            result["observed_player_hits"] = len(own)
            result["observed_opponent_hits"] = sum(event["actor_id"] == match["opponent_id"] for event in hits)
            result["paired_player_hits"] = sum(event["before"] is not None for event in own)
            missing_pairs = len(own) - result["paired_player_hits"]
            if missing_pairs:
                result["issues"].append(f"{missing_pairs} player hits lack matched incoming ball states.")
            unknown_hits = sum(event["actor_id"] is None for event in hits)
            if unknown_hits:
                result["issues"].append(f"{unknown_hits} hits have unknown player attribution.")
            if not hits:
                result["issues"].append("No authoritative hit messages captured in the bounded attempts.")
            result["measurement_status"] = "gaps_detected" if result["issues"] else "no_detected_gaps"
            if result["status"].startswith("bounded"):
                for event in hits:
                    role = "player" if event["actor_id"] == selected_id else "opponent" if event["actor_id"] == match["opponent_id"] else "unattributed"
                    hit_counts[role] += 1
                for event in own:
                    features = event["features"]
                    outgoing.append(features["outgoing_speed_raw"])
                    spin.append(features["outgoing_spin_magnitude_raw"])
                    contact_y.append(features["contact_position_raw"][1])
                    if features["incoming_speed_raw"] is not None:
                        paired += 1
                        incoming.append(features["incoming_speed_raw"])
            retained += len(result["events"])
            qualities[result["status"]] += 1
    collector.retained_events = retained
    profile["ball_telemetry"] = {
        "units": "Raw log coordinates and rates; no m/s, km/h, rpm, or paddle-angle conversion is claimed.",
        "basis": "Hit statistics use explicitly start/end-bounded attempts only, including multiple attempts per scoring point. Counts are observed contacts, not guaranteed rally lengths.",
        "point_status_counts": dict(qualities),
        "bounded_hit_counts": dict(hit_counts),
        "paired_player_hits": paired,
        "player_incoming_speed_raw": describe(incoming),
        "player_outgoing_speed_raw": describe(outgoing),
        "player_outgoing_spin_magnitude_raw": describe(spin),
        "player_contact_y_raw": describe(contact_y),
        "retained_events": retained,
        "diagnostics": sum(len(items) for items in collector.diagnostics.values()),
        "points_with_parse_warnings": warned_points,
        "paddle_kinematics_available": False,
    }
    profile["limitations"].extend([
        "Ball telemetry requires same-file score boundaries and explicit point start/end markers; partial attempts are excluded from aggregate hit statistics.",
        "Local collision states are paired with outgoing hits only in the same engine frame with matching position, velocity, and rotation-rate vectors.",
        "Hit ownership uses authenticated account IDs. relativeSender at a collision can describe the previous hitter and is not used to identify the current hitter.",
        "Ball orientation is not paddle orientation. Paddle speed, face angle, contact location, and continuous swing paths remain unavailable.",
        "Table and net contacts use local MyCollision records only; remote simulation duplicates are not counted again.",
    ])


def render_section(
    profile: dict[str, Any], table: Callable[[list[str], list[list[Any]]], str],
    escape: Callable[..., str],
) -> str:
    telemetry = profile.get("ball_telemetry")
    if telemetry is None:
        return ""
    parts = [
        "<h2>Ball and contact measurements</h2>",
        f"<p>{escape(telemetry['units'])}</p><p>{escape(telemetry['basis'])}</p>",
        table(["Point boundary status", "Points"], [[k, v] for k, v in telemetry["point_status_counts"].items()]),
        f"<p>Bounded observed hits: {telemetry['bounded_hit_counts'].get('player', 0)} yours, "
        f"{telemetry['bounded_hit_counts'].get('opponent', 0)} opponent, "
        f"{telemetry['bounded_hit_counts'].get('unattributed', 0)} unattributed. "
        f"Telemetry parse warnings: {telemetry['diagnostics']}; affected point windows: {telemetry['points_with_parse_warnings']}.</p>",
        table(["Measure", "Samples", "Min", "Median", "Max"], [
            [key.replace("_", " "), telemetry[key]["count"],
             *[f"{telemetry[key][stat]:.3f}" if telemetry[key][stat] is not None else "N/A"
               for stat in ("min", "median", "max")]]
            for key in ("player_incoming_speed_raw", "player_outgoing_speed_raw",
                        "player_outgoing_spin_magnitude_raw", "player_contact_y_raw")
        ]),
        "<p>Paddle-hit events are recorded, but paddle speed, face angle, and contact location are unavailable. "
        "Expand a match below for per-point coverage. Full vectors and provenance are in the JSON profile and SQLite points table.</p>",
    ]
    for match in profile["matches"]:
        parts.append(f"<details><summary>Match {escape(match['match_id'])}: {escape(match['opponent_name'])} - point telemetry</summary>")
        parts.append(table(["Round", "Score (participant order)", "Outcome", "Loss pattern", "Boundaries", "Measurements", "Attempts", "Your hits", "Opponent hits", "Paired incoming/outgoing", "Notes"], [
            [point["round"], "-".join(map(str, point["score"])),
             "Won" if point["winner_id"] == profile["player"]["id"] else "Lost",
             point["loss_analysis"]["category"] if point.get("loss_analysis") else "-",
             point["telemetry"]["status"],
             point["telemetry"]["measurement_status"],
             point["telemetry"]["attempts"], point["telemetry"]["observed_player_hits"],
             point["telemetry"]["observed_opponent_hits"], point["telemetry"]["paired_player_hits"],
             "; ".join(point["telemetry"]["issues"])]
            for point in match["observed_points"]
        ]))
        parts.append("</details>")
    return "\n".join(parts)
