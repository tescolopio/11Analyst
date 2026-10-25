"""Import manual 11 Hero shot exports without treating them as local-log evidence."""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import UUID


LOG = logging.getLogger("11analyst.hero")
VERSION = "hero-import-1"
MAX_BYTES = 32 * 1024 * 1024
NUMBERS = (
    "posX", "posY", "posZ", "velX", "velY", "velZ", "velSqrt",
    "rrateX", "rrateY", "rrateZ", "rrateSqrt", "rallyCount",
    "bmPosX", "bmPosY", "bmPosZ", "bmBasePosX", "bmBasePosY", "bmBasePosZ",
    "bmSpeed", "bmAngleHorizontal", "bmAngleVertical",
    "bmSpinTopBottom", "bmSpinLeftRight", "bmSpinScrew",
)
BOOLEANS = ("playerIsHome", "isSuccess", "isWinningShot", "isOpenUpShot", "isServe", "isServeAce", "isServeSuccess")
LABELS = {
    "contactType": {"Toss", "Hit"},
    "shotType": {"Toss", "Serve", "Drive", "Push", "Chop", "SlowLoop", "FastLoop"},
    "spinDirection": {"None", "BottomLeft", "BottomRight", "Bottom", "TopLeft", "TopRight", "Top", "Left", "Right"},
    "direction": {"Mid", "Left", "Right"}, "distance": {"Short", "Mid", "Long"}, "height": set(),
}
LIMITS = [
    "Hero exports are uploaded coverage, not complete account history. Match completeness and terminal point outcomes are unknown.",
    "Provider shot/spin labels and success/serve flags are retained annotations, not independently validated Analyst classifications or point-loss reasons.",
    "Tosses are not racket shots or return attempts, even when the provider marks isServe=true.",
    "Export point IDs are groups, not validated scoring transitions. Scores/participants supplied in a manifest are separately declared metadata.",
    "Axes, vector units, speed/spin magnitudes and event timing are uncalibrated. No conversion to the illustrative spin frame is performed.",
    "No paired incoming states, table/net collisions, engine ticks or paddle pose are invented. bm fields are not enabled machine feeds.",
    "Hero UUIDs are not local game IDs. Cross-source reconciliation is pending; Hero data is excluded from local denominators, rankings and publishing eligibility.",
    "Revisions are retained without silently selecting changed evidence. Inspect each revision; do not add their counts together.",
]


