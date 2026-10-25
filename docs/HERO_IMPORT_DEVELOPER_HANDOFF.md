# 11 Hero import and evidence integration: developer handoff

Research date: 2026-10-25. Repository reviewed at
`97d9fda2f76c4bb57889783b4caa038958420040`.

## Goal and first delivery

Make existing 11 Hero exports usable in 11 Analyst so a player can move from
observed recurring problems to justified practice and later reassessment.
Deliver a manual JSON importer first, then resumable collection of a player's
available matches. This document is an implementation proposal, not a claim
that importing, automated downloads, or calibrated shot reproduction exist.

Pilot identity: player ID **1909208**, current name **DigitalByooki**. Keep IDs as
strings internally; names are mutable display and discovery attributes.

## Verified findings and their limits

| Finding | Evidence / limit |
| --- | --- |
| Player profile reports 55 matches | https://11hero.com/players/1909208 |
| Match discovery is paginated and name-filtered | Profile links to https://11hero.com/matches?playerName=DigitalByooki ; clicking pagination adds `page=2`, etc. |
| All available pilot links were discoverable | Browser traversal found 55 unique match URLs across five pages: 12/12/12/12/7. Every card named DigitalByooki; last page disabled Next. This is a dated observation, not a fixed expected count. |
| Per-match shot export works | Match Shots tab offers **Export all shots (JSON)**. One export was downloaded and parsed locally. |
| Bulk export / documented match API | Neither was identified in the inspected public interface or public search. Absence is not proven; authenticated options and a supported API remain unverified. |
| Direct HTTP retrieval | Research requests received HTTP 403. Browser reading/export worked. Do not treat a browser export as proof that server-to-server collection is supported. |
| Origin of detailed data | Hero's upload instructions describe headset game logs and PC spectator logs: https://11hero.com/upload . Hero availability is uploaded coverage, not the complete Eleven account history. |

Reference match:
https://11hero.com/matches/01a1610f-89ac-7000-aa7a-1e42566bd38b
(Munna62 versus DigitalByooki). The export contained **181 records, 41 fields,
138 Hits and 43 Tosses**, grouped under 43 distinct `pointId` values, involving
players 770249 and 1909208. These counts describe one export only. Raw player
exports are intentionally not committed with this handoff.

The match card showed a 2:0 result with set scores 13:11 and 0:0, while the
export grouped 43 point IDs. This needs reconciliation; do not silently declare
this a complete, internally consistent match or infer terminal outcomes from
the summary. Another inspected card showed a set-count/score-list anomaly.

## Where this fits the current repository

| Existing component | Current contract | Proposed integration |
| --- | --- | --- |
| `analyst.py` (`read_source`, `analyze`, `persist`) | Immediate `.log` files, local FullSnapshot records, score-transition points; SQLite/report rebuild from the current input directory | Introduce explicit Hero inputs and provenance. Do not rename JSON as `.log` or bypass snapshot validation. Define whether imported archives persist across rebuilds. |
| `telemetry.py` (`Event`, `Collector`, `attach`) | Engine-frame events, raw vectors, source lines, sometimes paired before/after states | Add a separate import adapter; do not invent engine ticks, local line evidence, incoming states, or collision events for Hero hits. |
| `serve_reception.py` | Requires bounded terminal attempts, known actors, no detected gaps, and supported local loss reasons | Preserve these guards. Hero-derived outcomes need a separate evidence path and validation, not fabricated `raw_reason` strings. |
| `loss_analysis.py` | Priorities based on observed local point losses and minimum evidence | Keep source-specific denominators and unknowns. Do not mix Hero success flags into local loss counts without reconciliation. |
| `shot_catalogue.py`, `dashboard/catalogue.js`, `dashboard/spin.js` | Versioned lexicon, synthetic receiver frame, named-shot classification gates | Retain Hero labels as provider-derived labels; validate their mapping into the lexicon. Preserve the glossary's axis convention. |
| `practice.py` | Generic candidate settings; raw ball vectors are not launcher sliders | Treat Hero `bm*` fields as candidate reconstruction inputs pending in-game validation, not proof of fidelity. |
| `cloud_publish.py`, `serve.py`, `dashboard/publishing.js` | Optional consented cloud delivery and exact settings read-back | Reuse publication safeguards after imported candidates qualify; collection must never trigger upload. |

Important correction to the earlier research summary: the repository already
contains a `HeroClient` using `/api/getBallMachineList`,
`/api/sendBallMachineToCloud`, and `/api/getBallMachine`. Those are ball-machine
operations, not discovered match-history or shot-download APIs. Do not assume
their authentication, pagination, or schemas apply to match data.

## Observed export schema

The exported root is an array. Field names below are observed, not an official
provider specification. Preserve the original JSON alongside normalized data.

