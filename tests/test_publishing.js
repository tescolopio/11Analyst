"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const publishing = require("../dashboard/publishing.js");
const player = "1909208";
const hash = "a".repeat(64);
const record = () => ({
  collection_id: "combined", candidate_sha256: hash, key: "1909208.123",
  recorded_at: "2026-10-24T18:00:00.000Z",
  confirmations: {backed_up: true, calibrated: true, uploaded: true}
});
const manifest = () => ({
  format: "11analyst.ball-machine-key-records", version: 1, player_id: player, records: [record()]
});
const storage = () => {
  const values = new Map();
  return {getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
};

test("keys retain the entire settings ID as a string, not a decimal number", () => {
  assert.equal(publishing.parseKey(" 1909208.123 ", player), "1909208.123");
  assert.equal(publishing.parseKey("1909208.10", player), "1909208.10");
  assert.equal(publishing.parseKey("1909208.12345678901234567890", player), "1909208.12345678901234567890");
});

test("invalid keys and keys owned by other accounts are rejected", () => {
  for (const key of ["4008.1", "1909208", "1909208.", "1909208.1.2", "1909208.-1", "1909208.1e3", "01909208.1",
    "1909208.1<script>", "1909208.1\n1909208.2", 1909208.1, null, "1909208." + "1".repeat(100)]) {
    assert.throws(() => publishing.parseKey(key, player));
  }
});

test("backups are validated without mutating their input or retaining arbitrary extra data", () => {
  const input = manifest();
  input.records[0].extra = "not stored";
  const original = structuredClone(input);
  const result = publishing.validateManifest(input, player);
  assert.deepEqual(input, original);
  assert.equal(result.records[0].extra, undefined);
  assert.notEqual(result.records[0], input.records[0]);
});

test("wrong file shapes, player, versions, and duplicate collections are rejected", () => {
  for (const value of [null, [], {}, {...manifest(), version: 2}, {...manifest(), player_id: "4008"},
    {...manifest(), records: {}}, {...manifest(), records: [record(), record()]},
    {...manifest(), records: Array(101).fill(record())}]) {
    assert.throws(() => publishing.validateManifest(value, player));
  }
});

test("invalid record identities, hashes, dates, and incomplete confirmations are rejected", () => {
  for (const changes of [
    {collection_id: "__proto__"}, {collection_id: "<img src=x>"}, {candidate_sha256: "not-a-hash"},
    {candidate_sha256: null}, {recorded_at: "tomorrow"}, {recorded_at: "2026-02-30T18:00:00.000Z"},
    {recorded_at: null}, {confirmations: {backed_up: true, calibrated: false, uploaded: true}},
    {confirmations: {backed_up: true, calibrated: true, uploaded: "True"}}, {key: "4008.48"}
  ]) {
    assert.throws(() => publishing.validateManifest({...manifest(), records: [{...record(), ...changes}]}, player));
  }
});

test("records survive storage reloads and are isolated by player", () => {
  const store = storage();
  assert.deepEqual(publishing.readManifest(store, player).records, []);
  publishing.writeManifest(store, player, manifest());
  assert.deepEqual(publishing.readManifest(store, player), manifest());
  assert.deepEqual(publishing.readManifest(store, "4008").records, []);
});

test("invalid imports leave existing records untouched", () => {
  const store = storage();
  publishing.writeManifest(store, player, manifest());
  assert.throws(() => publishing.writeManifest(store, player, {...manifest(), version: 2}));
  assert.deepEqual(publishing.readManifest(store, player), manifest());
});

test("corrupt stored JSON is explicit and is not silently reset", () => {
  const store = storage(), key = publishing.storageKey(player);
  store.setItem(key, "{bad json");
  assert.throws(() => publishing.readManifest(store, player));
  assert.equal(store.getItem(key), "{bad json");
});

test("storage access and quota failures propagate rather than claim a save", () => {
  assert.throws(() => publishing.readManifest({getItem() { throw new Error("Storage blocked"); }}, player), /Storage blocked/);
  assert.throws(() => publishing.writeManifest({setItem() { throw new Error("Quota exceeded"); }}, player, manifest()), /Quota exceeded/);
});

test("a changed or missing candidate flags the old key without asserting publication", () => {
  assert.match(publishing.statusFor(record(), hash), /user-recorded; cloud unverified/);
  assert.match(publishing.statusFor(record(), "b".repeat(64)), /candidate changed or unavailable/);
  assert.match(publishing.statusFor(record(), undefined), /candidate changed or unavailable/);
  assert.equal(publishing.statusFor(undefined, hash), "No Ball Machine Key recorded");
});

test("empty backups and records for previously generated collections can be retained", () => {
  assert.deepEqual(publishing.validateManifest({...manifest(), records: []}, player).records, []);
  const previous = {...record(), collection_id: "previous-collection"};
  assert.deepEqual(publishing.validateManifest({...manifest(), records: [previous]}, player).records[0], previous);
});

test("11 Hero keys use the service owner, not the training player's ID", () => {
  assert.equal(publishing.parseKey("54334.12", player, "11hero"), "54334.12");
  assert.throws(() => publishing.parseKey("1909208.12", player, "11hero"));
  assert.throws(() => publishing.parseKey("4008.1", player, "11hero"));
  assert.throws(() => publishing.parseKey("54334.12", player));
  assert.throws(() => publishing.parseKey("54334.12", player, "unknown"));
  const entry = {...record(), provider: "11hero", key: "54334.12"};
  const backup = publishing.validateManifest({...manifest(), records: [entry]}, player);
  assert.equal(backup.records[0].provider, "11hero");
  assert.match(publishing.statusFor(entry, hash), /user-recorded; cloud unverified/);
});

test("cloud receipts distinguish exact read-back, old revisions, and uncertainty", () => {
  const receipt = {...record(), status: "verified", key: "54334.12", verified_at: "2026-10-24T18:00:00Z"};
  assert.match(publishing.cloudStatusFor(receipt, hash), /exact cloud read-back matched/);
  assert.match(publishing.cloudStatusFor(receipt, hash), /In-game testing still required/);
  assert.match(publishing.cloudStatusFor(receipt, "b".repeat(64)), /Older candidate revision/);
  const uncertain = {...receipt, status: "uncertain", key: null, error: "Timed out"};
  assert.match(publishing.cloudStatusFor(uncertain, hash), /Use Recheck; do not re-upload/);
  assert.doesNotMatch(publishing.cloudStatusFor(uncertain, hash), /Key null/);
});

test("verified receipt must match the requested collection, revision, provider, and owner", () => {
  const receipt = {
    id: "1".repeat(32), provider: "11hero", collection_id: "combined", candidate_sha256: hash,
    published_sha256: "b".repeat(64), status: "verified", key: "54334.12", verified_at: "2026-10-24T18:00:00Z"
  };
  assert.equal(publishing.validateReceipt(receipt, "combined", hash, player), receipt);
  for (const changes of [
    {collection_id: "serve-returns"}, {candidate_sha256: "c".repeat(64)}, {provider: "other"},
    {key: "1909208.1"}, {verified_at: undefined}, {published_sha256: null}, {status: "uncertain"}
  ]) assert.throws(() => publishing.validateReceipt({...receipt, ...changes}, "combined", hash, player));
});
