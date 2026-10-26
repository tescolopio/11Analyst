"""Versioned shot vocabulary and conditional coaching, separate from log classification."""

from copy import deepcopy


VERSION = "shot-lexicon-1"
NAME_TEMPLATE = "{pace} {length} {spin} {context} to {placement}{direction}"
FACETS = {
    "context": {
        "label": "Incoming ball",
        "values": [
            {"id": "serve", "label": "Serve", "name": "serve",
             "definition": "An opponent's service ball; evaluate your first return, not the eventual rally result."},
            {"id": "rally", "label": "Rally ball", "name": "rally ball",
             "definition": "An opponent's ball after service; evaluate the immediate return separately from later shots."},
        ],
    },
    "length": {
        "label": "Length / depth",
        "values": [
            {"id": "short", "label": "Short", "name": "short",
             "definition": "Without a return contact, the ball would bounce again on the receiver's half. This is a flight-length property, not simply a first bounce near the net."},
            {"id": "half_long", "label": "Half-long", "name": "half-long",
             "definition": "Without a return contact, the second receiver-side bounce would be near the end line. The tolerance around that line still needs calibration."},
            {"id": "long", "label": "Long", "name": "long",
             "definition": "Without a return contact, the next bounce would be beyond the receiver's end line. Do not infer this from serve speed or first-bounce location alone."},
            {"id": "mid_depth", "label": "Mid-depth", "name": "mid-depth",
             "definition": "The receiver-side bounce is between the near-net and deep regions. Calibrated region boundaries are not yet defined."},
            {"id": "deep", "label": "Deep", "name": "deep",
             "definition": "The receiver-side bounce is near the end line. Deep describes bounce placement; it is not the same definition as a long serve."},
            {"id": "unknown", "label": "Length unknown", "name": "length-unclassified",
             "definition": "Length/depth has not been established. Missing trajectory evidence is not a short ball."},
        ],
    },
    "placement": {
        "label": "Receiving-side location",
        "values": [
            {"id": "backhand", "label": "Backhand side", "name": "the backhand side",
             "definition": "The receiver's backhand-side region, not proof of the stroke actually played. Mapping needs handedness, receiver orientation and an agreed reference position."},
            {"id": "forehand", "label": "Forehand side", "name": "the forehand side",
             "definition": "The receiver's forehand-side region, not proof of the stroke actually played. A player may move around a ball and use either stroke."},
            {"id": "middle", "label": "Table middle", "name": "the table middle",
             "definition": "A region around the table centreline. This is not automatically the player's elbow or crossover point; those require player-position evidence."},
            {"id": "wide_backhand", "label": "Wide backhand side", "name": "the wide backhand side",
             "definition": "Toward the backhand-side sideline. The width threshold and receiver reference position still need calibration."},
            {"id": "wide_forehand", "label": "Wide forehand side", "name": "the wide forehand side",
             "definition": "Toward the forehand-side sideline. The width threshold and receiver reference position still need calibration."},
            {"id": "unknown", "label": "Placement unknown", "name": "an unclassified location",
             "definition": "Receiving-side placement is unavailable or unvalidated; a raw contact position is not a receiving bounce."},
        ],
    },
    "spin": {
        "label": "Spin family",
        "values": [
            {"id": "top", "label": "Topspin", "name": "topspin", "side": False, "presets": ["top"],
             "definition": "In the illustrative incoming +Z frame, the topspin component is +X. A classification would need calibrated axes, measurement timing and component thresholds."},
            {"id": "back", "label": "Backspin", "name": "backspin", "side": False, "presets": ["back"],
             "definition": "In the illustrative incoming +Z frame, the backspin component is -X. The numerical signs in the logs have not yet been mapped to this frame."},
            {"id": "side", "label": "Sidespin", "name": "sidespin", "side": True,
             "presets": ["clockwise", "counterclockwise"],
             "definition": "A sidespin family with rotation about the vertical axis. This broad label does not prove zero topspin/backspin; determine any vertical-spin component before choosing the return."},
            {"id": "side_top", "label": "Sidespin + topspin", "name": "sidespin-topspin", "side": True,
             "presets": ["topClockwise", "topCounterclockwise"],
             "definition": "Both side and topspin components are present. Direction and balance are separate attributes, not a claim about one fixed spin magnitude."},
            {"id": "side_back", "label": "Sidespin + backspin", "name": "sidespin-backspin", "side": True,
             "presets": ["backClockwise", "backCounterclockwise"],
             "definition": "Both side and backspin components are present. The amount of lift and sideways compensation depends on their strengths."},
            {"id": "none", "label": "Negligible spin", "name": "negligible-spin", "side": False, "presets": ["zero"],
             "definition": "Spin is sufficiently small under an agreed threshold. Missing measurements do not establish negligible spin; no log threshold is calibrated yet."},
            {"id": "axial", "label": "Axial rotation (advanced)", "name": "axial-spin", "side": False, "presets": ["axial"],
             "definition": "Rotation around the travel direction. It is a separate component; no automated response or calibrated bounce prediction is supplied."},
            {"id": "unknown", "label": "Spin unknown", "name": "spin-unclassified", "side": False, "presets": [],
             "definition": "Spin family cannot be established. Do not replace unknown with zero or use machine sliders as measured angular velocity."},
        ],
    },
    "direction": {
        "label": "Sidespin direction",
        "values": [
            {"id": "unspecified", "label": "Not established", "name": " (sidespin direction unspecified)",
             "definition": "The sidespin family is defined, but its clockwise/counterclockwise direction is not established."},
            {"id": "clockwise", "label": "Clockwise viewed from above", "name": " (clockwise viewed from above)",
             "definition": "Clockwise viewed from above corresponds to -Y in the illustrative receiver frame. Camera choice and handedness do not change this label."},
            {"id": "counterclockwise", "label": "Counterclockwise viewed from above", "name": " (counterclockwise viewed from above)",
             "definition": "Counterclockwise viewed from above corresponds to +Y in the illustrative receiver frame. No ambiguous left/right sidespin alias is used."},
            {"id": "not_applicable", "label": "Not applicable", "name": "",
             "definition": "No sidespin direction is assigned for this family. This is distinct from an unknown direction on a sidespin ball."},
        ],
    },
    "pace": {
        "label": "Pace",
        "values": [
            {"id": "unknown", "label": "Not established", "name": "",
             "definition": "Pace is not established; there are no calibrated slow/medium/fast speed bands yet."},
            {"id": "slow", "label": "Slow", "name": "slow",
             "definition": "A slow-pace category under a future agreed reference and measurement event, not an absolute m/s claim."},
            {"id": "medium", "label": "Medium", "name": "medium-pace",
             "definition": "A medium-pace category under a future agreed reference and measurement event. It is not inferred from animation speed."},
            {"id": "fast", "label": "Fast", "name": "fast",
             "definition": "A fast-pace category under a future agreed reference and measurement event. Measurements before and after bounces must not be mixed."},
        ],
    },
}
CONTEXT_LENGTHS = {
    "serve": ["short", "half_long", "long", "unknown"],
    "rally": ["short", "mid_depth", "deep", "unknown"],
}
GUIDANCE = {
    "context": {
        "serve": ["Read length and the top/back component before committing to a return. A sidespin name alone does not determine the racket angle."],
        "rally": ["Recover to a ready position after the previous shot and use a compact response before adding pace."],
    },
    "length": {
        "short": ["Move into comfortable reach. Depending on spin and height, use a controlled short touch or an attacking flick; do not use the same action for every short ball."],
        "half_long": ["Judge whether the ball will clear the end line. If it does, create room for a controlled opening; if it stays short, use a touch or flick suited to the spin."],
        "long": ["Prepare space for a controlled drive or topspin opening rather than treating the ball as a short touch. Adjust lift and racket angle to the top/back component."],
        "mid_depth": ["Use the available time to set up a balanced, repeatable contact before attempting a wider or faster return."],
        "deep": ["Create enough space for a compact contact; avoid being crowded by the bounce near the end line."],
        "unknown": ["Establish length/depth first; do not prescribe a short-ball or deep-ball response without it."],
    },
    "spin": {
        "top": ["Use a relatively closed racket angle with a compact block or counter, adjusted to the ball's height and spin. Excessive upward lift can send the return long."],
        "back": ["Account for the underspin: lift with controlled topspin when attacking, or use an appropriately open racket for a push. Increase lift if repeated contacts fall into the net."],
        "side": ["Start with a broad central target. Observe whether returns drift sideways, then adjust aim and racket angle against that drift. Identify any topspin/backspin component before deciding how much lift to use."],
        "side_top": ["Combine a compact topspin/block response with compensation for sideways drift. Avoid treating this as backspin and adding unnecessary lift."],
        "side_back": ["Combine enough lift for the backspin with compensation for sideways drift. Separate net errors from side misses while adjusting."],
        "none": ["Do not add the lift or spin compensation you would use against heavy backspin or sidespin. Use a controlled stroke and reassess if the ball behaves differently."],
        "axial": ["Observe the actual bounce and return behaviour first. No specific racket-angle prescription follows from the axial label alone."],
        "unknown": ["Identify spin through observation before choosing a spin-specific correction. A missed return does not by itself reveal the spin family."],
    },
    "placement": {
        "backhand": ["Prepare a comfortable backhand-side contact. The target-side label does not forbid a forehand response if you have time and position."],
        "forehand": ["Get into a comfortable forehand-side position instead of reaching for the ball late."],
        "middle": ["Make an early choice of stroke; table-middle placement is not proof that the ball targeted your playing elbow."],
        "wide_backhand": ["Move toward the wide backhand-side ball rather than relying only on reach, then recover for the next shot."],
        "wide_forehand": ["Move toward the wide forehand-side ball rather than relying only on reach, then recover for the next shot."],
        "unknown": ["Confirm the receiving location before choosing a placement-specific adjustment."],
    },
}
PADDLE_TECHNIQUE = {
    "spin": {
        "top": {
            "face_angle": "closed",
            "description": "Tilt paddle forward/down to counter upward kick",
            "error_if_wrong": "Ball flies long if paddle too open",
        },
        "back": {
            "face_angle": "open",
            "description": "Tilt paddle back/up to lift the ball over the net",
            "error_if_wrong": "Ball drops into net if paddle too closed",
        },
        "side": {
            "face_angle": "angled_into_spin",
            "description": "Angle paddle face against the sidespin direction",
            "error_if_wrong": "Ball drifts sideways off intended target",
        },
        "side_top": {
            "face_angle": "closed_plus_sideways",
            "description": "Close face for topspin, angle into sidespin direction",
            "error_if_wrong": "Ball goes long and/or drifts sideways",
        },
        "side_back": {
            "face_angle": "open_plus_sideways",
            "description": "Open face for backspin, angle into sidespin direction",
            "error_if_wrong": "Ball drops into net and/or drifts sideways",
        },
        "none": {
            "face_angle": "neutral",
            "description": "Neutral paddle angle; do not add spin compensation",
            "error_if_wrong": "Adding unnecessary compensation causes errors",
        },
        "axial": {
            "face_angle": "observe_first",
            "description": "Observe bounce behavior before choosing angle",
            "error_if_wrong": "No standard prescription for axial spin",
        },
        "unknown": {
            "face_angle": "identify_first",
            "description": "Identify the spin type before applying correction",
            "error_if_wrong": "Wrong compensation for unidentified spin",
        },
    },
    "direction": {
        "clockwise": {
            "aim_adjustment": "right",
            "description": "Ball curves left to receiver; aim right to compensate",
        },
        "counterclockwise": {
            "aim_adjustment": "left",
            "description": "Ball curves right to receiver; aim left to compensate",
        },
        "unspecified": {
            "aim_adjustment": "observe",
            "description": "Watch ball curve direction and adjust aim accordingly",
        },
        "not_applicable": {
            "aim_adjustment": "none",
            "description": "No sidespin direction to compensate for",
        },
    },
    "length": {
        "short": {
            "positioning": "move_in",
            "stroke_options": ["touch", "flick", "push"],
        },
        "half_long": {
            "positioning": "read_length",
            "stroke_options": ["touch", "flick", "drive"],
        },
        "long": {
            "positioning": "create_space",
            "stroke_options": ["drive", "loop", "counter"],
        },
        "mid_depth": {
            "positioning": "balanced_ready",
            "stroke_options": ["drive", "counter"],
        },
        "deep": {
            "positioning": "step_back",
            "stroke_options": ["compact_drive", "block"],
        },
        "unknown": {
            "positioning": "ready_position",
            "stroke_options": ["read_first"],
        },
    },
}
GATES = [
    "Convert log axes and angular-velocity units into the receiver frame and validate signs at an agreed measurement event.",
    "Establish receiver orientation, handedness/reference position and receiving-bounce attribution before naming placement.",
    "Validate length/depth inference and agree boundaries for half-long, deep, wide, negligible-spin and pace labels.",
    "Review labeled successful and failed examples across matches; keep unknowns and immediate-return outcomes separate.",
    "Only then rank named categories by observed point losses, alongside attempts, resolved coverage and error rates.",
    "Validate a representative feed's category fidelity before offering a category-specific key. Existing generic keys do not prove that fidelity.",
]


