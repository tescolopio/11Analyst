# 11 Analyst

**Turn Eleven Table Tennis logs into evidence-backed training priorities.**

11 Analyst is a local-first tool that reconstructs observed points, identifies
recurring return problems, and helps players choose what to practice next. Its
self-contained dashboard connects each recommendation to supporting match and
contact evidence, with optional Ball Machine Key generation through 11 Hero.

**Status: working prototype under active development.** Loss analysis, training
plans, the shot catalogue, spin illustrations and key delivery are implemented.
Automatic spin/placement classification and faithful opponent-shot reproduction
are not yet validated. This is an independent community project, not an official
Eleven Table Tennis or 11 Hero integration.

### At a glance

| Capability | What it does today |
| --- | --- |
| Local log analysis | Deduplicates files/matches and reconstructs observed point outcomes |
| Evidence-driven priorities | Ranks recurring problems by observed point losses, with source examples |
| Interactive dashboard | Filters match modes, inspects contacts, shows training and data-quality details |
| Shot catalogue | Defines 12 starter categories and builds names from context, length, location, spin and pace |
| Spin glossary | Illustrates rotation with a marked 3D ball, camera presets and independent controls |
| Receiving pilot | Counts supported first-return attempts, outcomes, exclusions and unresolved evidence |
| Training graphics | Shows perspective table-tennis tables, targets, serve-bounce order and feed settings |
| Ball Machine Keys | Optionally publishes eligible generic return plans and verifies exact cloud read-back |
| Practice observations | Saves explicit player-reported feed checks locally, with export |
| Manual 11 Hero imports | Preserves provider exports and revisions in a separate, inspectable evidence view |

**Privacy default:** analysis needs no network or third-party Python packages.
Raw logs and generated reports are not distributed in this repository. Optional
cloud publishing sends sanitized machine settings only, after explicit consent.

## Quick start

### Requirements

- Python **3.11+**, available as `python`.
- A modern browser with JavaScript enabled.
- Your own Eleven Table Tennis `.log` files containing local match snapshots,
  or manually exported Hero shot JSON for the separate import workflow below.
- Git for cloning; Node.js **18+** only if you want to run the JavaScript tests.
- An internet connection only for cloning and optional cloud-key publishing.

The commands below use PowerShell on Windows. There is no `pip install`,
`npm install`, frontend build, game login, or account token required.

```powershell
git clone https://github.com/tescolopio/11Analyst.git
Set-Location .\11Analyst
New-Item -ItemType Directory -Path .\11TTLogs -Force | Out-Null
```

Copy your logs directly into `11TTLogs` (not nested subfolders). Then enter
your actual Eleven player ID and run the analysis:

```powershell
$playerId = Read-Host "Your Eleven player ID (digits only)"
python .\analyst.py --logs .\11TTLogs --output .\output --player-id $playerId
if ($LASTEXITCODE -eq 0) { Start-Process .\output\report.html }
```

The historical development default is **DigitalByooki, player ID `1909208`**.
Pass `--player-id` when analyzing another player; the program does not discover
your account automatically. The player must be represented in usable local
snapshots, and contact attribution still depends on the authenticated logging
account.

For optional Ball Machine Key generation, leave this command running in a terminal:

```powershell
python .\serve.py --output .\output --port 18765
```

Open **http://127.0.0.1:18765/**. Use the exact `127.0.0.1` address, not a
`localhost` alias. Stop the server with **Ctrl+C**. Nothing is uploaded merely
by starting it; the offline report remains usable without the server.

### Suggested first session

1. Check **Data & evidence** for missing snapshots or telemetry gaps.
2. Open **Training plan** and inspect the highest-count eligible loss category.
3. Follow **Why this priority?** into real point and contact examples.
4. Use **Shot catalogue** and **Spin glossary** to understand terminology.
   Catalogue entries are definitions, not automatically detected weaknesses.
5. Preview an eligible generic return plan and, if desired, generate a key
   through the local server after reading its sharing notice.
6. Back up your in-game settings, validate the feed in Eleven, and record
   actual practice results. A verified download is not proof of shot fidelity.

### Guide contents