| Fields | Proposed handling |
| --- | --- |
| `id`, `beginAt`, `playerId`, `pointId`, `playerIsHome` | Provider IDs, timestamp and attribution. Parse timestamp with timezone; retain original precision and text. |
| `contactType` | Observed `Toss` and `Hit`. A toss is not a racket shot or return attempt. |
| `posX`, `posY`, `posZ` | Event ball position, not established landing coordinates or paddle pose. |
| `velX`, `velY`, `velZ`, `velSqrt` | Provider velocity components and reported speed magnitude. Hero's metrics display m/s; verify export units and event timing independently. |
| `rrateX`, `rrateY`, `rrateZ`, `rrateSqrt` | Preserve components and magnitude separately until units are established. |
| `spinDirection`, `shotType`, `direction`, `distance`, `height` | Provider classifications and nullable attributes; never substitute for validated measurements. |
| `isSuccess`, `isWinningShot`, `isOpenUpShot`, `rallyCount` | Provider outcome/sequence annotations; definitions and handling of incomplete points require validation. |
| `isServe`, `isServeAce`, `isServeSuccess` | Provider serve annotations. In the sample, `isServe=true` applies to both tosses and serve hits. |
| `bmPosX`, `bmPosY`, `bmPosZ` | Provider machine-position fields; preserve frame and transformation uncertainty. |
| `bmBasePosX`, `bmBasePosY`, `bmBasePosZ` | Additional machine/base-position fields; exact semantics unverified. |
| `bmSpeed`, `bmAngleHorizontal`, `bmAngleVertical` | Candidate feed speed and launch angles; not verified racket angle. |
| `bmSpinTopBottom`, `bmSpinLeftRight`, `bmSpinScrew` | Candidate machine spin components; do not copy raw `rrate*` into these fields. |

Observed shot labels: `Toss`, `Serve`, `Drive`, `Push`, `Chop`, `SlowLoop`,
`FastLoop`. Observed spin labels: `None`, `BottomLeft`, `BottomRight`, `Bottom`,
`TopLeft`, `TopRight`, `Top`, `Left`, `Right`. These lists are not exhaustive.
In particular, Hero already performs some shot classification; Analyst should
retain its labels and document disagreements instead of assuming none exist.

Specific validation findings:

- All 181 `direction` values were `Mid`; `distance` was `Mid` in 175 rows and
  `Long` in 6. All `height` values were null. Do not claim accurate placement
  classification from these distributions.
- For one serve, `rrate=(-5313.3,7701.6,-5056.5)` and `rrateSqrt=29.5`.
  The vector norm divided by 360 is approximately 29.54. This suggests
  degrees/s components and revolutions/s magnitude, but is only a hypothesis.
  Verify across fixtures and against provider/game definitions before conversion.
- The browser table exposes set, score and `pointWonByHome`; these were absent
  from the 41-field download. The file also lacks match ID, ranked status,
  participant names, and a match-level envelope. Save independently obtained
  metadata rather than assuming it is present.
- No explicit table/net collision events, paired incoming/outgoing ball states,
  continuous trajectories, paddle settings, grip, or handedness were found in
  this export. Existing player settings remain the source of known handedness.

## Import contract (proposed)

Create `hero_import.py` with a provider-specific parser and a versioned normalized
record, rather than forcing imported data into `Collector.feed()`.

Each imported match should retain:

- `source_kind: hero_export`, importer version, retrieval time, source URL,
  provider match ID, original file name and SHA-256, participant IDs where
  established, and discovery name. Unknown metadata remains null.
- Original shot rows and a deterministic provider key `(provider_match_id, id)`;
  point grouping key `(provider_match_id, pointId)`.
- Separate provenance for numeric provider fields, provider-derived labels,
  Analyst-derived labels, user declarations, and unresolved values. Numeric
  provider fields are not automatically independently verified measurements.
- Explicit frame, units, event timing, completeness and outcome-evidence status.
  Unknown is different from zero and false. Preserve unrecognized fields.

Validate root shape, required identifiers, participant membership, finite
numeric vectors, boolean types, timestamps, and duplicate/conflicting IDs.
Keep diagnostics and raw input for rejected rows; never silently repair them.
Allow documented optional/null fields. Conflicts must not overwrite previous
evidence without retaining revisions. Support both players' rows, then filter
the analysis target by stable ID.

Hero UUID match IDs must not be assumed to equal Eleven's numeric game IDs.
Reconcile local-log versus Hero matches using an explicit crosswalk supported
by participant IDs, time and scores. Ambiguous matches stay separate and are
excluded from combined denominators to avoid counting the same play twice.

## Collection strategy

