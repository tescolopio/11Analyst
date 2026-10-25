"""Serve the local dashboard with opt-in 11 Hero publishing. No uploads on startup."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlsplit

import cloud_publish
import dashboard
import hero_import

LOG = logging.getLogger("11analyst.server")


def create_server(profile: dict[str, Any], output: Path, port: int = 18765,
                  client: cloud_publish.HeroClient | None = None) -> ThreadingHTTPServer:
    publisher = cloud_publish.Publisher(profile, output, client)
    hero_evidence = hero_import.load_evidence(output, profile["player"]["id"])
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, message, *args):
            LOG.info("%s %s", self.command, urlsplit(self.path).path)

        def respond(self, status: int, value: Any, *, html: bool = False) -> None:
            raw = value.encode("utf-8") if html else json.dumps(value, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                LOG.warning("Browser disconnected; consult the publication journal before retrying")

        def allowed(self, *, write: bool = False) -> bool:
            authority = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != authority:
                self.respond(403, {"error": "Use the printed 127.0.0.1 address"})
                return False
            origin = self.headers.get("Origin")
            if (origin is not None and origin != "http://" + authority) or (write and origin is None):
                self.respond(403, {"error": "Same-origin browser request required"})
                return False
            if (write or urlsplit(self.path).path.startswith("/api/")) and not secrets.compare_digest(
                self.headers.get("X-11Analyst-Token", ""), token
            ):
                self.respond(403, {"error": "Invalid session token; reload the dashboard"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            try:
                if self.path in ("/", "/report.html"):
                    service = {"token": token, "publications": publisher.summaries()}
                    self.respond(200, dashboard.render(profile, service, hero_evidence), html=True)
                elif self.path == "/api/publications":
                    self.respond(200, {"publications": publisher.summaries()})
                elif self.path == "/health":
                    self.respond(200, {"status": "ready", "automatic_uploads": False})
                else:
                    self.respond(404, {"error": "Not found"})
            except (ValueError, OSError) as exc:
                LOG.exception("Local dashboard read failed")
                self.respond(500, {"error": f"Local data could not be read: {exc}"})

        def do_POST(self):
            if not self.allowed(write=True):
                return
            if self.path not in ("/api/publish", "/api/recheck"):
                self.respond(404, {"error": "Not found"})
                return
            try:
                if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
                    raise ValueError("A bounded application/json request is required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2048:
                    raise ValueError("Request must be between 1 and 2048 bytes")
                self.connection.settimeout(10)
                body = json.loads(self.rfile.read(length))
                if (not isinstance(body, dict) or set(body) != {"collection_id", "candidate_sha256", "consent"}
                        or not isinstance(body["collection_id"], str) or not isinstance(body["candidate_sha256"], str)):
                    raise ValueError("Send only collection_id, candidate_sha256, and explicit consent")
                result = publisher.publish(**{
                    "collection_id": body["collection_id"], "digest": body["candidate_sha256"],
                    "consent": body["consent"], "recheck": self.path == "/api/recheck",
                })
                self.respond(200, result)
            except ValueError as exc:
                LOG.warning("Publishing request rejected: %s", exc)
                self.respond(400, {"error": str(exc)})
            except cloud_publish.CloudError as exc:
                LOG.warning("Publishing service: %s", exc)
                self.respond(502, {"error": str(exc)})
            except OSError:
                LOG.exception("Local publication state or connection failed")
                self.respond(500, {"error": "Local state or connection failed. An upload may have occurred; preserve the journal and reload. Do not re-upload blindly."})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        profile = json.loads((args.output / "profile.json").read_text(encoding="utf-8"))
        with create_server(profile, args.output, args.port) as server:
            print(f"Open http://127.0.0.1:{server.server_port}/#machines", flush=True)
            print("No uploads on startup. Publish only after checking the explicit sharing consent.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                LOG.info("Local server stopped")
    except (ValueError, OSError) as exc:
        LOG.error("Cannot start publishing server: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