def identifier(value: Any, *, player: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Identifier must be a string or integer")
    result = str(value)
    if not result or result.strip() != result or len(result) > 200:
        raise ValueError("Invalid identifier")
    if player and not re.fullmatch(r"[1-9]\d*", result):
        raise ValueError("Player ID must be a positive integer")
    return result


def timestamp(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", value
    ):
        raise ValueError("Timestamp must be ISO 8601 with an explicit timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp timezone is missing")
    return value


def finite_tree(value: Any) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if not math.isfinite(value):
                raise ValueError("Nonfinite number")
        except OverflowError as error:
            raise ValueError("Number exceeds finite range") from error
    if isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object field: {key}")
        result[key] = value
    return result


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def read_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Input exceeds {MAX_BYTES} bytes: {path.name}")
    return raw


def manifest_entries(path: Path, player_id: str) -> list[dict[str, Any]]:
    manifest = json.loads(read_bytes(path).decode("utf-8-sig"), object_pairs_hook=unique_object)
    finite_tree(manifest)
    if (not isinstance(manifest, dict) or set(manifest) != {"format", "version", "player_id", "matches"}
            or manifest.get("format") != "11analyst.hero-manifest"
            or type(manifest.get("version")) is not int or manifest["version"] != 1
            or identifier(manifest.get("player_id"), player=True) != player_id
            or not isinstance(manifest.get("matches"), list) or not manifest["matches"]):
        raise ValueError("Invalid Hero manifest format, version, player or matches")
    entries = []
    for entry in manifest["matches"]:
        if not isinstance(entry, dict) or set(entry) - {
            "file", "provider_match_id", "source_url", "retrieved_at", "participant_ids", "discovery_name", "metadata"
        }:
            raise ValueError("Invalid Hero manifest entry fields")
        match_id = str(UUID(identifier(entry.get("provider_match_id"))))
        if entry["provider_match_id"] != match_id:
            raise ValueError("Provider match ID must be a canonical UUID string")
        source_url = entry.get("source_url")
        if source_url is not None and source_url != f"https://11hero.com/matches/{match_id}":
            raise ValueError("Source URL must identify the declared Hero match")
        retrieved = entry.get("retrieved_at")
        if retrieved is not None:
            timestamp(retrieved)
        participants = entry.get("participant_ids")
        if participants is not None:
            if not isinstance(participants, list):
                raise ValueError("participant_ids must be an array or null")
            participants = [identifier(value, player=True) for value in participants]
            if len(participants) != 2 or len(set(participants)) != 2 or player_id not in participants:
                raise ValueError("Declare two distinct participants including the target player, or use null")
        discovery_name = entry.get("discovery_name")
        if discovery_name is not None and not isinstance(discovery_name, str):
            raise ValueError("discovery_name must be a string or null")
        metadata = entry.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object or null")
        if not isinstance(entry.get("file"), str) or not entry["file"].strip():
            raise ValueError("Each match needs an exported file path")
        source = Path(entry["file"])
        if not source.is_absolute():
            source = path.parent / source
        entries.append({
            "path": source.resolve(), "provider_match_id": match_id, "source_url": source_url,
            "retrieved_at": retrieved, "participant_ids": participants, "discovery_name": discovery_name,
            "metadata": metadata,
        })
    return entries


def normalize_row(row: Any, index: int, entry: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(row, dict):
        raise ValueError("Shot row must be an object")
    finite_tree(row)
    shot_id = identifier(row.get("id"))
    point_id = identifier(row.get("pointId"))
    player_id = identifier(row.get("playerId"), player=True)
    if entry["participant_ids"] is not None and player_id not in entry["participant_ids"]:
        raise ValueError("Row player is not a declared participant")
    begin_at = timestamp(row.get("beginAt"))
    if not isinstance(row.get("contactType"), str) or not row["contactType"]:
        raise ValueError("contactType must be a nonempty string")
    for field in NUMBERS:
        value = row.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{field} must be a finite JSON number or null")
    if row.get("rallyCount") is not None and (
        not isinstance(row["rallyCount"], int) or row["rallyCount"] < 0
    ):
        raise ValueError("rallyCount must be a nonnegative integer or null")
    for field in BOOLEANS:
        if row.get(field) is not None and type(row[field]) is not bool:
            raise ValueError(f"{field} must be a boolean or null")
    warnings = []
    for field, known in LABELS.items():
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string or null")
        if value is not None and value not in known:
            warnings.append(f"Unrecognized provider {field}; retained without interpretation")
    vectors = {}
    for prefix in ("pos", "vel", "rrate"):
        values = [row.get(prefix + axis) for axis in "XYZ"]
        vectors[prefix] = values if all(value is not None for value in values) else None
        if vectors[prefix] is None:
            warnings.append(f"{prefix} vector incomplete or unavailable; original components retained")
    return {
        "provider_key": [entry["provider_match_id"], shot_id],
        "point_key": [entry["provider_match_id"], point_id],
        "row_index": index, "id": shot_id, "point_id": point_id, "player_id": player_id,
        "begin_at": begin_at, "contact_type": row["contactType"],
        "provider_fields": row, "numeric_vectors": vectors,
        "provider_labels": {field: row.get(field) for field in LABELS if field != "contactType"},
        "provider_annotations": {field: row.get(field) for field in (*BOOLEANS, "rallyCount")},
        "analyst_labels": None, "return_outcome": None, "point_outcome": None,
        "machine_key_eligible": False,
    }, warnings


def parse_export(raw: bytes, entry: dict[str, Any], player_id: str) -> dict[str, Any]:
    result = {
        "source_kind": "hero_export", "importer_version": VERSION,
        "provider_match_id": entry["provider_match_id"], "target_player_id": player_id,
        "original_filename": entry["path"].name, "sha256": hashlib.sha256(raw).hexdigest(),
        "source_url": entry["source_url"], "retrieved_at": entry["retrieved_at"],
        "declared_participant_ids": entry["participant_ids"], "discovery_name": entry["discovery_name"],
        "declared_metadata": entry["metadata"], "metadata_provenance": "manual_manifest_unverified",
        "frame_status": "provider_frame_unvalidated", "units_status": "provider_units_unvalidated",
        "event_timing_status": "provider_beginAt_preserved_semantics_unverified",
        "completeness": "unknown", "outcome_evidence": "provider_flags_only",
        "crosswalk": None, "included_in_local_analysis": False,
        "records": [], "rejected_rows": [], "diagnostics": [], "duplicate_rows": 0,
        "input_rows": None, "status": "rejected",
    }
    try:
        rows = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
        if not isinstance(rows, list):
            raise ValueError("Export root must be an array")
    except (UnicodeError, ValueError, RecursionError) as error:
        result["diagnostics"].append({"level": "error", "row_index": None, "message": str(error)})
        return result
    result["input_rows"] = len(rows)
    raw_ids = defaultdict(set)
    for row in rows:
        if isinstance(row, dict):
            try:
                raw_id = identifier(row.get("id"))
            except ValueError:
                continue
            raw_ids[raw_id].add(json.dumps(row, sort_keys=True, ensure_ascii=True))
    conflicts = {key for key, variants in raw_ids.items() if len(variants) > 1}
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        try:
            if isinstance(row, dict) and identifier(row.get("id")) in conflicts:
                raise ValueError("Conflicting provider ID; every conflicting row quarantined")
            record, warnings = normalize_row(row, index, entry)
        except (ValueError, RecursionError) as error:
            result["rejected_rows"].append({"row_index": index, "message": str(error)})
            continue
        groups[record["id"]].append(record)
        result["diagnostics"].extend({"level": "warning", "row_index": index, "message": text} for text in warnings)
    for group in groups.values():
        result["records"].append(group[0])
        result["duplicate_rows"] += len(group) - 1
    result["records"].sort(key=lambda row: row["row_index"])
    observed = sorted({row["player_id"] for row in result["records"]})
    result["observed_participant_ids"] = observed
    if player_id not in observed:
        result["diagnostics"].append({"level": "error", "row_index": None, "message": "Target player absent from accepted rows"})
    if len(observed) > 2:
        result["diagnostics"].append({"level": "error", "row_index": None, "message": "More than two participants; match identity unresolved"})
    home_by_player = defaultdict(set)
    for row in result["records"]:
        value = row["provider_annotations"]["playerIsHome"]
        if value is not None:
            home_by_player[row["player_id"]].add(value)
    if any(len(values) > 1 for values in home_by_player.values()) or (
        len(home_by_player) == 2 and len(set.union(*home_by_player.values())) == 1
    ):
        result["diagnostics"].append({"level": "warning", "row_index": None, "message": "Contradictory provider home/away attribution"})
    result["counts"] = {
        "accepted_rows": len(result["records"]), "hits": sum(row["contact_type"] == "Hit" for row in result["records"]),
        "tosses": sum(row["contact_type"] == "Toss" for row in result["records"]),
        "other_contacts": sum(row["contact_type"] not in ("Hit", "Toss") for row in result["records"]),
        "point_groups": len({row["point_id"] for row in result["records"]}),
        "target_rows": sum(row["player_id"] == player_id for row in result["records"]),
        "opponent_rows": sum(row["player_id"] != player_id for row in result["records"]),
        "rejected_rows": len(result["rejected_rows"]),
    }
    result["status"] = "imported_with_diagnostics" if (
        result["rejected_rows"] or result["diagnostics"] or result["duplicate_rows"]
    ) else "imported"
    if not result["records"] or any(item["level"] == "error" for item in result["diagnostics"]):
        result["status"] = "rejected"
    return result


def empty_evidence(player_id: str) -> dict[str, Any]:
    return {"format": "11analyst.hero-evidence", "version": 1, "player_id": player_id,
            "revisions": [], "limits": list(LIMITS)}


def load_evidence(output: Path, player_id: str) -> dict[str, Any]:
    result = empty_evidence(player_id)
    path = output / "hero_imports.sqlite3"
    if not path.exists():
        return result
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unsupported Hero archive version")
        rows = db.execute(
            "SELECT data_json FROM hero_revisions WHERE player_id=? ORDER BY imported_at, revision_id", (player_id,)
        ).fetchall()
    result["revisions"] = [json.loads(row[0]) for row in rows]
    return result


def refresh_outputs(output: Path, player_id: str) -> None:
    import analyst
    import loss_analysis
    profile_path = output / "profile.json"
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if profile["player"]["id"] != player_id:
            raise ValueError("Output profile belongs to another player; use a separate output directory")
    else:
        profile = analyst.make_profile([], [], player_id)
        loss_analysis.attach(profile)
        analyst.atomic_text(profile_path, json.dumps(profile, indent=2, allow_nan=False) + "\n")
    evidence = load_evidence(output, player_id)
    analyst.atomic_text(output / f"hero_evidence.{player_id}.json", json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    analyst.atomic_text(output / "report.html", analyst.render_html(profile, hero_evidence=evidence))


def import_manifest(manifest: Path, output: Path, player_id: str) -> dict[str, Any]:
    player_id = identifier(player_id, player=True)
    entries = manifest_entries(manifest, player_id)
    if (output / "profile.json").exists():
        profile = json.loads((output / "profile.json").read_text(encoding="utf-8"))
        if profile["player"]["id"] != player_id:
            raise ValueError("Output profile belongs to another player; use a separate output directory")
    output.mkdir(parents=True, exist_ok=True)
    summary = {"declared_files": len(entries), "imported_revisions": 0, "unchanged_files": 0, "failed_files": 0,
               "accepted_rows": 0, "rejected_rows": 0, "duplicate_rows": 0}
    with closing(sqlite3.connect(output / "hero_imports.sqlite3")) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("Unsupported Hero archive version")
        db.execute("CREATE TABLE IF NOT EXISTS hero_revisions (revision_id TEXT PRIMARY KEY, player_id TEXT NOT NULL, match_id TEXT NOT NULL, imported_at TEXT NOT NULL, raw_json BLOB NOT NULL, data_json TEXT NOT NULL)")
        db.execute("PRAGMA user_version=1")
        db.commit()
        for entry in entries:
            try:
                raw = read_bytes(entry["path"])
            except (OSError, ValueError) as error:
                LOG.error("Could not read %s: %s", entry["path"].name, error)
                summary["failed_files"] += 1
                continue
            result = parse_export(raw, entry, player_id)
            identity = {key: value for key, value in result.items() if key not in {
                "records", "rejected_rows", "diagnostics", "counts", "duplicate_rows", "input_rows",
                "status", "observed_participant_ids"
            }}
            revision_id = hashlib.sha256(json_text(identity).encode("utf-8")).hexdigest()
            existing = db.execute("SELECT data_json FROM hero_revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if existing:
                summary["unchanged_files"] += 1
            else:
                result["revision_id"] = revision_id
                result["imported_at"] = datetime.now(timezone.utc).isoformat()
                prior = db.execute("SELECT count(*) FROM hero_revisions WHERE player_id=? AND match_id=?",
                                   (player_id, entry["provider_match_id"])).fetchone()[0]
                result["revision_number"] = prior + 1
                with db:
                    db.execute("INSERT INTO hero_revisions VALUES (?,?,?,?,?,?)", (
                        revision_id, player_id, entry["provider_match_id"], result["imported_at"], raw, json_text(result)
                    ))
                summary["imported_revisions"] += 1
            summary["accepted_rows"] += len(result["records"])
            summary["rejected_rows"] += len(result["rejected_rows"])
            summary["duplicate_rows"] += result["duplicate_rows"]
            if result["status"] != "imported":
                LOG.warning("%s: %s; %d rejected rows, %d diagnostics, %d duplicate rows",
                            entry["path"].name, result["status"], len(result["rejected_rows"]),
                            len(result["diagnostics"]), result["duplicate_rows"])
            for diagnostic in [*result["diagnostics"], *result["rejected_rows"]]:
                LOG.warning("Row %s: %s", diagnostic.get("row_index"), diagnostic["message"])
            if result["status"] == "rejected" or result["rejected_rows"]:
                summary["failed_files"] += 1
    refresh_outputs(output, player_id)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--player-id", required=True)
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = import_manifest(args.manifest, args.output, args.player_id)
    except (OSError, ValueError, sqlite3.Error) as error:
        LOG.error("Hero import failed: %s", error)
        return 1
    LOG.info("Hero import summary: %s", json_text(result))
    return 1 if result["failed_files"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