def selected_values(facets):
    if not isinstance(facets, dict) or set(facets) != set(FACETS):
        raise ValueError("Shot category requires exactly the supported facets")
    selected = {}
    for key, value in facets.items():
        if not isinstance(value, str):
            raise ValueError(f"Invalid {key} category")
        selected[key] = next((item for item in FACETS[key]["values"] if item["id"] == value), None)
        if selected[key] is None:
            raise ValueError(f"Unknown {key} category: {value}")
    if facets["length"] not in CONTEXT_LENGTHS[facets["context"]]:
        raise ValueError("Length/depth category does not apply to this context")
    if selected["spin"]["side"] == (facets["direction"] == "not_applicable"):
        raise ValueError("Sidespin direction does not apply to this spin family")
    return selected


def describe(facets):
    selected = selected_values(facets)
    name = " ".join(NAME_TEMPLATE.format(**{key: value["name"] for key, value in selected.items()}).split())
    spin_tech = PADDLE_TECHNIQUE["spin"].get(facets["spin"], {})
    dir_tech = PADDLE_TECHNIQUE["direction"].get(facets["direction"], {})
    len_tech = PADDLE_TECHNIQUE["length"].get(facets["length"], {})
    return {
        "id": "--".join(facets[key] for key in FACETS),
        "name": name[0].upper() + name[1:],
        "facets": dict(facets), "taxonomy_version": VERSION,
        "source_kind": "category_definition", "evidence_status": "not_classified",
        "observed_attempts": None, "observed_failures": None, "observed_matches": None,
        "machine_key_eligible": False,
        "recognition": [selected[key]["definition"] for key in FACETS],
        "counter_play": [line for key in GUIDANCE for line in GUIDANCE[key][facets[key]]],
        "paddle_technique": {
            "face_angle": spin_tech.get("face_angle"),
            "face_description": spin_tech.get("description"),
            "error_if_wrong": spin_tech.get("error_if_wrong"),
            "aim_adjustment": dir_tech.get("aim_adjustment"),
            "aim_description": dir_tech.get("description"),
            "positioning": len_tech.get("positioning"),
            "stroke_options": len_tech.get("stroke_options"),
        },
        "success_criteria": [
            "On a valid incoming feed, your return clears the net and lands legally on the opponent's half.",
            "Choose a generous target before practice; record legal returns and target hits separately.",
            "Record net, long and side errors, then change one aspect at a time. These are suggested checks, not a diagnosis of your technique.",
        ],
    }


