# Manual 11 Hero evidence imports

Implemented first delivery: a manual importer and an independent evidence view.
This follows work items 1 and 2 of the supplied
[research handoff](HERO_IMPORT_DEVELOPER_HANDOFF.md). Browser collection,
automatic match discovery, cross-source reconciliation, classifier calibration
and faithful machine-feed reconstruction are **not implemented** by this delivery.

## Import an export

1. In 11 Hero, open a match, select **Shots**, and use **Export all shots (JSON)**.
   Keep the original file; do not rename JSON to `.log`.
2. Save the file in a private directory, preferably `hero-imports` in your local
   checkout (ignored by Git), or outside the checkout. Name it by match ID when
   possible, since browsers often reuse `all_hits_data.json`.
3. Create a local manifest based on [the example](hero-import.example.json).
   Replace the example UUID, file path and target player with actual values.
   Paths are relative to the manifest's directory, or absolute.
4. Run from the project root:

   ```powershell
   python .\hero_import.py --manifest .\hero-manifest.local.json --player-id 1909208 --output .\output
   ```

5. Open `output\report.html` and select **Hero imports**. For a served dashboard,
   restart `serve.py` and reload the browser after importing.

There are no network requests, game logins, cloud uploads or extra packages in
this workflow. The original source export is read-only. Tests use fabricated
rows; never contribute real player exports as fixtures.

The importer also works without a local-log profile: it creates an empty local
profile and the report, then displays Hero evidence separately. Empty local
statistics are not filled from provider flags. Use another output directory
when switching players; an existing profile for a different player is rejected.

## Manifest contract

```json
{
  "format": "11analyst.hero-manifest",
  "version": 1,
  "player_id": "1909208",
  "matches": [
    {
      "file": "hero-imports\\YOUR-MATCH-ID.json",
      "provider_match_id": "00000000-0000-4000-8000-000000000001",
      "source_url": "https://11hero.com/matches/00000000-0000-4000-8000-000000000001",
      "retrieved_at": null,
      "participant_ids": null,
      "discovery_name": null,
      "metadata": {
        "notes": "Replace the example UUID and path. Keep uncertain context explicit."
      }
    }
  ]
}
```

- `provider_match_id` is a canonical UUID provided by the source match page.
  The downloaded array has no match envelope, so this association is declared,
  not verified from the file. It is never assumed to equal a local numeric game ID.
- `source_url` may be null; otherwise it must be the exact
  `https://11hero.com/matches/<provider_match_id>` URL.
- `retrieved_at` may be null. If known, use ISO 8601 with a timezone, e.g.
  `2026-10-25T14:00:00Z`. Do not invent a retrieval time from file modification time.
  The importer records its own `imported_at` separately.
- `participant_ids` may be null or exactly two distinct positive numeric IDs
  including the analysis target. Rows outside a declared pair are quarantined.
  Observed IDs are retained separately when participants are not declared.
- `discovery_name` may be null or a display-name string; it is never the identity key.
- `metadata` may be null or an object. Put independently obtained scores, names,
  ranked status, research context and discrepancies here. These remain
  `manual_manifest_unverified`, not additions to local match results.
- File and required identifiers cannot be null. Unsupported entry fields fail
  explicitly; put supplementary information under `metadata`.

## Row validation and normalization

The export root must be an array. Every accepted row needs `id`, `pointId`,
`playerId`, `beginAt` and a nonempty string `contactType`.

- IDs normalize to strings. Composite row and point keys include the Hero match
  UUID, so two matches can contain the same shot/point ID without collision.
- `beginAt` needs a valid timestamp and explicit timezone. Original text,
  fractional precision and offset are retained; no engine tick or local log line
  is invented. The displayed export row is a one-based array position.
- Provided numeric vector, magnitude, sequence and `bm*` fields must be finite
  JSON numbers, not numeric strings or booleans. `rallyCount`, if supplied, must
  be a nonnegative integer.
- Known boolean flags accept only true, false or null. Missing/null values
  remain unknown rather than becoming false.
- Optional vector components may be absent/null. Incomplete vectors produce a
  diagnostic and a null normalized vector, with individual fields still retained.
