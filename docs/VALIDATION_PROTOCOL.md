# Milestone 1 validation protocol: controlled capture

Research date: 2026-10-25. Repository at
[`d338a7c`](https://github.com/tescolopio/11Analyst/commit/d338a7c3b730a5ed6ce20ee6d97ab62650716834).

## Purpose

Establish whether the imported serve data supports the milestone category:
**long sidespin serves to your backhand**. Synthetic tests verify logic paths,
not real-world accuracy. This protocol obtains ground-truth observations for
coordinate mapping, spin conventions, timing, and bounce reconstruction.

Until this validation is complete, category-specific attempts, errors, and
difficulty remain **unknown—not zero**. Generic drills remain available without
claiming they reproduce the milestone category.

---

## Capture-readiness checklist

Complete before the capture session.

| Item | Ready | Notes |
|------|-------|-------|
| Eleven Table Tennis installed and updated | ☐ | Record exact game version |
| Hero upload configured and working | ☐ | Verify a test upload appears in Hero |
| Video recording setup tested | ☐ | Camera angle shows full table and both bounce locations |
| Timestamp synchronization method chosen | ☐ | Options: verbal callout, visible timer, or game clock reference |
| Player settings documented | ☐ | Paddle model, rubber, grip; save screenshot |
| Ball machine / drill settings template ready | ☐ | Blank form or spreadsheet for each trial |
| Log export location known | ☐ | `%LOCALAPPDATA%\Eleven Table Tennis VR\` or equivalent |
| Hero export procedure tested | ☐ | Match → Shots → Export all shots (JSON) |
| Trial ID scheme defined | ☐ | e.g., `val-001`, `val-002`... shared across all artifacts |
| Backup storage prepared | ☐ | Separate directory for raw logs, exports, video, labels |
| Labeling template ready | ☐ | Columns: trial ID, serve type, bounce positions, spin observed, uncertainty |

---

## Pre-capture documentation

Record before any trial begins.

### Environment

| Parameter | Value |
|-----------|-------|
| Game version | |
| Platform (Quest, PC VR, spectator) | |
| Date and local time | |
| Receiver handedness | |
| Receiver starting table side | |
| Paddle settings (model, rubbers, grip) | |

### Coordinate frame reference

Sketch or photograph the table from above. Mark:
- Your starting position (receiver)
- Backhand side (receiver-left for right-handed, receiver-right for left-handed)
- Forehand side
- Net position
- End lines
- Expected positive X, Y, Z directions based on any available documentation

---

## Capture protocol

### Phase 1: Bounce observation (no return)

Capture serves without returning the ball so both bounce locations are visible
on video.

| Trial type | Description | Minimum trials |
|------------|-------------|----------------|
| Long to backhand | Serve landing deep, second bounce would pass end line, to receiver-left (RH) | 3 |
| Short to backhand | Serve landing near net, second bounce would stay on table, to receiver-left (RH) | 3 |
| Deep first bounce (not long) | First bounce deep but second bounce stays on table | 3 |
| Long to forehand | Long serve to receiver-right (RH) | 3 |
| Sidespin left | Visible left curve or kick | 2 |
| Sidespin right | Visible right curve or kick | 2 |
| Mixed side/backspin | Combined rotation visible in bounce behavior | 2 |

For each trial:
1. Announce trial ID audibly before serve.
2. Let ball bounce twice without returning.
3. Note first bounce position (near net / mid-table / deep).
4. Note second bounce position (on table / past end line / off side).
5. Note visible spin effect on bounce.
6. Record any uncertainty immediately.

### Phase 2: Return practice

Capture a separate block where serves are returned normally.

- Use the same serve types as Phase 1.
- Minimum 5 returns per category where possible.
- Note return outcome (in play, net, off table, winner).

### Phase 3: Table side switch

After completing Phases 1 and 2:
1. Switch receiver table sides.
2. Repeat selected cases from Phase 1 (minimum 2 long backhand, 2 long forehand).
3. Document how backhand/forehand mapping changes with position.

---

## Data preservation

### Required artifacts per session

| Artifact | Filename convention | Location |
|----------|---------------------|----------|
| Raw game logs | `val-session-YYYYMMDD-raw/` | Backup storage |
| Hero JSON export | `val-session-YYYYMMDD-hero.json` | Backup storage |
| Video recording | `val-session-YYYYMMDD.mp4` | Backup storage |
| Manual labels | `val-session-YYYYMMDD-labels.csv` | Backup storage |
| Environment record | `val-session-YYYYMMDD-env.txt` | Backup storage |

### Label file columns

```
trial_id, serve_type, first_bounce_zone, second_bounce_zone, spin_observed, receiver_side, uncertainty_notes
```

Zones: `near-net`, `mid`, `deep`, `past-end`, `off-side-left`, `off-side-right`, `unknown`

Spin observed: `left`, `right`, `back`, `top`, `none`, `mixed`, `unknown`

**Record uncertain observations as `unknown`, not omitted or guessed.**

### Shared trial IDs

Every artifact must reference the same trial ID scheme:
- Video: audible announcement
- Labels: `trial_id` column
- Export matching: by timestamp correlation with video

---

## Acceptance criteria

Define these thresholds **before** reviewing capture data.

### Coordinate mapping

| Criterion | Pass condition |
|-----------|----------------|
| Backhand side identification | Exported coordinates for known backhand serves cluster on expected receiver-left region |
| Forehand side identification | Exported coordinates for known forehand serves cluster on expected receiver-right region |
| Position units | Documented conversion between export units and table dimensions (2.74m × 1.525m) |

### Spin direction and units

| Criterion | Pass condition |
|-----------|----------------|
| Sidespin direction | `spinDirection` or `rrate*` components correctly distinguish left vs right spin across labeled trials |
| Spin unit scale | Documented relationship between export values and physical rotation (RPM or rad/s) |
| Mixed spin representation | Combined spin types produce expected component combinations |

### Bounce reconstruction

| Criterion | Pass condition |
|-----------|----------------|
| Long serve classification | Serves labeled "long" in manual observations are classified as long by bounce prediction |
| Short serve classification | Serves labeled "short" are not misclassified as long |
| Deep-but-not-long distinction | Deep first bounces with second bounce on table are correctly distinguished from long serves |
| Agreement threshold | ≥80% agreement between predicted and observed bounce positions |

### Timing

| Criterion | Pass condition |
|-----------|----------------|
| Event sequence | Export timestamps order matches video event sequence |
| Timestamp precision | Timestamps resolve individual contacts within a rally |

---

## Review process

1. Complete capture session following this protocol.
2. Preserve all artifacts with shared trial IDs.
3. **Do not run classification code against capture data until manual review is complete.**
4. Compare manual labels against export fields for each criterion.
5. Document discrepancies with specific trial IDs and evidence.
6. Update acceptance status for each criterion.

### Validation status template

```
## Validation session: YYYY-MM-DD

### Coordinate mapping
- Backhand identification: [ ] Pass [ ] Fail [ ] Inconclusive
- Forehand identification: [ ] Pass [ ] Fail [ ] Inconclusive
- Position units: [ ] Documented [ ] Unknown

### Spin
- Direction agreement: [ ] Pass [ ] Fail [ ] Inconclusive
- Units documented: [ ] Yes [ ] No
- Mixed spin: [ ] Pass [ ] Fail [ ] Not tested

### Bounce reconstruction
- Long serves: ___/___  correct (___%)
- Short serves: ___/___ correct (___%)
- Deep-not-long: ___/___ correct (___%)

### Timing
- Sequence correct: [ ] Yes [ ] No
- Precision adequate: [ ] Yes [ ] No

### Overall
- Ready for category classification: [ ] Yes [ ] No
- Blocking issues:
```

---

## What this validation does not cover

- Automatic collection of all 55 discovered matches
- Broad API integration or cross-source merging
- Additional serve categories beyond the milestone target
- Visual polish or UI improvements
- Practice feed tolerance validation (separate protocol needed)

---

## Next steps after validation

| Outcome | Action |
|---------|--------|
| All criteria pass | Classify reviewed sample, report attempts/errors/uncertainty, proceed to practice feed validation |
| Coordinate mapping fails | Document frame transformation, update classification logic, re-validate |
| Spin conventions wrong | Document correct conventions, update spin handling, re-validate |
| Bounce reconstruction unreliable | Investigate physics assumptions, consider alternative approach, re-validate |
| Insufficient data | Extend capture session with additional trials |

**Real-world validation remains pending until this protocol is executed and reviewed.**
