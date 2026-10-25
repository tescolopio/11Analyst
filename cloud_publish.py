"""Opt-in 11 Hero publishing with a durable journal and read-back verification."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from http.client import HTTPException
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

import analyst
import practice

LOG = logging.getLogger("11analyst.cloud")
HERO = "https://11hero.com"
OWNER = "54334"
MAX_RESPONSE = 4 * 1024 * 1024


@contextmanager
def journal_lock(path: Path):
    with path.with_suffix(".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CloudError("Another process is using this publication journal") from exc
        yield


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CloudError(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CloudError("11 Hero redirected the request; redirect was not followed")


class HeroClient:
    def __init__(self) -> None:
        self.opener = build_opener(NoRedirects())

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
        request = Request(HERO + path, data=payload, method=method, headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "11Analyst/1.0",
        })
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise CloudError("11 Hero response exceeded 4 MiB")
                if response.headers.get_content_type() != "application/json":
                    raise CloudError("11 Hero returned a non-JSON response")
                return json.loads(raw)
        except HTTPError as exc:
            raise CloudError(f"11 Hero returned HTTP {exc.code}; no automatic retry") from exc
        except (URLError, TimeoutError, OSError, ValueError, HTTPException) as exc:
            raise CloudError(f"11 Hero request failed ({type(exc).__name__}); no automatic retry") from exc

    def listing(self) -> set[str]:
        response = self.request("GET", "/api/getBallMachineList")
        rows = response.get("result") if isinstance(response, dict) else None
        if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
            or not re.fullmatch(r"\d{1,30}", row[0]) for row in rows
        ):
            raise CloudError("11 Hero returned an invalid settings listing")
        ids = {row[0] for row in rows}
        if len(ids) != len(rows):
            raise CloudError("11 Hero listing contains duplicate IDs")
        return ids

    def upload(self, settings: dict[str, Any]) -> None:
        result = self.request("POST", "/api/sendBallMachineToCloud", {"json": settings})
        if not isinstance(result, dict) or result.get("message") != "success":
            raise CloudError("11 Hero did not acknowledge success; the upload outcome is uncertain")

    def download(self, setting_id: str) -> dict[str, Any]:
        result = self.request("GET", "/api/getBallMachine?" + urlencode({"userID": OWNER, "fileName": setting_id}))
        if not isinstance(result, dict):
            raise CloudError("11 Hero returned invalid settings")
        return result


def publication_settings(candidate: dict[str, Any], publication_id: str) -> dict[str, Any]:
    original = candidate["settings"]
    practice.validate_settings(original)
    shots = {}
    for index, (shot_id, shot) in enumerate(original["shots"]["data"].items(), 1):
        shots[shot_id] = {
            "Description": f"11 Analyst {candidate['recipe_id']}, feed {index}. Publication {publication_id}. Calibrate before training.",
            "DataName": f"11 Analyst {candidate['recipe_id']} {index}",
            "isActive": shot["isActive"],
            **{group: {mode: {field: shot[group][mode][field] for field in fields}
                       for mode in ("raw", "spread")} for group, fields in practice.SETTING_FIELDS.items()},
        }
    settings = practice.settings_root(shots)
    for field in ("settingsVersion", "showBallMachineLauncherAlways", "ballCount", "timeScale", "shuffle"):
        settings[field] = original[field]
    practice.validate_settings(settings)
    return settings


class Publisher:
    def __init__(self, profile: dict[str, Any], output: Path, client: HeroClient | None = None) -> None:
        self.player_id = profile["player"]["id"]
        if not isinstance(self.player_id, str) or not re.fullmatch(r"[1-9]\d*", self.player_id):
            raise ValueError("Invalid player ID")
        self.catalog = {item["recipe_id"]: item for item in practice.training_candidates(profile)}
        for identifier, item in self.catalog.items():
            if not re.fullmatch(r"[a-z0-9-]+", identifier):
                raise ValueError("Invalid collection ID")
            practice.validate_settings(item["settings"])
        self.path = output / f"cloud_publications.{self.player_id}.json"
        self.client = client if client is not None else HeroClient()
        self.lock = threading.Lock()
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "player_id": self.player_id, "publications": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("version") != 1
                or value.get("player_id") != self.player_id or not isinstance(value.get("publications"), list)):
            raise ValueError("Invalid publication journal; preserve it and repair before publishing")
        seen = set()
        for entry in value["publications"]:
            if (not isinstance(entry, dict) or entry.get("status") not in ("uncertain", "verified")
                    or not isinstance(entry.get("id"), str) or entry["id"] in seen
                    or not isinstance(entry.get("collection_id"), str)
                    or not isinstance(entry.get("candidate_sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", entry["candidate_sha256"])
                    or not isinstance(entry.get("before_ids"), list)
                    or any(not isinstance(item, str) or not re.fullmatch(r"\d{1,30}", item) for item in entry["before_ids"])
                    or not isinstance(entry.get("settings"), dict)
                    or entry.get("published_sha256") != practice.settings_digest(entry["settings"])):
                raise ValueError("Invalid publication journal entry; no upload attempted")
            if entry["status"] == "verified" and (
                not isinstance(entry.get("key"), str) or not re.fullmatch(r"54334\.\d{1,30}", entry["key"])
            ):
                raise ValueError("Invalid verified key in publication journal")
            seen.add(entry["id"])
        return value

    def save(self, value: dict[str, Any]) -> None:
        analyst.atomic_text(self.path, json.dumps(value, indent=2, allow_nan=False) + "\n")

    @staticmethod
    def public(entry: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in entry.items() if key not in ("settings", "before_ids")}

    def summaries(self) -> list[dict[str, Any]]:
        return [self.public(entry) for entry in self.load()["publications"]]

    def verify(self, entry: dict[str, Any]) -> None:
        deadline = time.monotonic() + 35
        for attempt in range(3):
            new_ids = self.client.listing() - set(entry["before_ids"])
            if len(new_ids) > 20:
                raise CloudError("More than 20 new settings IDs; cannot safely identify this upload automatically")
            matches = []
            for identifier in sorted(new_ids, key=int):
                if time.monotonic() >= deadline:
                    raise CloudError("Read-back verification timed out; use Recheck, not another upload")
                settings = self.client.download(identifier)
                if practice.settings_digest(settings) == entry["published_sha256"]:
                    matches.append(identifier)
            if len(matches) == 1:
                entry.update(status="verified", key=f"{OWNER}.{matches[0]}", verified_at=now(), error=None)
                return
            if len(matches) > 1:
                raise CloudError("Multiple exact matches; refusing to guess a key")
            if attempt < 2:
                time.sleep(0.5)
        raise CloudError("No exact settings match yet. The upload may exist; use Recheck without re-uploading")

    def publish(self, collection_id: str, digest: str, consent: bool, *, recheck: bool = False) -> dict[str, Any]:
        if consent is not True:
            raise ValueError("Explicit consent to contact 11 Hero is required")
        candidate = self.catalog.get(collection_id)
        if not recheck and (candidate is None or digest != practice.settings_digest(candidate["settings"])):
            raise ValueError("Collection unavailable or revision changed; reload the dashboard")
        if not self.lock.acquire(blocking=False):
            raise CloudError("Another publishing operation is running; wait for it to finish")
        try:
            with journal_lock(self.path):
                return self._publish(collection_id, digest, candidate, recheck)
        finally:
            self.lock.release()

    def _publish(self, collection_id: str, digest: str, candidate: dict[str, Any] | None,
                 recheck: bool) -> dict[str, Any]:
        if candidate is None and not recheck:
            raise ValueError("Collection unavailable")
        try:
            journal = self.load()
            entries = journal["publications"]
            entry = next((item for item in entries if item["collection_id"] == collection_id
                          and item["candidate_sha256"] == digest), None)
            if entry is not None and entry["status"] == "verified":
                return self.public(entry)
            if entry is not None and not recheck:
                return self.public(entry)
            if entry is None:
                if recheck:
                    raise ValueError("No publication exists for this candidate revision")
                before = self.client.listing()
                identifier = uuid4().hex
                settings = publication_settings(candidate, identifier)
                entry = {
                    "id": identifier, "collection_id": collection_id, "provider": "11hero",
                    "candidate_sha256": digest, "published_sha256": practice.settings_digest(settings),
                    "settings": settings, "before_ids": sorted(before, key=int),
                    "created_at": now(), "status": "uncertain", "key": None,
                    "error": "Upload pending or interrupted. Recheck before any further action.",
                }
                entries.append(entry)
                # Persist before the only POST, so a timeout or restart cannot trigger a duplicate.
                self.save(journal)
                try:
                    self.client.upload(settings)
                except CloudError as exc:
                    LOG.warning("Publication %s: %s", entry["id"], exc)
                    entry["error"] = str(exc)
                    self.save(journal)
                    return self.public(entry)
            try:
                self.verify(entry)
            except (CloudError, ValueError) as exc:
                LOG.warning("Publication %s verification: %s", entry["id"], exc)
                entry["error"] = str(exc)
            self.save(journal)
            return self.public(entry)
        except OSError as exc:
            raise CloudError("Publication journal could not be saved. An upload may have occurred. Preserve the journal and recheck; do not start a new upload.") from exc