- Unknown string labels and contact kinds are preserved with warnings rather
  than forced into known categories. All unrecognized fields are retained.
- Identical duplicate IDs in one file collapse to one accepted record, with a
  duplicate count. Conflicting copies quarantine **every** row with that ID,
  including a valid row that conflicts with a malformed copy.
- Malformed JSON, duplicate JSON object keys, non-array roots, and invalid rows
  produce explicit diagnostics. Original file bytes are retained, including
  nonstandard JSON that could not be normalized.
- An accepted-row set with no target player or more than two observed players
  rejects the match revision for use; rows remain inspectable. Contradictory
  home/away annotations produce a warning, not a repaired attribution.

`provider_fields` retains the original fields for accepted rows. Provider labels,
provider flags, numeric vectors, declared metadata and null Analyst
labels/outcomes remain separate. `rrateSqrt` is not substituted for the vector
norm, and no degrees/s-to-rad/s conversion is applied.

The importer reads at most **32 MiB per export or manifest**. Oversized or missing
files are reported without pretending an import succeeded. No collection retry
or background download is attempted.

## Persistence, revisions and rebuilds

The authoritative archive is `output\hero_imports.sqlite3`, **separate from**
`analyst.sqlite3`. Its `hero_revisions` table stores:

- `revision_id`: hash of source SHA-256, importer version, player/match identity
  and declared provenance/metadata.
- `player_id`, `match_id`, `imported_at`.
- `raw_json`: exact original file bytes as a SQLite BLOB.
- `data_json`: normalized record, diagnostics, counters and revision number.

Each revision's raw and normalized data are written in one transaction. Reusing
the same file bytes and metadata skips insertion. Changing either preserves a
new revision; none is silently promoted to overwrite previous evidence.
The original filename is part of provenance, so renaming an otherwise identical
file creates a new revision. Import order, not game chronology, numbers revisions.
The UI exposes all revisions and does not sum them as independent matches.

Materialized outputs:

- `output\hero_evidence.<player-id>.json`: normalized evidence and diagnostics.
- `output\report.html`: embedded Hero view alongside unchanged local findings.
- `output\profile.json`: left unchanged when an existing local profile is present.

A normal `analyst.py` rebuild leaves the Hero archive untouched and reloads the
selected player's Hero evidence into the report. Local SQLite snapshots,
matches, points, priorities and settings retain their original contracts.
The `render_html`/`dashboard.render` Python APIs also accept an explicit
`hero_evidence` argument; an in-memory render without it includes no imports.

If materializing the report fails after the archive transaction, the command
fails explicitly. Rerun the same manifest: existing revisions are reused and
the outputs are refreshed. Back up the archive, original files and manifest.
Normalized JSON exports do not contain the raw bytes of rejected rows; recover
those from the original file or the archive's `raw_json` BLOB.

Exit code is nonzero for unreadable/rejected files or any rejected rows, even
when another file or valid rows were imported. Unknown-label warnings and
identical row duplicates are reported but do not make an otherwise valid import
fail. Summary counters describe the files processed in that invocation, not
additional unique coverage when unchanged files are re-imported.

## Evidence view

Choose a source match/revision, then filter by contact kind, target/opponent
player, point ID or provider label. Inspect a row to see the retained original
fields and normalized provenance. Both players are imported; filtering does not
discard opponent data. Tosses are distinct from Hits even if `isServe=true`.

Hero evidence is intentionally independent of the dashboard's local ranked/
unranked filter. Provider success and winning-shot flags are not first-return
outcomes or eventual point winners. Named catalogue categories, synthetic spin
conventions, local loss rankings, receiving denominators and publishing gates
are unchanged.

### Milestone-one assisted review

Within **Hero imports**, choose a revision and use **Milestone 1: assisted serve
review**. The queue contains opponent Hit rows with a provider serve flag or
Serve label; Tosses and own serves are excluded. Disagreeing labels, multiple
serves, reversed timestamps, quarantined rows and ace/return-contact overlap
are flagged. A following Hit means **following in source-file order**, not a
validated event sequence. Missing contact is not a missed return.

