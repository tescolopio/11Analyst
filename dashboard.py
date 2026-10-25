"""Render a portable dashboard with inline assets and no fetched data."""

from __future__ import annotations

from collections import Counter
from html import escape
import json
from pathlib import Path
import re
from typing import Any

import loss_analysis
import practice
import hero_import


ASSETS = Path(__file__).with_name("dashboard")
PLAYER_SETTINGS = Path(__file__).with_name("player_settings.json")


def player_context(player: dict[str, Any]) -> dict[str, Any]:
    settings = json.loads(PLAYER_SETTINGS.read_text(encoding="utf-8"))
    if settings.get("version") != 1 or not isinstance(settings.get("players"), dict):
        raise ValueError("Invalid player settings")
    preference = settings["players"].get(player["id"])
    if preference is None:
        return {**player, "handedness": "unknown", "handedness_source": "not_configured"}
    if preference.get("handedness") not in ("right", "left", "varies") or preference.get("source") != "user_confirmed":
        raise ValueError("Invalid handedness preference")
    return {**player, "handedness": preference["handedness"], "handedness_source": preference["source"]}


def scoped_data(profile: dict[str, Any], mode: str) -> dict[str, Any]:
    scope = loss_analysis.for_mode(profile, mode)
    matches = scope["matches"]
    completed = [match for match in matches if match["status"] == "completed"]
    points_won = sum(match["points_won"] for match in completed)
    points_lost = sum(match["points_lost"] for match in completed)
    summary = {
        "completed": len(completed), "observed_matches": len(matches),
        "wins": sum(match["won"] for match in completed),
        "losses": sum(not match["won"] for match in completed),
        "points_won": points_won, "points_lost": points_lost,
        "point_win_rate": points_won / (points_won + points_lost) if points_won + points_lost else None,
        "opponents": len({match["opponent_id"] for match in matches}),
        "incomplete": sum(match["status"] == "incomplete" for match in matches),
        "inconsistent": sum(match["status"] == "inconsistent" for match in matches),
        "higher_rated_matches": sum(match["elo_gap"] > 100 for match in completed),
    }
    point_status: Counter[str] = Counter()
    player_hits = paired_hits = 0
    for match in matches:
        for point in match["observed_points"]:
            telemetry = point.get("telemetry", {})
            status = telemetry.get("status", "unavailable")
            point_status[status] += 1
            if status.startswith("bounded"):
                player_hits += telemetry.get("observed_player_hits", 0)
                paired_hits += telemetry.get("paired_player_hits", 0)
    daily = []
    for day in profile["daily_results"]:
        stats = day if mode == "all" else day[mode]
        daily.append({
            "date": day["date"], "matches": stats["matches"],
            "wins": stats["wins"], "losses": stats["losses"],
            "point_win_rate": stats["point_win_rate"],
        })
    scope.update({
        "summary": summary, "daily": daily,
        "telemetry": {"point_status": dict(point_status), "player_hits": player_hits, "paired_hits": paired_hits},
    })
    return scope


def compact_match(match: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in match.items() if key != "observed_points"}
    points = []
    for point in match["observed_points"]:
        telemetry = point.get("telemetry", {})
        events = []
        for event in telemetry.get("events", []):
            events.append({
                key: value for key, value in event.items()
                if key not in ("features", "source") and value is not None
            })
        points.append({
            "id": f"{match['match_id']}:{point['round']}:{point['score'][0]}:{point['score'][1]}",
            "round": point["round"], "score": point["score"],
            "winner_id": point["winner_id"], "timestamp": point["timestamp"],
            "reason": point["raw_reason"], "source": point["source"], "line": point["line"],
            "loss": point.get("loss_analysis"),
            "telemetry": {key: value for key, value in telemetry.items() if key != "events"},
            "events": events,
        })
    result["points"] = points
    return result