- [Shot catalogue](#shot-catalogue)
- [Spin glossary and first-return pilot](#spin-glossary-and-first-return-pilot)
- [Analysis commands](#run) and [generated outputs](#outputs)
- [What is measured](#what-is-measured)
- [Using the dashboard](#using-the-dashboard)
- [Optional cloud publishing](#publishing-through-11-hero-optional-local-server)
- [Manual 11 Hero evidence imports](#manual-11-hero-evidence-imports)
- [Ball/contact telemetry](#ball-and-paddle-contact-telemetry)
- [Practice patterns](#ball-machine-practice-patterns)
- [Interpretation and ranking](#interpretation-and-training)
- [Architecture](#architecture)
- [Quest file share sync](#quest-file-share-sync)
- [Privacy and repository contents](#privacy-and-repository-contents)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Roadmap and contributing](#roadmap-and-contributing)
- [Validation protocol](docs/VALIDATION_PROTOCOL.md)

The detailed product brief and completion gates are maintained in the
[visual guide and milestone tracker](docs/Eleven_Analyst_Spin_Guide_Developer_Brief.docx).
The [controlled-capture validation protocol](docs/VALIDATION_PROTOCOL.md) defines
the checklist, capture procedure, and acceptance criteria for milestone-one
coordinate mapping, spin conventions, and bounce reconstruction.

## Shot catalogue

The **Shot catalogue** dashboard section now provides **12 starter categories**
and a reusable, versioned vocabulary (`shot-lexicon-1`). Names combine:

- Incoming context: serve or rally ball.
- Length/depth: short, half-long or long serves; short, mid-depth or deep rally balls.
- Receiving location: backhand side, forehand side, table middle, or wide to either side.
- Spin: topspin, backspin, sidespin, mixed side-topspin/side-backspin, negligible, axial or unknown.
- Explicit overhead-clockwise/counterclockwise sidespin direction, or direction not established.
- Optional pace, with no invented numerical speed bands.

The featured milestone-one entry is **Long sidespin serve to the backhand side
(sidespin direction unspecified)**. It includes recognition cues, conditional
counter-play guidance, suggested success criteria, a handedness-aware schematic
of the target side, and links to both possible sidespin illustrations.
For this family, guidance distinguishes sideways compensation from the lift
needed for a possible top/backspin component; a generic sidespin label does not
justify one fixed racket angle.

Search/filter the starter library or use the name builder to explore valid
combinations. Changing the incoming context updates its permitted length/depth
choices; sidespin direction only applies to side-containing families. Builder
changes are exploratory, not saved observations; export a definition to keep it.
The full catalogue is persisted in `output\shot_catalogue.json`,
`output\profile.json`, SQLite's profile JSON, and the portable report.
Both the catalogue and individual definitions can be exported from the dashboard.

**This first catalogue release defines categories; it does not yet classify
recorded balls into them.** Per-category attempts, failures and matches are
unknown (`null`), not zero. The broad receiving-pilot counts are shown separately
and never attributed to the selected category. No named category is asserted to
be a personal weakness or allowed to publish a category-specific key.

Before named-shot loss rankings can be built, validate log-coordinate conversion,
measurement timing, receiver/bounce attribution, length inference and category
boundaries, then review labeled positive and negative examples. A long serve is
defined by its hypothetical next bounce beyond the end line, not simply a deep
first bounce. Table middle is not automatically the playing elbow, and a
backhand-side target does not prove a backhand stroke. Broad sidespin families
overlap their mixed-spin subtypes, so future ranking must avoid double-counting.

Catalogue checks:

```powershell
python -m unittest discover -s tests -p test_shot_catalogue.py
node --test .\tests\test_catalogue.js
```

## Spin glossary and first-return pilot

The dashboard now includes a dependency-free **illustrative 3D spin glossary**.
It starts paused on topspin and offers marked-sphere rotation, top/back and both
overhead-side directions, mixed-spin balance, synthetic zero, and optional axial
rotation. Camera presets, overlay switches, stepping, slow playback, and optional
straight travel work offline. Reduced-motion users get static stepping instead
of autoplay. No curve, bounce, paddle motion, or log replay is simulated.

Confirmed synthetic frame: **+X receiver right, +Y up, +Z opponent toward receiver**.
The receiver faces -Z. Right-hand rotation gives topspin +X, backspin -X,
clockwise viewed from above -Y, and counterclockwise +Y. Handedness and camera
do not change those vectors. There are no ambiguous left/right sidespin aliases.
The [player settings](player_settings.json) record DigitalByooki's confirmed
right-handed preference by player ID; other players remain unspecified.
These preferences do not classify forehand/backhand placement.

The viewer contract uses `schemaVersion: "1"`, `conventionVersion:
"receiver-rh-1"`, `sourceKind: "synthetic"`, explicit angular velocity in rad/s
and linear velocity in m/s, a label, illustrative evidence status, and measurement
event. Camera/playback state is separate. Rev/s converts with `2*pi`; mixed
balance preserves total magnitude. Unknown spin is distinct from zero.
The prototype accepts synthetic +Z travel only; **Eleven log axes, units and
machine sliders are not yet mapped into this frame**.

The **opponent-serve / first-return pilot** counts bounded terminal opponent-serve
attempts across wins and losses, not just lost points. Known serve faults,
nonterminal attempts, unbounded windows and known measurement gaps are excluded.
Earlier attempts never inherit the terminal point result. Contact alone is not
success; a later rally loss is not charged to the first return. Unknown outcomes,
point-level versus attempt-level exclusions, source examples, classifier version
and selected-mode exports remain visible.

Development sample as of **2026-10-24** (not included in the repository):
**731 receiving attempts across 38 matches**, 730 resolved,
with 47 missed first returns, 250 failed first-return landings, 407 returns
followed by an opponent rally contact, 26 first-return winners and 1 unknown.
The **297/730 = 40.7%** failure fraction applies only to the resolved observed
sample, not all serves played. Automated rule tests are not independent
ground-truth validation of shot categories.

The local observation form proposes a **20-feed repeatability protocol**:
20 legal serve feeds, at least 18 in a target chosen before testing, and a
comfortable pace. The player must agree before the run. Test just the
representative serve feed **ANLY01**, with its settings unchanged. Existing key
**54334.340** is a delivery baseline reported working by the player, not proof
of physical fidelity. The form records key, feed, any matching receipt revision,
target, legal feeds/returns, pace, spin observations and explicit self-report
status. It stores observations in player-scoped browser storage and exports
JSON backups; it does not upload anything. File and localhost storage differ.

**In-game validation remains pending.** Meeting this proposed broad protocol
would establish self-reported repeatability/usability, not calibrated spin,
speed, placement or opponent reproduction. Player-specific keys remain
withheld. The original long-sidespin-to-backhand milestone remains open.
DigitalByooki has accepted the 20-feed protocol and will test it in-game;
no results from that test have been recorded yet.

Targeted checks:

```powershell
python -m unittest discover -s tests -p test_serve_reception.py
python -m unittest discover -s tests -p test_dashboard.py
node --test .\tests\test_spin.js .\tests\test_pilot.js
```

## Run

Requires Python **3.11 or later**. From this folder in PowerShell:

```powershell
python .\analyst.py
Start-Process .\output\report.html
```

Optional inputs:

```powershell
python .\analyst.py --logs .\11TTLogs --output .\output --player-id 1909208
```

Input logs are read-only. Add new logs and rerun the same command. Each successful
run rebuilds the output from the current input folder; it does **not** accumulate
records from files you have removed. Only immediate `.log` files are included.
Identical files are recognized by SHA-256 and skipped. Matches are grouped by
stable match ID; repeated score states do not create extra points.

## Outputs

These files are generated locally after a successful run, not hosted GitHub
downloads. The default `output` directory is excluded from version control.

- **Interactive dashboard** (`output\report.html`): overview charts, evidence-backed
  training cards, drill downloads, searchable matches, point inspection, and
  data-quality details. Opens directly in a browser without a local server.
- **JSON profile** (`output\profile.json`): the same profile plus source provenance
  and per-point ball/contact telemetry, suitable for a future dashboard.
- **SQLite database** (`output\analyst.sqlite3`): `sources`, `snapshots`, `matches`,
  `points`, and `profiles` tables. Detailed records are stored as JSON alongside
  searchable IDs, timestamps, and statuses. Version 1 databases are rebuilt into
  schema version 2 automatically on the next successful run.
- **Practice recipes** (`output\practice_patterns.json`): original sequences, research
  citations, raw contact examples, calibration steps, and candidate settings.
- **Shot catalogue** (`output\shot_catalogue.json`): versioned definitions,
  recognition cues, counter-play guidance and explicit classification gates.
- **Ball-machine candidates** (`output\ball_machine`): eligible return-plan packages,
  three reference collections, and individual rally-feed variations. Serve collections require a
  provenance-backed game-default serve seed from the logs. Their structure is
  validated, but **category fidelity is not established**. The development
  player reported loading and using one earlier serve-return package; this
  does not validate every candidate or its physical behaviour.
- **Cloud publication journal** (`output\cloud_publications.<player-id>.json`):
  created by the optional publishing workflow; preserve it to prevent duplicate
  uploads and retain settings revisions and verification status.

Manual key records and pilot observations live separately in browser storage.
Export them from the dashboard; they are not automatically backed up in SQLite.

SQLite replacement is transactional; each report file is replaced atomically.
If report writing fails after the database commits, the command fails explicitly;
rerun to regenerate matching reports. The database holds one selected player's
current analysis, not a multi-user historical archive.

The console lists every input's status. Malformed snapshots are logged and
recorded in source diagnostics, not silently discarded. A missing directory,
unreadable input, unsupported database version, or absent player data returns a
nonzero exit code. No player data means existing outputs are left unchanged.
Malformed physics records are reported separately as telemetry diagnostics and,
where possible, attached to the affected point window.

## What is measured

The parser reads **local `FullSnapshot reads` records**, not server friend lists
or arbitrary JSON objects mentioning a match. It validates participants, scores,
winner, match format, and ranked status. Identification uses player ID rather
than display-name spelling.

- Completed-match wins/losses, game scores, and final-score point-win rate.
- Separate ranked/unranked results and daily summaries.
- Opponent strength: within 100 Elo inclusive is "similar"; beyond that is
  "higher" or "lower", using first observed match ratings.
- Per-opponent records and observed rating values.
- Close games: completed games ending with a two-point margin.
- Observed individual points only when consecutive distinct score states
  confirm exactly one increment, including a game-ending point followed by a
  new 0-0 game. Gaps are reported, not filled with invented point events.

Match scores in the profile are ordered **you, opponent**. Raw point-event scores
retain snapshot participant order; `winner_id` is the stable account ID.
Every snapshot and reconstructed point retains its source path and line number.
Incomplete matches (no winner) and inconsistent final results are excluded from
aggregate results. A declared winner with an unfinished score is flagged, not
treated as a normal completed match; forfeits are not yet modeled separately.

## Using the dashboard

The offline dashboard is a single self-contained HTML file. CSS, JavaScript, compact
point telemetry, evidence, and candidate settings are embedded; no CDN, fonts,
API, or companion file is fetched. You can copy the HTML elsewhere and still
inspect points or download its embedded settings. Without JavaScript, a basic
summary remains visible with an explicit message about disabled interactions.

- **Match mode** filters the overview, charts, training priorities, contact
  counts, and match explorer. Priorities are recomputed with the same backend
  loss classifier and evidence thresholds for each mode, not merely relabeled.
- **Why this priority?** opens supporting counts, opponent-strength context,
  logged reasons, and point examples. Follow an example to inspect the actual
  recorded events, ball vectors, and source line.
- **Match explorer** supports opponent/match-ID search, result filtering, and
  pagination. These table-only filters do not change the training plan.
- **Shot graphics** in point evidence let you select each observed hit or
  collision. Raw X/Z and X/Y projections show incoming/outgoing positions,
  normalized velocity-direction arrows, and other retained samples from the
  same attempt. Rotation-rate bars show signed raw X/Y/Z components. Missing
  states and gaps are explicit; samples are never joined into a simulated
  flight path, and the plots are not calibrated table views or paddle traces.
- **Preview training shots** opens per-feed coaching diagrams, configured aim
  gauges, spin controls, timing, and initial stage activation. Recipe and
  collection dialogs expose the same visuals, also available beside the
  publishing selector. Training cards and feed previews share a perspective
  table-tennis illustration with standard table proportions, white markings,
  raised net/mesh, edge thickness and supporting legs. Table targets are illustrative coaching goals, not
  predicted bounces; angle-gauge zero directions are diagram conventions, not
  calibrated table axes. Previews never change settings or upload anything.
- **Ball machines** provides embedded JSON downloads and setup guidance.
  Templates do not change numerically when the match mode changes; their links
  to qualifying training priorities do. In-game validation is still required.
- **Generate Ball Machine Key** is the main action on eligible return-training plans.
  The local server sends settings behind the scenes and displays a verified key
  to copy into Eleven; no JSON download or import is required. Optional file
  downloads, manual uploads, and record backups are under **Advanced**.
  The offline file itself cannot generate a cloud key.
- **Export summary** downloads the selected mode's summary and loss priorities,
  not the full raw player profile. The separate JSON/SQLite outputs remain the
  complete persistent analysis.
- **Data & evidence** distinguishes mode-filtered contact coverage from
  all-input source diagnostics and historical rating observations.

Daily point-win rates use completed-match scores; loss evidence also includes
validated points from unfinished matches. A missing daily rate is not plotted
as zero. Charts use a fixed 0-100% scale and do not claim a controlled improvement
trend. Keyboard navigation, native accessible detail dialogs, reduced-motion
preferences, and narrow-screen layouts are supported.

The editable dashboard assets live in [dashboard/](dashboard/), assembled by
[dashboard.py](dashboard.py) each time the normal analysis command runs. No
frontend build step or third-party packages are required.

### Publishing through 11 Hero (optional local server)

After generating the normal analysis outputs, run:

```powershell
python .\serve.py
```

Open the printed `http://127.0.0.1:18765/` address, then go to **Ball machines ->
Generate Ball Machine Key**. Use `--output <folder>` or `--port <number>` if
needed. The server loads a snapshot of that folder's profile at startup; restart
it after regenerating analysis to use newer candidates. Stop it with Ctrl+C.

1. Choose an eligible return-training plan, either on its training card or in
   the key-generation selector. The selector follows the selected match mode.
2. Read the sharing notice and explicitly approve sending the selected settings
   to **11 Hero**, a third-party community service. Its keys use the shared
   account prefix **54334**, not your player ID. Treat uploads as public; the
   Analyst does not provide cloud deletion.
3. Click **Generate Ball Machine Key** and confirm. No upload happens on startup,
   page load, changing match mode, or merely checking the consent box.
4. Wait for an **exact cloud read-back match**, then click **Copy key**. If automatic
   copying is blocked, select the displayed key and use your browser's Copy command. If the
   outcome is uncertain, use **Recheck without re-uploading**; this performs
   reads only. Never delete an uncertain journal entry to force a retry.
5. Back up existing in-game settings. With the machine off, open **Settings ->
   Advanced -> Backup and reset -> Ball machine**, enter the key, and press
   **Download**. Open **Training & Practice -> Ball machine** and test cautiously:
   confirm legal bounces, selected feeds, placement, order, speed, and timing.

Cloud verification checks stored JSON, **not in-game import compatibility or
trajectory quality**. One earlier serve-return key was reported usable by the
development player; current candidates still require their own in-game checks. Read-back is
an observation at the recorded time, not a guarantee a remote key never changes.

Only allowlisted feed parameters are sent. The publisher replaces free-text
descriptions with generated collection/feed labels and a random publication tag.
This tag identifies the request when multiple people publish concurrently.
Logs, player/profile data, source paths, original descriptions, and account
credentials are not sent. The original candidate SHA-256 and the actual
published-settings SHA-256 are recorded separately.

The observed 11 Hero interface uses:

| Method | Endpoint on `https://11hero.com` | Purpose |
|---|---|---|
| GET | `/api/getBallMachineList` | List shared-account settings IDs |
| POST | `/api/sendBallMachineToCloud` | Send `{"json": <complete settings object>}` |
| GET | `/api/getBallMachine?userID=54334&fileName=<id>` | Read back a candidate key |

These are **undocumented third-party endpoints**, not an official Eleven API.
They were identified in the [11 Hero editor](https://11hero.com/ballmachineditor).
The read endpoints were observed working; live writes and in-game behavior
were deliberately not exercised during implementation. The client does not
follow redirects, send login credentials, or bypass authentication challenges.
Provider changes, rate limits, normalization, and eventual consistency can
prevent verification. A failure is shown explicitly, not treated as success.

Before the single external POST, the server atomically saves a pending receipt
in `output\cloud_publications.<player-id>.json`. A per-player file lock prevents
different local server processes from submitting simultaneously. Retries,
double-clicks, and restarts reuse the same candidate's receipt rather than POST
again. An uncertain receipt can only be rechecked. A verified receipt returns
its existing key. The `.lock` companion file is local synchronization state.

Verification compares IDs against the pre-upload listing and downloads newly
appearing settings, requiring **exactly one complete payload match**. It does
not simply use the highest ID. It is bounded to 20 new IDs per attempt, three
read passes, a verification deadline, 10-second request timeouts, and 4 MiB
responses. Too many candidates, no match, duplicate matches, changed settings,
or a timeout produce an uncertain result, never a fabricated key. An interrupted
attempt may have been accepted by the provider, even if no key is shown.

Keep the publication journal with your backups; it contains the actual
sanitized settings, candidate revision, pre-upload IDs, and verification
result. **Export cloud key receipts** provides a smaller portable record of
keys and statuses, not the full journal. Browser imports cannot assert a
server-verified upload. Old candidate revisions remain explicitly labeled.

The service binds only to `127.0.0.1`, serves no arbitrary workspace files, and
guards API writes with exact Host/Origin checks plus a per-process session token.
No CORS access is enabled. Only the served report permits same-origin connections;
the generated offline report retains `connect-src 'none'`. Do not expose this
development server on a public interface or through a tunnel.

### Manual file loading and recording existing keys

The publishing workbench supports an **assisted Meta/Oculus PC workflow**:

1. Choose serve returns, rally practice, or combined practice. Download the
   selected settings as `BallLauncherSettings.json`. The dashboard checks the
   supported settings structure during generation, not actual game compatibility.
2. Close Eleven and back up its entire existing settings folder. The historical
   Meta/Oculus PC layout documented by the community is
   `<Oculus library>\Software\for-fun-labs-eleven-table-tennis-vr\settings`.
   Confirm the actual existing `BallLauncherSettings.json` before replacing it.
   **Do not guess a path if that file is missing.** Replacing a collection is not
   a merge with your existing drills. Download suffixes such as `(1)` must not
   become the installed filename.
3. Load and calibrate the collection in-game. Check legal bounces, feed order,
   placement, speed, launch intervals, and recovery delay. Changes made in-game
   are not automatically reflected in the Analyst candidate.
4. With the machine off, open **Settings -> Advanced -> Backup and reset ->
   Ball machine** (the user's current download menu path). Identify the actual
   upload/save-to-cloud control, if available, and copy the returned key.
   **Only see Download? Stop:** entering a new number does not create a key.
   The upload control has not been verified in the current build. A screenshot
   of this screen plus the game version, or developer-provided publishing
   instructions, is needed to resolve that step. Do not send authentication logs.
5. Confirm the backup, calibration, and actual upload in the workbench, then
   paste the returned key and save it locally. The account prefix must match the
   profile's player ID, or select **11 Hero shared account (54334)** as the source.
   Community example keys from unrelated accounts cannot be recorded as your uploads.

Keys are strings in `PlayerID.SettingsID` form, **not decimal numbers** or an
encoding of the JSON. A key can reference a complete collection of feeds.
We directly retrieved the public music pack behind `4008.48` and confirmed
the same overall `settingsVersion: "1"` / `shots.data` layout.

Verified community **read-only** endpoints (not an official publishing API):

- [Retrieve the public settings for 4008.48](https://solidslime.net/cloud/getSettings.php?environment=production&type=ballMachine&userId=4008&fileName=48)
- [Cloud settings viewer](https://solidslime.net/cloud/)
- [Creator's page identifying key 4008.48](https://solidslime.net/2024/09/bpm/)
- [Community manual file-loading instructions](https://github.com/jerryfromearth/ETT-Service-Return-Drills#manual-way)

The manual workflow does not install files, guess keys, extract tokens from logs,
or contact the provider. The optional publishing service described above uses
the observed 11 Hero interface, without claiming official support. Research
links are external and open only on user action.

Key records are **user-recorded and cloud-unverified**, including the in-game
confirmations. A SHA-256 revision binds each record to its original generated
candidate, not to independently verified cloud contents. If a candidate changes
or becomes unavailable, its previous key is flagged for rechecking rather than
presented as current. Match-mode changes do not change these settings or records.

Manual records persist in browser storage, separately for each player. They are not
written into the HTML, JSON profile, or SQLite database. Storage behavior for
`file:` URLs can vary by browser and report location; the local server address
has separate browser storage. Use **Export key records**
for a portable JSON backup; **Import record backup** validates the format,
account, keys, revisions, and confirmations before asking to replace local
records. Importing does not verify a key against the cloud. A malformed backup
or failed storage write leaves existing records unchanged and displays an error.
Unavailable or corrupt local storage is explicit, not silently reset.
Clearing local records requires confirmation and never deletes anything in-game
or in the cloud. Keep calibrated game settings backed up separately: key-record
backups contain neither settings payloads nor authentication credentials.

## Manual 11 Hero evidence imports

You can now import a match's **Export all shots (JSON)** file from 11 Hero,
without scraping the website or guessing a match API. This is distinct from
the existing Hero ball-machine publishing client.

Create a local manifest based on
[the example](docs/hero-import.example.json), replacing the file path, provider
match UUID and player ID, then run:

```powershell
python .\hero_import.py --manifest .\hero-manifest.local.json --player-id 1909208 --output .\output
```

The **Hero imports** dashboard section shows both players, Hits versus Tosses,
provider point groups, raw accepted-row fields, provider labels/flags, declared
metadata and diagnostics. Filter rows or inspect the original provider fields.
Unknown outcomes stay unknown. It also works with no local-log input, using an
empty local profile rather than deriving local scores from Hero annotations.

The **Milestone 1: assisted serve review** panel links opponent serve candidates
to exact revisions and following recorded Hits. Save pending notes or
reference-backed user observations, then export a browser-local review backup.
Real long/backhand placement remains **unknown** pending validated receiver-frame
coordinates, event timing and bounce reconstruction; a deep first bounce is not
enough to call a serve long. Synthetic tests cover both handednesses, receiver
ends, mixed spin and boundary cases, but do not establish real-world accuracy.
Reviews do not change loss statistics or unlock keys. See the
[review workflow and limitations](docs/HERO_IMPORT.md#milestone-one-assisted-review).

- Original file bytes and normalized evidence are stored transactionally in a
  separate `output\hero_imports.sqlite3` archive.
- Re-importing unchanged content and metadata is idempotent. Changes retain
  new revisions instead of overwriting prior evidence.
- A normalized `output\hero_evidence.<player-id>.json` snapshot and the report
  are refreshed. Existing local profiles, snapshots, loss counts and machine
  settings are not altered by import.
- Ordinary local-log rebuilds preserve the archive and include its evidence
  separately in the report. Restart `serve.py` and reload after imports/rebuilds.
- Hero success flags do **not** become local point-loss reasons, receiving
  denominators, catalogue diagnoses or key-generation eligibility.

The supplied reference sample was checked locally: **181 rows / 41 fields /
138 Hits / 43 Tosses / 43 provider point groups**, preserving both players.
Those counts are not hardcoded expectations. The handoff's anomalous match
score summary remains declared, unresolved metadata, not a complete result.
No real exports or private manifests are committed as fixtures.

Read the [import contract, storage and troubleshooting guide](docs/HERO_IMPORT.md)
and [dated research handoff](docs/HERO_IMPORT_DEVELOPER_HANDOFF.md).
The handoff's 55-match discovery is a dated coverage observation, not complete
account history. Clubhouse commentary remains unverified narrative rather than
shot evidence. Automated collection, cross-source matching, unit/label
calibration and representative-feed validation remain future work.

## Ball and paddle-contact telemetry

Each reconstructed point includes its score-snapshot source boundaries and a
`telemetry` object. Explicit point-start and point-end markers bound an attempt;
multiple attempts between score changes are retained separately, not collapsed
into one alleged rally. Missing boundaries are marked `partial` or `unavailable`.
Free-play events outside those markers are not attached.

Recorded features include:

- Authoritative local-sent and remote-received ball hits, with serve/rally phase
  when the adjacent paddle signal states it.
- Outgoing position, velocity, and rotation-rate vectors.
- Incoming ball state for local hits only when a same-frame dynamic collision
  matches the outgoing position, velocity, and rotation rate.
- Ball orientation when present, velocity change, speed magnitude, spin-vector
  magnitude, and raw contact position.
- Local table/net/toss collision events. Remote game-logic collision echoes are
  excluded to avoid double counting.

Hit ownership uses the log's **authenticated account ID**, not an assumption
that the selected profile is always the logging player. Unknown or conflicting
identity leaves hits unattributed. `relativeSender` is retained as raw context
only: at a paddle collision it may still refer to the previous hitter.

All coordinates, engine ticks, and rates remain in **raw log units**. No m/s,
km/h, rpm, calibrated height, or physical paddle-angle claim is made. Paddle
speed, paddle face angle, contact location on the paddle, and continuous swing
paths remain unavailable. Ball orientation must not be mistaken for paddle pose.

`bounded` describes point boundaries, not guaranteed complete measurements.
`measurement_status`, missing-pair notes, and parse warnings flag detected gaps;
even `no_detected_gaps` is not proof of complete motion capture. Aggregate hit
statistics use bounded attempts only; counts are observed contacts, not a
validated rally-length statistic. Raw point telemetry is persisted in SQLite's
`points` table, the JSON profile, and expandable per-match HTML tables.

## Ball-machine practice patterns

The main organization is **three separate training collections**:

| Collection | Planned sequence | Main use |
| --- | --- | --- |
| Serve returns (`serve-returns.candidate.json`) | Repeat one serve feed | Establish legal return consistency before varying serves |
| Rally practice (`rally-practice.candidate.json`) | Alternate two rally feeds | Return consistency and controlled placement changes |
| Combined (`combined.candidate.json`) | Serve, rally feed, rally feed | Practice receiving and continuing a short point-like sequence |

These are timed, **open-loop** sequences. The machine does not react to the
quality or placement of your return. Before training, confirm the game plays
the planned feed order; shuffle is off. The combined candidate proposes a
3-second `PostDelay` on its final feed for recovery, but exact timing semantics
must be checked in-game. Do not interpret `ballCount` as sequence length.

Serve candidates use the numeric fields of the game-default preset explicitly
named `Serve`, extracted only from default `BallLauncherDeviceSettings` blocks.
The selected source file, header line, preset ID, and timestamp are recorded.
Original coaching descriptions are not copied. The newest available logged
default is selected; its existence is not proof that its trajectory or import
works in the current running game. If no valid serve seed is available, the
serve and combined collections are marked unavailable instead of relabeling
a rally feed. Previously generated serve/combined candidate files are then
removed to prevent stale settings being mistaken for current output; unrelated
files in the output folder are untouched. Rally candidates remain available.

The pipeline also retains three **individual rally-feed variation candidates**:

1. **Repeatable contact** (`repeatable-contact.candidate.json`):
   one active feed, all spread zero.
2. **Two-direction recovery** (`two-location-recovery.candidate.json`):
   two active feeds with horizontal aim offsets of -4 and +4 from the supplied
   baseline. Verify their actual landing points and sequence in-game.
3. **Controlled variation** (`controlled-variation.candidate.json`):
   one feed with horizontal-angle spread 1.5; all other spread zero.

Their numeric seed is the user-provided forehand-drive example. Rally candidates retain
its raw position, base aim, speed, spin, and `PostDelay`, enable the shots, and
use a proposed **2-second** interval instead of 1 second. Numbers and booleans
remain strings; the supplied `settingsVersion`, `ballCount`, and `shots.data`
metadata shape are preserved. `ballCount` is not interpreted as the drill's
planned repetition count. Descriptions are newly written, not copied coaching
text. Candidate IDs are unique within each separate settings file.

**Back up current game settings first.** Analysis alone never installs to the headset,
overwrites game settings, uploads data, or creates cloud sharing codes.
These files pass a structural validator based on the supplied example, but
structural validity is not an in-game validation. Do not blindly replace a settings file: inspect a
current game export and verify the import workflow first. Each candidate is a
standalone settings collection, not a merge with your existing library.

The user-provided sample is a rally feed, not a serve template. Raw incoming ball state at
contact is not a launcher origin; rotation-rate vectors are not spin-slider
values. Exact shot recreation requires coordinate/unit mapping and in-game
trajectory validation. Representative incoming rally-contact samples in the
recipes are references only, never direct machine settings.

### Research methodology

Sources checked on **2026-10-24**:

- [Shane Lindsay's Dynamic Drillinator](https://github.com/shanelindsay/ElevenBallMachine):
  controlled, variable, and point-like sequences; progressive difficulty;
  moving the launch origin for more realistic scenarios. The guide explicitly
  concerns the June 2020 machine, so its UI/file instructions are historical.
- [SolidSlime's service-return drills](https://github.com/jerryfromearth/ETT-Service-Return-Drills):
  adapt an existing template, begin with limited variation, then add variation
  and shuffle. Its legacy file and cloud-code instructions are not verified for
  the current game version.

The old `drills.default` format described online differs from the `shots.data`
format in the supplied example and logs. The recipes use those training
principles without copying drill libraries or claiming compatibility with
legacy exports. Targets such as 16/20 successful returns and practice-set sizes
are coaching suggestions, not measured requirements.

## Interpretation and training

The main output is now **training priorities ranked by observed point losses**,
not generic drills or overall match win rate. Every classified lost point stores
its category, raw reason, contact corroboration, and supporting source location.

Ranking uses each observed point once, without a ranked/unranked, recency, or Elo
multiplier. Longer matches naturally contribute more points. Single-step score
changes in incomplete matches are included in point-loss analysis even though
those matches remain excluded from completed-match statistics.

Supported categories are shot-landing failure, missed rally return, point-losing
serve fault, missed serve return, return with unknown context, and contact-rule
losses. Unsupported reasons are explicitly unclassified. A priority requires
**at least five classified losses across two distinct matches**; smaller samples
remain visible as monitoring items. This threshold is an evidence-screening
choice, not a statistical-significance claim.

### Return plans and opponent-specific opportunities

General-practice keys are restricted to missed opponent serves, missed rally
balls, and contacted returns that failed to land. Unknown incoming context can
support only a clearly labelled general return baseline. Each plan needs five
eligible return losses across two matches; conflicting terminal contacts and
observed own serves do not qualify. Own-serve faults remain manual coaching;
contact-rule losses and unclassified outcomes do not generate machine keys.
The publisher recomputes eligibility from the points, rather than trusting
saved plan metadata. Reference collections remain available for inspection,
but cannot be newly published through the API.

The landing-consistency package contains a baseline and a later variation
stage. Only the baseline starts active; switch feed activation manually when
progressing. Rally-recovery feeds start together. Serve-return plans require
the provenance-backed serve template; they never substitute a rally seed.
All these are **generic template-based practice**, not opponent reproductions.
Settings retain stable hashes when only evidence counts or priorities change.
Old cloud journals and manual key backups are preserved; historical uncertain
receipts remain visible under **Advanced -> Saved cloud receipts**, with
explicitly confirmed read-only rechecking and no duplicate upload. Reference
collection JSON downloads remain in their setup dialogs' Advanced tools.

**Opponent-specific opportunities** group eligible return losses by stable
opponent ID and supported incoming context (serve, rally, or unknown), requiring
five losses across two matches *within each group*. The dashboard shows the six
highest-count groups; JSON and selected-mode exports retain all qualifying
groups. Evidence links open the original point/contact records. A contacted
return is attributed to a serve/rally context only when the preceding observed
hit belongs to the opponent in the terminal attempt without known measurement
gaps. Unknown context is never presented as a known serve type.

These counts do not establish return-error rates, technical causes, or a
particular spin family. More losses can reflect more play against an opponent.
**Player-specific keys are withheld until serve/shot reproduction is validated.**
Raw ball states are not calibrated launcher parameters, and generic presets
must not be labelled as that opponent's serves. Cloud read-back verification
checks stored settings, not physical reproduction or in-game compatibility.

The report includes lost-point counts, shares of all observed losses, distinct
matches/opponents, mode and opponent-strength breakdowns, and source examples.
The JSON also contains per-day category counts. Rates labeled "losses per 100
observed points" are not shot-error rates or serve-fault percentages: shot/serve
attempt denominators have not been validated.

The raw score and reason establish the broad loss category. More detailed
serve-versus-rally return classification requires a consistent terminal opponent
hit in a bounded attempt without known measurement gaps. Net contact after the
final player hit is supporting evidence only. It is not proof of an unforced
net error; absence of a net event does not mean a long/wide miss. Mechanical
causes such as paddle angle, forehand/backhand technique, footwork, or spin
misreading are not inferred without supporting measurements.

Practice recipes now carry explicit links to the ranked loss categories.
Shot-landing priorities use the repeatable feed and controlled variation;
missed rally returns use two-location practice that needs in-game calibration. Serve faults use
manual serve practice, and missed serve returns use the separate serve-return
collection when a logged serve template is available. **No serve-machine
settings are generated from the supplied forehand-drive feed.** Numeric
candidate settings use the appropriate template, not a fitted replay of an
observed failure.

Suggested practice volumes and success targets are coaching proposals, not facts
measured from the logs. Loss counts show observed cost, not points guaranteed to
be recoverable. Overall win rate is not a skill diagnosis, especially against
much stronger opponents.

Not yet validated: serve/return performance, rally length, forehand/backhand
classification, calibrated placement, physical velocity/spin units, or detailed
stroke-specific causes of point-ending reasons.

Snapshot rating values are **not** a verified Elo change history or a live
rating. Log timestamps have no timezone, and session duration is not active
practice time. A log with no snapshots is not proof that no play occurred.

Reports contain account names/IDs, match information, and local source paths.
Keep them private or redact them before sharing. The HTML is self-contained,
escapes log-derived text, and loads no external resources.

## Architecture

The application deliberately uses a small stack: Python's standard library,
SQLite, and vanilla JavaScript/CSS/SVG/Canvas. There is no framework build step
or dependency on a hosted dashboard service.

```text
Local .log files
    -> snapshot parsing + file/match deduplication
    -> bounded point/attempt telemetry
    -> loss analysis + first-return evidence
    -> generic practice candidates + shot-category definitions
    -> SQLite / JSON / self-contained HTML dashboard
                              |
                              +-> optional loopback publishing server
                                    -> consented sanitized settings upload
                                    -> exact read-back verification + journal
```

| Component | Responsibility |
| --- | --- |
| [analyst.py](analyst.py) | CLI, snapshot reconstruction, profile generation and persistence |
| [telemetry.py](telemetry.py) | Bounded attempts, hit ownership, paired ball states and measurement quality |
| [loss_analysis.py](loss_analysis.py) | Loss categories, eligibility, mode-specific priorities and opponent opportunities |
| [serve_reception.py](serve_reception.py) | Conservative first-return denominator, outcomes and exclusions |
| [hero_import.py](hero_import.py) | Offline Hero export/manifest validation, raw archive and independent evidence revisions |
| [shot_catalogue.py](shot_catalogue.py) | Shared category vocabulary, naming rules and conditional coaching |
| [practice.py](practice.py) | Reference templates, staged return plans and machine-settings validation |
| [dashboard.py](dashboard.py) | Embedded data and assets, offline report generation |
| [dashboard/](dashboard/) | UI interactions, graphics, spin viewer, catalogue and local records |
| [cloud_publish.py](cloud_publish.py) | Sanitization, publishing eligibility, durable receipts and verification |
| [serve.py](serve.py) | Loopback HTTP server and guarded publish/recheck endpoints |
| [player_settings.json](player_settings.json) | Player-ID-scoped, explicitly confirmed handedness preferences |
| [tests/](tests/) | Synthetic analysis, persistence, browser-model and publishing tests |
| [docs/](docs/) | Developer brief, milestone acceptance criteria and validation protocol |
| [quest_sync.py](quest_sync.py) | Automatic log sync from Quest headset file share |

For a different player's handedness, add an entry under `players` in
[player_settings.json](player_settings.json), using their numeric ID as a string.
Use `handedness: "right"`, `"left"` or `"varies"` and
`source: "user_confirmed"` only after confirming that preference. Missing entries
remain unknown. Do not commit other people's preferences without permission.
Handedness is not a log-axis calibration or a detected stroke classification.

## Quest file share sync

The Eleven Table Tennis app on Quest exposes a local HTTP file share when enabled
in Settings. This provides direct access to logs, settings, and recordings without
USB cables or sideloading tools.

Enable file sharing in-game, note the displayed IP and port (e.g., `172.16.0.15:8090`),
then sync logs:

```powershell
python .\quest_sync.py --host 172.16.0.15:8090 --logs .\11TTLogs
```

Options:

| Flag | Effect |
| --- | --- |
| `--watch 30` | Poll every 30 seconds instead of one-shot sync |
| `--rebuild` | Run `analyst.py` after downloading new logs |
| `--settings` | Also download current ball machine settings |
| `--dry-run` | Show what would be downloaded without downloading |

Watch mode example for continuous capture sessions:

```powershell
python .\quest_sync.py --host 172.16.0.15:8090 --logs .\11TTLogs --watch 30 --rebuild --player-id 1909208
```

This polls every 30 seconds, downloads new/changed logs, and rebuilds the analysis
automatically. Press Ctrl+C to stop. The headset must remain on the same network
with file sharing enabled.

The sync script uses size comparison to detect changes. It does not upload, delete,
or modify files on the headset. Downloaded settings go to
`output/quest_BallLauncherSettings.json` for inspection, separate from the game's
active settings.

## Privacy and repository contents

The repository contains application source, synthetic tests, documentation,
and the original development player's explicit example configuration. It does
**not** contain the raw gameplay logs, complete player profiles, generated HTML
reports, SQLite databases, or cloud publication journals.

- Raw logs may contain authentication material. Never upload them to GitHub
  issues, discussions or pull requests.
- Generated reports contain names/IDs, match evidence and local source paths.
  Self-contained does not mean anonymous; review/redact before sharing.
- Default input/output folders, raw `.log` files, common local databases,
  credentials and environment files are excluded by [.gitignore](.gitignore).
  If using custom output paths, keep them outside the checkout or add explicit
  ignore rules **before staging**.
- Review `git status` and the staged diff before every commit. Ignore rules are
  safeguards, not a comprehensive secret scanner.
- The optional 11 Hero upload shares sanitized drill settings with a public
  community service. It is separate from GitHub publication and always opt-in.
- Preserve cloud journals and export browser records before cleaning local data.
  Do not delete uncertain publication receipts to force another upload.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `python` or `node` is not found | Install the required runtime and reopen the terminal; Node is needed only for tests |
| No logs or no valid local snapshots | Put `.log` files directly in the selected folder and confirm the numeric player ID and supported local snapshot format |
| Very small or empty report | Some logs contain only headers, no match snapshots, or incomplete capture; missing events are not invented |
| `serve.py` cannot find a profile | Run the analysis first; use the same `--output` directory for both commands |
| Port 18765 is occupied | Choose another port, e.g. `python .\serve.py --port 18766`; do not stop unrelated services |
| Browser gets a 403 response | Use the printed `http://127.0.0.1:<port>/` URL and reload after a server restart |
| Report or candidates look stale | Regenerate analysis, restart the server to reload its profile snapshot, and reload the browser |
| No eligible machine plan | Inspect loss thresholds, missing telemetry and serve-template availability; own-serve faults are manual coaching |
| Named category counts are unknown | This is intentional until spin/length/placement classification is validated |
| Publishing says uncertain | Preserve the journal and use read-only **Recheck**, not another upload |
| A verified key behaves unexpectedly | Read-back proves stored settings matched, not game physics; stop the feed and check/calibrate in-game |
| Browser records are missing | File URLs, different report locations, ports and browser profiles can have separate storage; use exported backups |

If analysis fails after committing SQLite but before replacing every report,
rerun the same command to regenerate consistent outputs. Do not run concurrent
analysis jobs against the same output directory.

## Tests

```powershell
python -m unittest discover -s tests -v
node --test .\tests\test_publishing.js .\tests\test_graphics.js .\tests\test_spin.js .\tests\test_pilot.js .\tests\test_catalogue.js .\tests\test_hero.js .\tests\test_hero_review.js
node --check .\dashboard\dashboard.js
```

Python tests use synthetic logs and temporary directories, not private gameplay
files. JavaScript tests use Node's built-in runner (Node 18+) and synthetic models.
The catalogue tests also invoke `python` to verify naming parity between the
backend and browser. Publishing tests use mocked clients/storage and a local
test server; they do not upload real settings to Eleven or 11 Hero.

The tests cover reconstruction, deduplication, measurement gaps, loss eligibility,
receiving outcomes, persistence, settings sanitization, publication uncertainty,
catalogue naming, spin math and graphics. Manual browser checks should also cover
offline operation, narrow-screen layouts, keyboard access, reduced motion and
source-point links. Mock uploads, clipboard writes and record storage when testing
those workflows; do not generate real keys merely to exercise the UI.

## Roadmap and contributing

The next goal is to connect the category vocabulary to trustworthy measured
evidence, then build **most-missed serves** and **most-missed rally shots** across
games and opponents:

1. Validate log-to-receiver coordinates, units and comparable measurement events.
2. Establish receiving-bounce attribution and length/location/spin category rules.
3. Review labeled successful and failed examples, retaining unknowns and exclusions.
4. Rank named categories by lost points, with attempt counts and resolved-outcome
   rates alongside them; do not double-count overlapping families.
5. Validate a representative in-game feed before claiming category-specific or
   opponent-specific reproduction.

Milestone one's original example remains **long sidespin serves to the backhand
side**, including evidence of difficulty, a clear explanation, counter-play,
attempt/error counts and a validated representative feed. A glossary, category
definition or working key alone does not complete that milestone. The broader
first-return pilot is a useful foundation, not a replacement for this gate.

For contributions, describe the observed behaviour and expected result, add
synthetic regression cases, run the relevant tests, and update directly related
documentation. Prefer small changes that preserve provenance, explicit unknown
states, offline operation and consent boundaries. Do not attach private logs;
provide a minimal fabricated example with the same structure instead.

Track work through [GitHub issues](https://github.com/tescolopio/11Analyst/issues)
and the [milestone brief](docs/Eleven_Analyst_Spin_Guide_Developer_Brief.docx).
There is currently **no license file** in this repository; a public repository
alone does not grant an open-source license.