The sample has 21 opponent serve Hits: 2 provider-marked unsuccessful serves,
19 with a following target-player Hit, including 6 marked unsuccessful.
All 21 carry provider `Mid` direction and distance; 18 carry `BottomLeft` spin
and 3 `TopLeft`. These are provider annotations, **not** measured category
attempts/errors or an error rate. The sample cannot yet substantiate the
long-sidespin/backhand finding. No replay/video has been supplied.

Player 1909208 is user-confirmed right-handed. Backhand side means the
receiver's left, not the stroke played. Geometry stays unknown until a
validated coordinate transform, event timing and bounce reconstruction exist.
Neither camera orientation nor Hero's direction/distance labels is used.
Long requires the hypothetical next table bounce **without a return** to fall
beyond the receiver's end line; a deep first bounce does not establish length.
Spin axes/units and machine-feed reconstruction also remain pending.

Review notes are appended to browser-local history keyed by player and exact
revision, with source hash, match/point/shot IDs, export-row index and timestamp.
A known immediate-return observation requires an explicit reference and remains
`user_review`, not an Analyst outcome. Without a reference, save pending notes.
Geometry cannot be overridden in the form. **Export this revision's reviews**
backs up the history and candidate references as `11analyst.hero-reviews` v1.
Revisions are not combined; older notes are never silently carried onto changed
source bytes or metadata. Corrupt/unavailable storage is reported, not replaced.
Browser notes are not added to the SQLite archive, report file, other browser
origins or local statistics. Review-file re-import is not yet implemented.
No reviews unlock machine keys.

The pure geometry prototype in `dashboard/hero_review.js` accepts **synthetic
fixtures only**. It takes explicitly supplied first and hypothetical next
bounces, not raw Hero contacts, and does not simulate ball physics. Its
synthetic frame uses metres, +Y up, table centre as origin, and a proper
180-degree +Y rotation for a receiver at the opposite end (including angular
vectors). Table dimensions are 2.74 x 1.525 m, surface height 0.76 m relative
to the floor-level centre. Position/spin tolerances are explicit fixture inputs,
not agreed real-world acceptance thresholds. Centre/end-line/edge uncertainty
is retained. Tests cover both hands/ends, side changes, translated origins,
deep-first-bounce negatives, mixed/pure/zero spin, boundaries and all validation
gates. Synthetic success verifies logic only, **not real-world accuracy**.

Remaining milestone work: validate the provider transform/timing/units and bounce
reconstruction against an independent reference; classify actual attempts and
immediate outcomes; agree category-feed tolerances; validate a representative
feed and the player's walkthrough in-game. The existing generic key and its
separate repeatability protocol do not establish this category's fidelity.

## Reference sample and research limits

The supplied reference export was validated locally: **181 rows, 41 fields,
138 Hits, 43 Tosses and 43 provider point groups**, covering both players.
Those are one export's observed counts, not hardcoded import requirements.
The real export and its manifest remain ignored private files.

The handoff reports a 2:0 match card with sets 13:11 and 0:0. That is inconsistent
with treating 43 exported point groups as a complete scored match. Its score
summary is retained as a declaration with an unresolved-reconciliation note.
No terminal outcome or complete-match result is inferred.

The [handoff](HERO_IMPORT_DEVELOPER_HANDOFF.md) also records:

- Hero already supplies shot/spin labels. They must be retained as provider
  classifications; their meaning and mapping into the catalogue need validation.
- A suggested relation between rotation components and reported magnitude is a
  hypothesis, not permission to convert units or declare spin direction.
- Hero's available history reflects uploaded coverage. The dated discovery of
  55 links is not a fixed expected total or complete account history.
- Direct research HTTP requests received 403; successful browser exports do not
  establish permission or support for automated server-side collection.
- Clubhouse commentary varied for the same score/context. Treat it as unverified
  generated narrative, never ball/shot evidence.
- Community Eleven API references may support match summaries, but authentication
  and schemas were not verified. The existing Hero ball-machine API is unrelated
  to match-history discovery.

No access restrictions are bypassed and no match endpoints are guessed.
