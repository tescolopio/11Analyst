from copy import deepcopy
from email.message import Message
import http.client
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

import cloud_publish
import dashboard
import practice
import serve
import test_dashboard
from test_loss_analysis import point


def profile_fixture():
    profile = test_dashboard.DashboardTests().make_profile()
    for match in profile["matches"]:
        match["observed_points"] = [point(index) for index in range(1, 4)]
    profile["practice_patterns"] = practice.build(profile)
    return profile


class FakeHero(cloud_publish.HeroClient):
    def __init__(self):
        self.rows = {"1": {"unrelated": True}}
        self.posts = []
        self.reads = 0
        self.mode = "normal"

    def listing(self):
        self.reads += 1
        return set(self.rows)

    def upload(self, settings):
        self.posts.append(deepcopy(settings))
        self.rows["2"] = deepcopy(settings)
        if self.mode == "timeout":
            raise cloud_publish.CloudError("Timed out after accepting settings")
        if self.mode == "mismatch":
            self.rows["2"]["ballCount"] = "99"
        if self.mode == "concurrent":
            self.rows["999"] = {"someone": "else"}
        if self.mode == "duplicate":
            self.rows["3"] = deepcopy(settings)

    def download(self, identifier):
        self.reads += 1
        return deepcopy(self.rows[identifier])


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.profile = profile_fixture()
        self.client = FakeHero()
        self.publisher = cloud_publish.Publisher(self.profile, self.output, self.client)
        self.candidate = self.publisher.catalog["plan-shot-landing"]
        self.digest = practice.settings_digest(self.candidate["settings"])
        sleep = patch("cloud_publish.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def publish(self, **kwargs):
        return self.publisher.publish("plan-shot-landing", self.digest, True, **kwargs)

    def test_no_external_requests_on_startup(self):
        self.assertEqual(self.publisher.summaries(), [])
        self.assertEqual(self.client.posts, [])
        self.assertEqual(self.client.reads, 0)
        self.assertFalse(self.publisher.path.exists())

    def test_only_explicit_current_collection_can_upload(self):
        for identifier, digest, consent in [
            ("plan-shot-landing", self.digest, False), ("plan-shot-landing", self.digest, 1),
            ("plan-shot-landing", "outdated", True), ("not-generated", self.digest, True),
            ("rally-practice", self.digest, True), ("plan-serve-legality", self.digest, True),
            ("opponent-2-serve", self.digest, True),
        ]:
            with self.assertRaises(ValueError):
                self.publisher.publish(identifier, digest, consent)
        self.assertEqual(self.client.posts, [])
        self.assertEqual(self.client.reads, 0)

    def test_payload_excludes_private_metadata_and_tracks_distinct_published_revision(self):
        source = deepcopy(self.candidate)
        source["settings"]["secret"] = "PRIVATE_SENTINEL"
        source["settings"]["shots"]["data"]["ANLY01"]["Description"] = "PRIVATE_SENTINEL"
        source["settings"]["shots"]["data"]["ANLY01"]["source_path"] = "PRIVATE_SENTINEL"
        source["title"] = "PRIVATE_SENTINEL"
        payload = cloud_publish.publication_settings(source, "publication-tag")
        text = json.dumps(payload)
        self.assertNotIn("PRIVATE_SENTINEL", text)
        self.assertIn("publication-tag", text)
        self.assertEqual(payload["shots"]["data"]["ANLY01"]["position"],
                         source["settings"]["shots"]["data"]["ANLY01"]["position"])
        self.assertNotEqual(practice.settings_digest(payload), self.digest)
        self.assertEqual(source["settings"]["secret"], "PRIVATE_SENTINEL")

    def test_readback_match_not_highest_id_and_journal_persists(self):
        self.client.mode = "concurrent"
        result = self.publish()
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["key"], "54334.2")
        self.assertNotIn("settings", result)
        self.assertNotIn("before_ids", result)
        self.assertEqual(len(self.client.posts), 1)
        journal = self.publisher.load()
        self.assertEqual(journal["publications"][0]["key"], "54334.2")

    def test_restart_reuses_verified_key_without_network(self):
        first = self.publish()
        replacement = FakeHero()
        publisher = cloud_publish.Publisher(self.profile, self.output, replacement)
        self.assertEqual(publisher.publish("plan-shot-landing", self.digest, True), first)
        self.assertEqual(replacement.posts, [])
        self.assertEqual(replacement.reads, 0)

    def test_journal_written_before_post(self):
        original = self.client.upload
        def check(settings):
            stored = self.publisher.load()["publications"][0]
            self.assertEqual(stored["status"], "uncertain")
            self.assertEqual(stored["settings"], settings)
            original(settings)
        self.client.upload = check
        self.publish()

    def test_timeout_does_not_retry_and_can_be_rechecked_after_restart(self):
        self.client.mode = "timeout"
        result = self.publish()
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["key"])
        self.assertEqual(self.publish(), result)
        self.assertEqual(len(self.client.posts), 1)
        restarted = cloud_publish.Publisher(self.profile, self.output, self.client)
        checked = restarted.publish("plan-shot-landing", self.digest, True, recheck=True)
        self.assertEqual(checked["key"], "54334.2")
        self.assertEqual(len(self.client.posts), 1)

    def test_mismatch_and_multiple_matches_never_produce_a_key(self):
        for mode in ("mismatch", "duplicate"):
            with self.subTest(mode=mode):
                if self.publisher.path.exists():
                    self.publisher.path.unlink()
                self.client = FakeHero()
                self.client.mode = mode
                self.publisher.client = self.client
                result = self.publish()
                self.assertEqual(result["status"], "uncertain")
                self.assertIsNone(result["key"])
                self.assertTrue(result["error"])

    def test_recheck_never_creates_an_upload(self):
        with self.assertRaises(ValueError):
            self.publish(recheck=True)
        self.assertEqual(self.client.posts, [])

    def test_old_revision_can_be_rechecked_without_reupload(self):
        self.client.mode = "timeout"
        self.publish()
        self.publisher.catalog["plan-shot-landing"]["settings"]["ballCount"] = "6"
        result = self.publish(recheck=True)
        self.assertEqual(result["key"], "54334.2")
        self.assertEqual(len(self.client.posts), 1)

    def test_historical_collection_recheck_survives_catalog_change(self):
        self.client.mode = "timeout"
        self.publish()
        journal = self.publisher.load()
        journal["publications"][0]["collection_id"] = "rally-practice"
        self.publisher.save(journal)
        result = self.publisher.publish("rally-practice", self.digest, True, recheck=True)
        self.assertEqual(result["key"], "54334.2")
        self.assertEqual(len(self.client.posts), 1)

    def test_stale_plan_metadata_cannot_bypass_evidence_threshold(self):
        for match in self.profile["matches"]:
            match["observed_points"] = []
        publisher = cloud_publish.Publisher(self.profile, self.output, self.client)
        self.assertEqual(publisher.catalog, {})
        with self.assertRaises(ValueError):
            publisher.publish("plan-shot-landing", self.digest, True)
        self.assertEqual(self.client.posts, [])

    def test_published_plan_preserves_stage_activation(self):
        self.publish()
        self.assertEqual([shot["isActive"] for shot in self.client.posts[0]["shots"]["data"].values()],
                         ["True", "False"])

    def test_failed_durable_write_prevents_the_post(self):
        with patch.object(self.publisher, "save", side_effect=OSError("Disk full")):
            with self.assertRaises(cloud_publish.CloudError):
                self.publish()
        self.assertEqual(self.client.posts, [])

    def test_corrupt_journal_is_not_replaced_or_ignored(self):
        self.publisher.path.write_text("{bad", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.publisher.path.read_text(), "{bad")
        self.assertEqual(self.client.posts, [])

    def test_process_lock_prevents_parallel_publishers(self):
        with cloud_publish.journal_lock(self.publisher.path):
            with self.assertRaises(cloud_publish.CloudError):
                self.publish()
        self.assertEqual(self.client.posts, [])

    def test_new_id_limit_is_exactly_twenty(self):
        for count in (20, 21):
            with self.subTest(count=count):
                self.publisher.path.unlink(missing_ok=True)
                client = FakeHero()
                original = client.upload
                def many(settings):
                    original(settings)
                    client.rows.update({str(index): {"unrelated": index} for index in range(3, count + 2)})
                client.upload = many
                self.publisher.client = client
                result = self.publish()
                self.assertEqual(result["status"], "verified" if count == 20 else "uncertain")


