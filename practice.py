"""Original manual ball-machine recipes, grounded in cited community methodologies."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
from typing import Any, Callable

import loss_analysis


SETTING_FIELDS = {
    "position": ("x", "y", "z"),
    "direction": ("horizontalAngle", "verticalAngle"),
    "spin": ("topBottom", "leftRight", "screw"),
    "speedAndRate": ("speed", "secondsPerLaunch", "PostDelay"),
}
PLAN_SOURCES = {
    "shot-landing": ("repeatable-contact", "controlled-variation"),
    "rally-reception": ("two-location-recovery",),
    "serve-reception": ("serve-returns",),
    "return-unspecified": ("repeatable-contact",),
}


def settings_digest(settings: dict[str, Any]) -> str:
    encoded = json.dumps(settings, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


SOURCES = [
    {
        "title": "Shane Lindsay: Dynamic Drillinator",
        "url": "https://github.com/shanelindsay/ElevenBallMachine",
        "verified_on": "2026-10-24",
        "supports": "Controlled, variable, and point-like sequences; changing launch origins; progressive difficulty.",
        "caveat": "Guide explicitly describes the June 2020 machine; its UI and file format are not current-version guarantees.",
    },
    {
        "title": "SolidSlime: Service Return Drills",
        "url": "https://github.com/jerryfromearth/ETT-Service-Return-Drills",
        "verified_on": "2026-10-24",
        "supports": "Adapt a similar serve template, learn with limited variation, then add variation and shuffle.",
        "caveat": "Historical cloud codes and manual replacement instructions are documented, not tested here.",
    },
]


class TemplateCollector:
    """Read only game-default machine settings, never arbitrary embedded JSON."""

    def __init__(self) -> None:
        self.pending: dict[str, dict[str, Any]] = {}
        self.serve_templates: list[dict[str, Any]] = []
        self.diagnostics: dict[str, list[str]] = {}

    def feed(self, source: str, line: int, text: str, timestamp: str | None, is_header: bool) -> None:
        if is_header:
            self.finish(source)
            if "Loading Default Settings JSON for object:BallLauncherDeviceSettings" in text:
                self.pending[source] = {"line": line, "timestamp": timestamp, "lines": []}
        elif source in self.pending:
            self.pending[source]["lines"].append(text)

    def finish(self, source: str) -> None:
        pending = self.pending.pop(source, None)
        if pending is None:
            return
        try:
            settings = json.loads("".join(pending["lines"]))
            if settings["settingsVersion"] != "1":
                raise ValueError("unsupported default machine settings version")
            for shot_id, original in settings["shots"]["data"].items():
                if original.get("DataName") != "Serve":
                    continue
                shot = {key: deepcopy(original[key]) for key in ("position", "direction", "spin", "speedAndRate")}
                shot["Description"] = "11 Analyst: game-default serve seed. Calibrate the trajectory in-game."
                shot["isActive"] = "True"
                shot["speedAndRate"]["raw"].setdefault("PostDelay", "0")
                shot["speedAndRate"]["spread"].setdefault("PostDelay", "0")
                candidate = settings_root({"ANLY01": shot})
                validate_settings(candidate)
                self.serve_templates.append({
                    "source": source, "line": pending["line"], "timestamp": pending["timestamp"],
                    "preset_id": shot_id, "preset_name": "Serve",
                    "origin": "game-default BallLauncherDeviceSettings", "shot": shot,
                })
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            message = f"line {pending['line']}: invalid default ball-machine settings: {exc}"
            self.diagnostics.setdefault(source, []).append(message)
            logging.getLogger("11analyst").warning("%s: %s", source, message)

    def latest_serve(self) -> dict[str, Any] | None:
        return max(self.serve_templates, key=lambda item: (item["timestamp"] or "", item["source"], item["line"])) if self.serve_templates else None


def settings_root(shots: dict[str, Any]) -> dict[str, Any]:
    return {
        "settingsVersion": "1", "showBallMachineLauncherAlways": "True",
        "ballCount": "5", "timeScale": "1", "shuffle": "False",
        "shots": {
            "LastModified": "1/1/0001 12:00:00 AM", "Dirty": "False", "Deleted": "False",
            "data": shots,
        },
    }


def candidate_settings() -> list[dict[str, Any]]:
    """Build originals from the numeric seed supplied by the user, not match physics."""
    seed = {
        "Description": "11 Analyst: repeatable contact. Calibrate the landing point in-game before practice.",
        "isActive": "True",
        "position": {
            "raw": {"x": "-0.43176531791687", "y": "-0.240288496017456", "z": "0.180000007152557"},
            "spread": {"x": "0", "y": "0", "z": "0"},
        },
        "direction": {
            "raw": {"horizontalAngle": "-17.9228744506836", "verticalAngle": "11.4849243164063"},
            "spread": {"horizontalAngle": "0", "verticalAngle": "0"},
        },
        "spin": {
            "raw": {"topBottom": "30.1296539306641", "leftRight": "0", "screw": "0"},
            "spread": {"topBottom": "0", "leftRight": "0", "screw": "0"},
        },
        "speedAndRate": {
            "raw": {"speed": "10.3590488433838", "secondsPerLaunch": "2", "PostDelay": "0"},
            "spread": {"speed": "0", "secondsPerLaunch": "0", "PostDelay": "0"},
        },
    }
    candidates = []
    for recipe_id, title, variations in (
        ("repeatable-contact", "Repeatable contact baseline", [(0, "0")]),
        ("two-location-recovery", "Two-direction recovery", [(-4, "0"), (4, "0")]),
        ("controlled-variation", "Controlled placement variation", [(0, "1.5")]),
    ):
        shots = {}
        for index, (angle_offset, angle_spread) in enumerate(variations, 1):
            shot = deepcopy(seed)
            shot["Description"] = f"11 Analyst: {title}, feed {index}. Verify landing and comfortable recovery time in-game."
            shot["direction"]["raw"]["horizontalAngle"] = str(
                Decimal(seed["direction"]["raw"]["horizontalAngle"]) + angle_offset
            )
            shot["direction"]["spread"]["horizontalAngle"] = angle_spread
            shots[f"ANLY{index:02d}"] = shot
        settings = settings_root(shots)
        validate_settings(settings)
        candidates.append({
            "recipe_id": recipe_id, "title": title,
            "path": f"ball_machine/{recipe_id}.candidate.json",
            "validated_against_supplied_shape": True,
            "tested_in_game": False,
            "changes_from_seed": "Activate shots; retain raw launch position, base aim, speed, and spin; "
                                 "use a 2-second interval, zero PostDelay, and zero spread except explicitly varied horizontal aim. "
                                 f"Horizontal aim offsets/spreads: {variations}.",
            "settings": settings,
        })
    return candidates


def build_collections(
    candidates: list[dict[str, Any]], serve_template: dict[str, Any] | None,
    links: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rally = deepcopy(next(c for c in candidates if c["recipe_id"] == "two-location-recovery")["settings"]["shots"]["data"])
    serve = deepcopy(serve_template["shot"]) if serve_template else None
    if serve:
        serve["speedAndRate"]["raw"]["secondsPerLaunch"] = "3"
        serve["speedAndRate"]["raw"]["PostDelay"] = "0"
    collections = []
    for collection_id, title, recipe_ids, sequence in (
        ("serve-returns", "Serve-return machine", ["serve-reception"], ["serve"]),
        ("rally-practice", "Rally-practice machine", ["repeatable-contact", "two-location-recovery", "controlled-variation"], ["rally", "rally"]),
        ("combined", "Serve plus rally machine", ["serve-reception", "repeatable-contact", "two-location-recovery"], ["serve", "rally", "rally"]),
    ):
        available = "serve" not in sequence or serve is not None
        priority_links = {}
        for recipe_id in recipe_ids:
            for link in links.get(recipe_id, []):
                priority_links[link["priority"]] = link
        collection = {
            "id": collection_id, "title": title, "recipe_ids": recipe_ids,
            "training_priorities": [priority_links[key] for key in sorted(priority_links)],
            "planned_sequence": sequence,
            "status": "candidate_requires_in_game_validation" if available else "missing_serve_template",
            "settings_path": f"ball_machine/{collection_id}.candidate.json" if available else None,
            "serve_seed": {key: value for key, value in serve_template.items() if key != "shot"}
            if serve_template and "serve" in sequence else None,
            "notes": "Timed, open-loop feeds; not reactive to your return. Verify feed order, bounce legality, placement, "
                     "launch intervals, and PostDelay in-game before training. Shuffle remains off.",
        }
        collections.append(collection)
        if not available:
            continue
        shots = {}
        rally_index = 0
        for index, role in enumerate(sequence, 1):
            if role == "serve":
                shot = deepcopy(serve)
            else:
                shot = deepcopy(list(rally.values())[rally_index % len(rally)])
                rally_index += 1
            shot["Description"] = f"11 Analyst: {title}, feed {index} ({role}). Verify timing and legal bounces in-game."
            if collection_id == "combined" and index == len(sequence):
                shot["speedAndRate"]["raw"]["PostDelay"] = "3"
            shots[f"ANLY{index:02d}"] = shot
        settings = settings_root(shots)
        validate_settings(settings)
        candidates.append({
            "recipe_id": collection_id, "title": title, "path": collection["settings_path"],
            "validated_against_supplied_shape": True, "tested_in_game": False,
            "kind": "collection",
            "training_priorities": collection["training_priorities"],
            "changes_from_seed": "Serve feeds use the game-default Serve preset when available; rally feeds use the supplied "
                                 "forehand-drive template with horizontal aim offsets. Serve interval 3 seconds; rally interval 2 seconds. "
                                 "Combined sequence proposes a final PostDelay of 3 seconds for recovery; timing semantics remain untested.",
            "settings": settings,
        })
    return collections


def training_candidates(
    profile: dict[str, Any], candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    source_candidates = candidates if candidates is not None else profile.get("practice_patterns", {}).get("settings_candidates", [])
    sources = {item["recipe_id"]: item for item in source_candidates if item.get("kind") != "training_plan"}
    result = []
    for plan in loss_analysis.for_mode(profile)["training_plan"]:
        category = plan["category_id"]
        if not plan.get("machine_practice_eligible") or category not in PLAN_SOURCES:
            continue
        source_ids = PLAN_SOURCES[category]
        if any(identifier not in sources for identifier in source_ids):
            continue
        shots, stages = {}, []
        for stage_index, identifier in enumerate(source_ids, 1):
            source = sources[identifier]
            validate_settings(source["settings"])
            feeds = []
            for shot in source["settings"]["shots"]["data"].values():
                feed = len(shots) + 1
                copied = deepcopy(shot)
                copied["isActive"] = "True" if stage_index == 1 else "False"
                copied["Description"] = f"11 Analyst: {source['title']}, stage {stage_index}, feed {feed}. Generic practice; calibrate in-game."
                shots[f"ANLY{feed:02d}"] = copied
                feeds.append(feed)
            stages.append({"title": source["title"], "feeds": feeds, "active_initially": stage_index == 1})
        settings = settings_root(shots)
        validate_settings(settings)
        identifier = f"plan-{category}"
        result.append({
            "recipe_id": identifier, "title": plan["focus"], "category_id": category,
            "kind": "training_plan", "recipe_ids": plan["recipe_ids"], "stages": stages,
            "path": f"ball_machine/{identifier}.candidate.json",
            "validated_against_supplied_shape": True, "tested_in_game": False,
            "changes_from_seed": "General template-based return practice, not a reproduction of any opponent's ball. "
                                 "Only stage 1 is active initially. For later stages, deactivate earlier feeds and activate "
                                 "the listed feed numbers manually after establishing a stable baseline. Calibrate before training.",
            "training_priorities": [plan],
            "settings": settings,
        })
    return result


def validate_settings(settings: dict[str, Any]) -> None:
    if settings.get("settingsVersion") != "1":
        raise ValueError("candidate settingsVersion must be string '1'")
    for name in ("showBallMachineLauncherAlways", "shuffle"):
        if settings.get(name) not in ("True", "False"):
            raise ValueError(f"{name} must be a string boolean")
    for name in ("ballCount", "timeScale"):
        numeric_setting(settings.get(name), name, positive=True)
    if Decimal(settings["ballCount"]) % 1:
        raise ValueError("ballCount must be an integer")
    container = settings.get("shots")
    if not isinstance(container, dict):
        raise ValueError("shots must be an object")
    shots = container.get("data")
    if not isinstance(shots, dict) or not shots:
        raise ValueError("shots.data must be a nonempty object")
    for shot in shots.values():
        if not isinstance(shot, dict) or shot.get("isActive") not in ("True", "False"):
            raise ValueError("shot isActive must be a string boolean")
        if not isinstance(shot.get("Description"), str):
            raise ValueError("shot Description must be a string")
        for group, fields in SETTING_FIELDS.items():
            group_values = shot.get(group)
            if not isinstance(group_values, dict):
                raise ValueError(f"{group} must be an object")
            for mode in ("raw", "spread"):
                values = group_values.get(mode)
                if not isinstance(values, dict):
                    raise ValueError(f"{group}.{mode} must be an object")
                for name in fields:
                    number = numeric_setting(values.get(name), f"{group}.{mode}.{name}",
                                             positive=mode == "raw" and name in ("speed", "secondsPerLaunch"))
                    if (mode == "spread" or name == "PostDelay") and number < 0:
                        raise ValueError(f"{group}.{mode}.{name} must be nonnegative")


def numeric_setting(value: Any, name: str, positive: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a numeric string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a finite numeric string") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return number


def build(profile: dict[str, Any], serve_template: dict[str, Any] | None = None) -> dict[str, Any]:
    examples = []
    for match in profile["matches"]:
        if match["status"] != "completed":
            continue
        for point in match["observed_points"]:
            telemetry = point.get("telemetry", {})
            if telemetry.get("status") != "bounded":
                continue
            for event in telemetry["events"]:
                if (
                    event["kind"] == "hit" and event["actor_id"] == profile["player"]["id"]
                    and event["phase"] == "rally" and event["before"]
                ):
                    examples.append({
                        "match_id": match["match_id"], "round": point["round"],
                        "point_score_participant_order": point["score"],
                        "point_won": point["winner_id"] == profile["player"]["id"],
                        "source": event["source"], "line": event["line"],
                        "incoming_ball": event["before"],
                        "incoming_speed_raw": event["features"]["incoming_speed_raw"],
                    })
    examples.sort(key=lambda item: item["incoming_speed_raw"])
    references = []
    if examples:
        for label, index in (("lower_quartile", (len(examples) - 1) // 4),
                             ("median", (len(examples) - 1) // 2),
                             ("upper_quartile", 3 * (len(examples) - 1) // 4)):
            references.append({"label": label, **examples[index]})
    recipes = [
        {
            "id": "repeatable-contact",
            "title": "Repeatable contact baseline",
            "goal": "Measure return consistency on a predictable feed before introducing variation.",
            "evidence": f"{len(examples)} paired player rally contacts available in single-attempt, bounded points of completed matches. "
                        "These establish examples to inspect, not a diagnosed stroke weakness.",
            "sequence": [
                {"feed": 1, "launch_origin": "supplied template origin",
                 "landing_target": "verify the template landing region in-game",
                 "spin": "supplied template spin; reduce in-game if needed", "variation": "off"}
            ],
            "ordering": "repeat",
            "cadence": "Begin at a comfortable recovery interval; 2 seconds per launch is an initial coaching suggestion.",
            "volume": "3 sets of 20 feeds; rest between sets as needed.",
            "success": "Count legal returns onto the far half out of 20; record target-zone hits separately.",
            "progression": "After at least 16 legal returns in each of two consecutive sets, change only one parameter.",
            "method_sources": [SOURCES[0]["url"]],
        },
        {
            "id": "two-location-recovery",
            "title": "Two-location recovery",
            "goal": "Practice contact consistency while moving between two manageable locations.",
            "evidence": "A general progression from the baseline drill; not a claim that footwork caused recorded losses.",
            "sequence": [
                {"feed": 1, "launch_origin": "supplied template origin", "landing_target": "aim offset -4 from template; calibrate a comfortable target",
                 "spin": "same as baseline", "variation": "off"},
                {"feed": 2, "launch_origin": "supplied template origin", "landing_target": "aim offset +4 from template; calibrate a second target",
                 "spin": "same as baseline", "variation": "off"},
            ],
            "ordering": "alternate 1, 2",
            "cadence": "Slow enough to recover comfortably; adjust secondsPerLaunch before increasing placement width.",
            "volume": "3 sets of 20 feeds, alternating targets.",
            "success": "Record legal-return totals separately for left and right feeds.",
            "progression": "Meet the baseline accuracy target, then add small placement spread; only later enable shuffle.",
            "method_sources": [SOURCES[0]["url"]],
        },
        {
            "id": "controlled-variation",
            "title": "Controlled placement variation",
            "goal": "Transfer the repeatable feed to a small range of incoming placements.",
            "evidence": "A general controlled-to-variable progression, not evidence of a specific stroke weakness. "
                        "The supplied forehand-drive template is not a serve template.",
            "sequence": [
                {"feed": 1, "launch_origin": "supplied template origin",
                 "landing_target": "small range around the calibrated baseline location",
                 "spin": "same as baseline", "variation": "horizontal aim spread 1.5; all other spread zero"}
            ],
            "ordering": "repeat with one varied parameter before mixing two calibrated templates",
            "cadence": "Use the baseline launch interval; change placement variation before increasing frequency.",
            "volume": "2 sets of 20 predictable feeds, followed by 20 varied feeds if accuracy remains stable.",
            "success": "Count legal returns and intended return placements; keep predictable and varied scores separate.",
            "progression": "Increase one placement control at a time, then mix calibrated templates with shuffle.",
            "method_sources": [SOURCES[0]["url"], SOURCES[1]["url"]],
        },
    ]
    priorities = profile.get("training_plan", [])
    links: dict[str, list[dict[str, Any]]] = {}
    for priority in priorities:
        if priority.get("category_id") is None:
            continue
        for recipe_id in priority["recipe_ids"]:
            links.setdefault(recipe_id, []).append({
                "priority": priority["priority"], "category_id": priority["category_id"],
                "focus": priority["focus"], "evidence": priority["evidence"],
            })
    if "serve-legality" in links:
        recipes.append({
            "id": "serve-legality", "title": "Legal-serve consistency (manual serve practice)",
            "goal": "Reduce point-losing serve faults without confusing them with all serve attempts.",
            "evidence": "", "sequence": [
                {"feed": 1, "launch_origin": "your own toss in serve-practice mode",
                 "landing_target": "legal near-side then far-side bounces",
                 "spin": "one familiar serve; increase only after consistency", "variation": "off initially"}
            ],
            "ordering": "repeat one self-served pattern",
            "cadence": "Self-paced; fully reset between serves.",
            "volume": "3 sets of 20 serve attempts; record legal and failed attempts separately.",
            "success": "Count serves with both required bounces legal out of 20.",
            "progression": "After at least 18 legal serves in two consecutive sets, change only one spin or placement variable. "
                           "These targets are coaching suggestions.",
            "method_sources": [],
            "settings_candidate_available": False,
            "setup_note": "Use manual serve practice. No compatible self-serve machine settings are generated.",
        })
    if "serve-reception" in links:
        recipes.append({
            "id": "serve-reception", "title": "Serve-return consistency (manual template selection)",
            "goal": "Put a selected incoming serve back onto the table before adding variation.",
            "evidence": "", "sequence": [
                {"feed": 1, "launch_origin": "an existing calibrated serve template selected in-game",
                 "landing_target": "one repeatable legal serve location",
                 "spin": "selected manually; not inferred from raw rotation vectors", "variation": "low initially"}
            ],
            "ordering": "one predictable serve template, then controlled variation",
            "cadence": "Allow time to return to your receiving position between feeds.",
            "volume": "3 sets of 20 feeds; record predictable and varied results separately.",
            "success": "Count legal returns out of feed attempts, then track target-zone returns.",
            "progression": "After 16 legal returns in each of two consecutive sets, add a small amount of one variation.",
            "method_sources": [SOURCES[1]["url"]],
            "settings_candidate_available": False,
            "setup_note": "The supplied forehand-drive example is not a serve feed. No serve settings are fabricated from it.",
        })
    for recipe in recipes:
        recipe["training_priorities"] = links.get(recipe["id"], [])
        recipe.setdefault("settings_candidate_available", True)
        if recipe["training_priorities"]:
            recipe["evidence"] = " ".join(link["evidence"] for link in recipe["training_priorities"])
            recipe["recommendation_status"] = "linked_to_observed_losses"
        else:
            recipe["recommendation_status"] = "optional_progression_not_a_loss_diagnosis"
    recipes.sort(key=lambda recipe: (
        min((link["priority"] for link in recipe["training_priorities"]), default=999),
        recipe["id"],
    ))
    candidates = candidate_settings()
    for candidate in candidates:
        candidate["training_priorities"] = links.get(candidate["recipe_id"], [])
    collections = build_collections(candidates, serve_template, links)
    candidates.extend(training_candidates(profile, candidates))
    for recipe in recipes:
        recipe["collection_ids"] = [c["id"] for c in collections if recipe["id"] in c["recipe_ids"]]
        if recipe["id"] == "serve-reception" and serve_template:
            recipe["settings_candidate_available"] = True
            recipe["setup_note"] = "The serve-return collection uses a game-default Serve seed with source provenance. "
            recipe["setup_note"] += "Calibrate it in-game; it is not a measured reproduction of the opponent's serve."
    return {
        "format": "11analyst.manual-practice-recipes",
        "version": 1,
        "game_importable": False,
        "player_id": profile["player"]["id"],
        "status": "manual calibration required",
        "settings_candidates": candidates,
        "collections": collections,
        "methodology_sources": SOURCES,
        "compatibility": [
            "Current supplied logs contain BallLauncherDeviceSettings with shots.data, not the legacy drills.default layout described online.",
            "Observed controls include position.raw/spread, direction.raw/spread, spin.raw/spread, "
            "speedAndRate.raw/spread (speed and secondsPerLaunch), timeScale, and shuffle.",
            "Ball rotation-rate vectors and collision positions are NOT machine spin-slider values or launch positions.",
            "Serve collections require a provenance-backed game-default Serve seed; a rally feed is never relabeled as a serve. "
            "If the seed is missing, serve and combined collections are explicitly unavailable.",
            "Candidate settings follow the user-supplied shots.data shape, including PostDelay and string-valued numbers/booleans. "
            "This validates structure, not in-game import compatibility, physical trajectory, or shot ordering.",
            "No game settings file is overwritten, no cloud drill code is generated, and no account or log data is uploaded.",
        ],
        "calibration_steps": [
            "Back up/export existing machine settings before editing them in-game.",
            "Create or duplicate a familiar feed in the current in-game editor; verify a legal bounce and comfortable pace.",
            "Use the recipe's landing locations as visual targets; left/right are from your playing perspective, not forehand/backhand labels.",
            "Adjust launch position, aim, speed, spin, and launch interval one at a time; start with zero or small spread.",
            "Treat raw incoming-ball examples as analysis references only. Their contact states cannot be pasted into launcher controls.",
            "Record successes out of attempted feeds, then add variation only after a repeatable baseline.",
        ],
        "raw_contact_reference_samples": references,
        "priority_policy": "Recipe links follow observed point-loss priorities. Numeric launcher values remain the supplied seed, "
                           "not fitted physics or a guaranteed replay of the failure.",
        "recipes": recipes,
        "limits": "The recipes and numeric practice targets are coaching proposals, not validated prescriptions. "
                  "A machine does not react to your returns. Game import and exact replay require in-game calibration and format validation.",
    }


def render_section(
    practice: dict[str, Any], table: Callable[[list[str], list[list[Any]]], str],
    escape: Callable[..., str],
) -> str:
    parts = [
        "<h2>Ball-machine practice patterns</h2>",
        "<p><strong>Manual recipes, not a game-importable settings file.</strong> "
        "The separate practice_patterns.json file contains editable sequences and calibration steps. "
        "The candidate files below follow the supplied game-settings shape but have not been tested in Eleven.</p>",
        "<ol>" + "".join(f"<li>{escape(step)}</li>" for step in practice["calibration_steps"]) + "</ol>",
    ]
    parts.append("<h3>Three training collections</h3>")
    for collection in practice["collections"]:
        label = escape(collection["title"])
        if collection["settings_path"]:
            label = f'<a href="{escape(collection["settings_path"], quote=True)}">{label}: collection candidate JSON</a>'
        parts.append(f"<p><strong>{label}</strong><br>Planned feeds: "
                     f"{escape(' -> '.join(collection['planned_sequence']))}. "
                     f"Status: {escape(collection['status'])}. {escape(collection['notes'])}</p>")
        if collection["training_priorities"]:
            parts.append("<p>Supports training priorities: " + ", ".join(
                str(link["priority"]) for link in collection["training_priorities"]
            ) + "</p>")
    parts.append("<details><summary>Individual feed variations and collection settings details</summary>")
    for candidate in practice["settings_candidates"]:
        parts.append(f'<p><a href="{escape(candidate["path"], quote=True)}">{escape(candidate["title"])}: candidate settings JSON</a>'
                     f'<br>{escape(candidate["changes_from_seed"])}</p>')
    parts.append("</details>")
    for recipe in practice["recipes"]:
        parts.append(f'<h3 id="practice-{escape(recipe["id"], quote=True)}">{escape(recipe["title"])}</h3>')
        if recipe["training_priorities"]:
            parts.append("<p><strong>Supports training priorities: " + ", ".join(
                str(link["priority"]) for link in recipe["training_priorities"]
            ) + "</strong></p>")
        else:
            parts.append("<p>Optional progression, not a diagnosed loss priority.</p>")
        if recipe.get("setup_note"):
            parts.append(f"<p>{escape(recipe['setup_note'])}</p>")
        for key in ("goal", "evidence", "ordering", "cadence", "volume", "success", "progression"):
            parts.append(f"<p><strong>{key.title()}:</strong> {escape(recipe[key])}</p>")
        parts.append(table(["Feed", "Launch origin", "Landing target", "Spin", "Variation"], [
            [feed["feed"], feed["launch_origin"], feed["landing_target"], feed["spin"], feed["variation"]]
            for feed in recipe["sequence"]
        ]))
    parts.append("<h3>Research and compatibility</h3><ul>")
    for source in practice["methodology_sources"]:
        parts.append(f'<li><a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a>: '
                     f'{escape(source["supports"])} {escape(source["caveat"])}</li>')
    parts.extend(f"<li>{escape(note)}</li>" for note in practice["compatibility"])
    parts.append(f"</ul><p>{escape(practice['limits'])}</p>")
    return "\n".join(parts)