def build_data(profile: dict[str, Any]) -> dict[str, Any]:
    scopes = {mode: scoped_data(profile, mode) for mode in ("all", "ranked", "unranked")}
    patterns = {**profile.get("practice_patterns", {
        "recipes": [], "collections": [], "settings_candidates": [], "methodology_sources": [],
    })}
    plans = practice.training_candidates(profile)
    patterns["settings_candidates"] = [
        item for item in patterns.get("settings_candidates", []) if item.get("kind") != "training_plan"
    ] + plans
    candidate_hashes = {}
    for candidate in patterns["settings_candidates"]:
        practice.validate_settings(candidate["settings"])
        candidate_hashes[candidate["recipe_id"]] = practice.settings_digest(candidate["settings"])
    return {
        "format": "11analyst.dashboard", "version": 1,
        "player": player_context(profile["player"]), "generated_at": profile["generated_at"],
        "matches": [compact_match(match) for match in scopes["all"]["matches"]],
        "shot_catalogue": scopes["all"]["shot_catalogue"],
        "views": {
            mode: {key: value for key, value in scope.items() if key not in ("player", "matches", "shot_catalogue")}
            for mode, scope in scopes.items()
        },
        "quality": profile["data_quality"],
        "sources": [{
            "name": Path(source["path"]).name, "path": source["path"],
            "status": source["status"], "size_bytes": source["size_bytes"],
            "player_snapshots": source["player_snapshots"],
            "diagnostics": source["diagnostics"] + source["telemetry_diagnostics"] + source["ball_machine_diagnostics"],
        } for source in profile["sources"]],
        "physics_diagnostics": profile.get("ball_telemetry", {}).get("diagnostics", 0),
        "practice": patterns,
        "limitations": profile["limitations"] + scopes["all"]["loss_analysis"]["limits"],
        "rating_observations": profile["rating_observations"],
        "publishing": {"candidate_sha256": candidate_hashes,
                       "plans": [{"id": item["recipe_id"], "title": item["title"], "category_id": item["category_id"]}
                                 for item in plans]},
    }


def render(profile: dict[str, Any], publishing_service: dict[str, Any] | None = None,
           hero_evidence: dict[str, Any] | None = None) -> str:
    data = build_data(profile)
    evidence = hero_evidence if hero_evidence is not None else hero_import.empty_evidence(profile["player"]["id"])
    if evidence.get("player_id") != profile["player"]["id"]:
        raise ValueError("Hero evidence belongs to another player")
    data["hero_evidence"] = evidence
    if publishing_service is not None:
        data["publishing"]["service"] = publishing_service
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    summary = data["views"]["all"]["summary"]
    fallback = (
        "<h2>JavaScript is disabled</h2><p>Enable JavaScript for filters, charts, evidence inspection, and embedded drill downloads. "
        "No network connection is needed.</p>"
        f"<p>{summary['completed']} completed matches: {summary['wins']} wins and {summary['losses']} losses.</p>"
        "<h3>Training priorities</h3><ul>" +
        "".join(f"<li><strong>{escape(item['focus'])}</strong>: {escape(item['evidence'])}</li>"
                for item in data["views"]["all"]["training_plan"]) +
        "</ul><h3>Recorded opponents</h3><ul>" +
        "".join(f"<li>{escape(match['opponent_name'])}</li>" for match in profile["matches"]) + "</ul>"
    )
    replacements = {
        "DATA": payload, "FALLBACK": fallback,
        "STYLE": (ASSETS / "dashboard.css").read_text(encoding="utf-8"),
        "SCRIPT": (ASSETS / "dashboard.js").read_text(encoding="utf-8"),
        "PUBLISHING_SCRIPT": (ASSETS / "publishing.js").read_text(encoding="utf-8"),
        "GRAPHICS_SCRIPT": (ASSETS / "graphics.js").read_text(encoding="utf-8"),
        "SPIN_SCRIPT": (ASSETS / "spin.js").read_text(encoding="utf-8"),
        "PILOT_SCRIPT": (ASSETS / "pilot.js").read_text(encoding="utf-8"),
        "CATALOGUE_SCRIPT": (ASSETS / "catalogue.js").read_text(encoding="utf-8"),
        "HERO_SCRIPT": (ASSETS / "hero.js").read_text(encoding="utf-8"),
        "HERO_REVIEW_SCRIPT": (ASSETS / "hero_review.js").read_text(encoding="utf-8"),
    }
    template = (ASSETS / "template.html").read_text(encoding="utf-8")
    if publishing_service is not None:
        template = template.replace("connect-src 'none'", "connect-src 'self'")
    return re.sub(r"@@(DATA|FALLBACK|STYLE|SCRIPT|PUBLISHING_SCRIPT|GRAPHICS_SCRIPT|SPIN_SCRIPT|PILOT_SCRIPT|CATALOGUE_SCRIPT|HERO_SCRIPT|HERO_REVIEW_SCRIPT)@@", lambda match: replacements[match[1]], template)