1. Prefer a supported provider bulk export/API if one becomes available. Record
   its actual contract before using it; do not guess endpoints.
2. Support manually exported files immediately, with a metadata manifest.
3. Prototype browser collection through the existing public UI: resolve player
   ID to profile, follow its actual Matches link, traverse pages until Next is
   disabled, collect unique match links, open each match, select Shots, export.
4. Name files by match ID, not `all_hits_data.json`. Save manifest and files
   atomically; validate each JSON before marking the match successful.
5. Keep discovery separate from downloading. Journal pending/success/failure,
   content hash, retrieval time, metadata and error. Resume partial work and
   skip unchanged imports. Revisit incomplete or changed matches explicitly.
6. Use sequential downloads with configurable conservative pacing, bounded
   retries for transient errors, and stop/report on access denials or challenges.
   Do not bypass restrictions or automatically publish anything.
7. Report discovered/downloaded/imported/failed/duplicate counts separately.
   Rerun discovery to detect new matches rather than assuming the current 55
   or relying on list order; observed listing order is not reliably chronological.

Keep browser automation optional: the current offline application requires no
third-party Python packages. An optional collector must not break that promise
for manual imports or existing local-log users. A successful per-match export
does not establish a supported long-term automated integration.

## Implementation backlog and completion gates

| Order | Work item | Acceptance criteria |
| --- | --- | --- |
| 1 | Manual Hero importer and manifest | Imports a valid sample with 181 rows/138 Hits/43 Tosses without dropping opponents; preserves all 41 fields, hash and source match ID. Reimport is idempotent. Synthetic malformed fixtures exercise missing/null fields, unknown enums, nonfinite numbers, conflicting IDs and timestamp handling. No user exports committed as fixtures. |
| 2 | Separate Hero evidence in report/storage | Source and coverage are visible; unknown outcomes stay unknown. Local tests and outputs preserve their contracts. Neither provider flags nor missing collisions become fabricated local reasons or gap-free telemetry. |
| 3 | Optional resumable collector | Current pilot discovery reproduces 55 unique links across five pages if the site is unchanged. Controlled test verifies interruption/resume, filename isolation, pagination exhaustion, duplicate links, access denial and changed counts. Then run a small live export trial before the full collection. |
| 4 | Units, coordinates and label calibration | Document component units, reference axes, signs, handedness handling and event timing. Review positive/negative examples for mixed spin, long serves and both receiver sides. Unknown placement remains visible. |
| 5 | Weakness-to-practice pilot | Identify long sidespin serves toward the player's backhand side only where supported. Show attempts, resolved/unknown returns, failure types, match/opponent counts and source examples. Separate return success from eventual point win. |
| 6 | Representative feed validation | Select a real incoming serve, preserve source lineage, validate machine format/delivery and then in-game speed/spin/placement. Delivery verification alone does not unlock a faithful-reproduction claim. |
| 7 | Progress assessment | Compare like-for-like categories with sample sizes, coverage and opponent/mode context. Keep provider/importer/classifier versions so a rule change is not presented as player improvement. |

Proposed CLI sketches (not existing commands):

```text
python hero_import.py --manifest hero-manifest.json --player-id 1909208
python hero_collect.py --player-id 1909208 --discover-only
python hero_collect.py --player-id 1909208 --resume
```

## Clubhouse and Eleven API findings to retain

Clubhouse's live page calls `/lib/matchViewer.php` with match ID and prior score,
approximately every three seconds. Inspected responses contained player/round
scores, serving indicator, commentary and replay references, but no ball vectors.
Two responses for the same commentary ID, time and score produced different
tactical descriptions (returns versus spin-heavy serving); a second paired
test reproduced this behavior. Treat the commentary as unverified generated
narrative, not shot evidence. The generation mechanism and private backend
inputs were not established. Replay metadata alone does not establish telemetry
download availability.

The public community scoreboard source calls
`https://api3.elevenvr.com/accounts/{userID}/matches` and
`/accounts/{userID}`. Its README requests an API key from Eleven developers;
this research did not authenticate or verify the current response schema.
It is a potential match-summary integration, not proof of Clubhouse's exact
upstream source or a ball-telemetry feed.

References:

- https://11clubhouse.com/live/
- https://github.com/Cristy94/eleven-vr-scoreboard/blob/main/app.js
- https://github.com/Cristy94/eleven-vr-scoreboard
- https://11hero.com/upload
- https://11hero.com/players/1909208

## First developer assignment

Implement work items 1 and 2 before automating collection. Bring one exported
match into a separate, inspectable Hero evidence view, document missing context,
and prove that existing local-log analysis still behaves the same. Then add
the collector and calibration work. The useful product outcome remains:
**what should I practice, what evidence supports it, and is practice helping?**