def build():
    specs = [
        ("serve", "long", "backhand", "side", "unspecified"),
        ("serve", "short", "backhand", "back", "not_applicable"),
        ("serve", "short", "forehand", "back", "not_applicable"),
        ("serve", "half_long", "middle", "side_back", "unspecified"),
        ("serve", "long", "backhand", "top", "not_applicable"),
        ("serve", "long", "forehand", "back", "not_applicable"),
        ("serve", "short", "middle", "none", "not_applicable"),
        ("rally", "deep", "backhand", "top", "not_applicable"),
        ("rally", "deep", "forehand", "top", "not_applicable"),
        ("rally", "deep", "backhand", "back", "not_applicable"),
        ("rally", "mid_depth", "wide_forehand", "side_top", "unspecified"),
        ("rally", "short", "forehand", "back", "not_applicable"),
    ]
    categories = [
        describe(dict(zip(("context", "length", "placement", "spin", "direction", "pace"), (*spec, "unknown"))))
        for spec in specs
    ]
    categories[0]["milestone_example"] = True
    return {
        "format": "11analyst.shot-catalogue", "version": 1, "taxonomy_version": VERSION,
        "status": "definitions_ready_log_classification_pending",
        "name_template": NAME_TEMPLATE, "facets": deepcopy(FACETS), "context_lengths": deepcopy(CONTEXT_LENGTHS),
        "default_lengths": {"serve": "long", "rally": "deep"},
        "guidance": deepcopy(GUIDANCE), "categories": categories, "classification_gates": list(GATES),
        "limits": [
            "These are named category definitions and conditional coaching, not findings that you face or struggle with these shots.",
            "Not classified means unknown counts, not zero occurrences. No raw vector, illustrative spin control or machine slider is automatically treated as a calibrated shot label.",
            "Handedness describes the receiving side, not the stroke actually played. Table middle is not automatically the playing elbow.",
            "Categories overlap: a broad sidespin family can include side-topspin and side-backspin subtypes. Future loss ranking must assign each attempt once at the chosen level.",
            "The milestone example is long sidespin serves to the backhand side. Its exact sidespin direction and personal difficulty still require evidence.",
        ],
    }