class HeroClientTests(unittest.TestCase):
    def test_post_contract_contains_only_json_settings(self):
        client = cloud_publish.HeroClient()
        headers = Message()
        headers["Content-Type"] = "application/json"
        response = io.BytesIO(b'{"message":"success"}')
        response.headers = headers
        with patch.object(client.opener, "open", return_value=response) as send:
            client.upload({"settingsVersion": "1"})
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://11hero.com/api/sendBallMachineToCloud")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"json": {"settingsVersion": "1"}})
        self.assertFalse(request.has_header("Authorization"))
        self.assertFalse(request.has_header("Cookie"))

    def test_redirects_and_unacknowledged_uploads_fail_explicitly(self):
        with self.assertRaises(cloud_publish.CloudError):
            cloud_publish.NoRedirects().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid")
        client = cloud_publish.HeroClient()
        with patch.object(client, "request", return_value={"error": "no"}):
            with self.assertRaises(cloud_publish.CloudError):
                client.upload({})

    def test_listing_validates_shape_and_ids(self):
        client = cloud_publish.HeroClient()
        for value in [{}, {"result": "bad"}, {"result": [["../bad", "0"]]},
                      {"result": [["1", "0"], ["1", "0"]]}, {"result": [[1, "0"]]}]:
            with patch.object(client, "request", return_value=value):
                with self.assertRaises(cloud_publish.CloudError):
                    client.listing()

    def test_json_response_size_boundary_and_content_type(self):
        client = cloud_publish.HeroClient()
        for length in (cloud_publish.MAX_RESPONSE, cloud_publish.MAX_RESPONSE + 1):
            response = io.BytesIO(b"{}" + b" " * (length - 2))
            response.headers = Message()
            response.headers["Content-Type"] = "application/json"
            with patch.object(client.opener, "open", return_value=response):
                if length == cloud_publish.MAX_RESPONSE:
                    self.assertEqual(client.request("GET", "/api/getBallMachineList"), {})
                else:
                    with self.assertRaises(cloud_publish.CloudError):
                        client.request("GET", "/api/getBallMachineList")
        response = io.BytesIO(b"<html>not JSON</html>")
        response.headers = Message()
        response.headers["Content-Type"] = "text/html"
        with patch.object(client.opener, "open", return_value=response):
            with self.assertRaises(cloud_publish.CloudError):
                client.request("GET", "/api/getBallMachineList")


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = FakeHero()
        self.profile = profile_fixture()
        self.server = serve.create_server(self.profile, Path(self.temp.name), 0, self.client)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        status, html, self.headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        data = json.loads(re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, re.S)[1])
        self.token = data["publishing"]["service"]["token"]
        self.digest = data["publishing"]["candidate_sha256"]["plan-shot-landing"]

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode(), dict(response.getheaders())
        finally:
            connection.close()

    def post(self, **changes):
        body = {"collection_id": "plan-shot-landing", "candidate_sha256": self.digest, "consent": True}
        body.update(changes)
        return self.request("POST", "/api/publish", json.dumps(body), {
            "Origin": self.origin, "Content-Type": "application/json", "X-11Analyst-Token": self.token
        })

    def test_offline_stays_offline_and_server_serves_no_arbitrary_files(self):
        self.assertIn("connect-src 'none'", dashboard.render(self.profile))
        _, html, _ = self.request("GET", "/")
        self.assertIn("connect-src 'self'", html)
        self.assertEqual(self.headers["X-Frame-Options"], "DENY")
        self.assertEqual(self.request("GET", "/profile.json")[0], 404)
        self.assertEqual(self.request("GET", "/../11TTLogs")[0], 404)
        self.assertEqual(self.client.posts, [])
        self.assertEqual(self.client.reads, 0)

    def test_origin_host_and_token_guards(self):
        for headers in [
            {"Origin": "https://other.invalid", "X-11Analyst-Token": self.token},
            {"Origin": self.origin}, {"X-11Analyst-Token": self.token},
            {"Origin": self.origin, "X-11Analyst-Token": self.token, "Host": "rebinding.invalid"},
        ]:
            self.assertEqual(self.request("POST", "/api/publish", "{}", headers)[0], 403)
        self.assertEqual(self.request("GET", "/api/publications")[0], 403)
        self.assertEqual(self.client.posts, [])

    def test_consent_stale_revision_and_arbitrary_payload_rejected(self):
        for changes in [{"consent": False}, {"candidate_sha256": "old"}, {"settings": {"unsafe": True}}]:
            self.assertEqual(self.post(**changes)[0], 400)
        self.assertEqual(self.client.posts, [])

    def test_http_publish_readback_and_persistent_receipt(self):
        status, body, _ = self.post()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["key"], "54334.2")
        self.post()
        self.assertEqual(len(self.client.posts), 1)
        status, body, _ = self.request("GET", "/api/publications", headers={"X-11Analyst-Token": self.token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["publications"][0]["status"], "verified")
        self.assertNotIn('"settings":', body)


if __name__ == "__main__":
    unittest.main()
