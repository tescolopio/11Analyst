"""
Shot analysis framework for recognizing incoming shots and evaluating counter responses.

This module provides:
1. Provisional shot classification from telemetry (pending coordinate validation)
2. Expected counter-play patterns for each shot type
3. Comparison of actual player responses to expected patterns
4. Success/failure pattern identification

All classifications are provisional until coordinate frame, spin conventions,
and bounce reconstruction are validated per VALIDATION_PROTOCOL.md.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShotSignature:
    """Telemetry signature for classifying an incoming shot."""

    # Position classification thresholds (provisional, unvalidated)
    POSITION_LEFT_THRESHOLD = -0.2
    POSITION_RIGHT_THRESHOLD = 0.2

    # Spin magnitude thresholds (provisional)
    HIGH_SPIN_THRESHOLD = 10000
    LOW_SPIN_THRESHOLD = 3000

    # Spin axis dominance threshold (fraction of total)
    AXIS_DOMINANCE_THRESHOLD = 0.5

    @staticmethod
    def classify_placement(x: float) -> str:
        """Classify placement from X coordinate (provisional)."""
        if x < ShotSignature.POSITION_LEFT_THRESHOLD:
            return "left"
        elif x > ShotSignature.POSITION_RIGHT_THRESHOLD:
            return "right"
        else:
            return "middle"

    @staticmethod
    def classify_spin(rotation_rate: list[float]) -> dict:
        """
        Classify spin from rotation rate components.

        Returns dict with:
        - type: primary spin classification
        - magnitude: total spin magnitude
        - dominant_axis: which axis dominates
        - components: breakdown of rx, ry, rz contributions
        """
        rx, ry, rz = rotation_rate
        magnitude = math.sqrt(rx*rx + ry*ry + rz*rz)

        if magnitude < ShotSignature.LOW_SPIN_THRESHOLD:
            return {
                "type": "negligible",
                "magnitude": magnitude,
                "dominant_axis": None,
                "components": {"rx": rx, "ry": ry, "rz": rz},
            }

        abs_rx, abs_ry, abs_rz = abs(rx), abs(ry), abs(rz)
        total_abs = abs_rx + abs_ry + abs_rz

        # Determine dominant axis
        if abs_ry / total_abs > ShotSignature.AXIS_DOMINANCE_THRESHOLD:
            dominant = "Y"
            spin_type = "sidespin"
        elif abs_rx / total_abs > ShotSignature.AXIS_DOMINANCE_THRESHOLD:
            dominant = "X"
            spin_type = "topspin" if rx > 0 else "backspin"
        elif abs_rz / total_abs > ShotSignature.AXIS_DOMINANCE_THRESHOLD:
            dominant = "Z"
            spin_type = "corkscrew"
        else:
            # Mixed spin
            dominant = None
            if abs_ry > ShotSignature.LOW_SPIN_THRESHOLD:
                if abs_rx > ShotSignature.LOW_SPIN_THRESHOLD:
                    spin_type = "side_top" if rx > 0 else "side_back"
                else:
                    spin_type = "sidespin"
            elif abs_rx > ShotSignature.LOW_SPIN_THRESHOLD:
                spin_type = "topspin" if rx > 0 else "backspin"
            else:
                spin_type = "mixed"

        return {
            "type": spin_type,
            "magnitude": magnitude,
            "dominant_axis": dominant,
            "components": {"rx": rx, "ry": ry, "rz": rz},
            "direction": "clockwise" if ry < 0 else "counterclockwise" if ry > 0 else None,
        }

    @staticmethod
    def classify_velocity(velocity: list[float]) -> dict:
        """Classify velocity characteristics."""
        vx, vy, vz = velocity
        speed = math.sqrt(vx*vx + vy*vy + vz*vz)

        return {
            "speed": speed,
            "forward_component": abs(vz),
            "lateral_component": abs(vx),
            "vertical_component": vy,
            "direction": "toward_receiver" if vz > 0 else "away_from_receiver",
        }


@dataclass
class ExpectedCounter:
    """Expected counter-play response for a shot type."""

    # Face angle expectations
    face_angle: str  # closed, open, neutral, angled_left, angled_right
    face_description: str

    # Aim adjustment
    aim_adjustment: str  # left, right, none
    aim_description: str

    # Expected return characteristics (relative to incoming)
    expected_spin_response: str  # "match", "counter", "neutral"
    expected_lift: str  # "high", "medium", "low", "negative"

    # Error patterns if wrong technique used
    likely_error_if_face_wrong: str  # "net", "long", "side_left", "side_right"
    likely_error_if_aim_wrong: str


# Counter-play expectations by spin type
SPIN_COUNTERS = {
    "topspin": ExpectedCounter(
        face_angle="closed",
        face_description="Close paddle face to counter upward kick",
        aim_adjustment="none",
        aim_description="No lateral adjustment needed",
        expected_spin_response="counter",
        expected_lift="low",
        likely_error_if_face_wrong="long",
        likely_error_if_aim_wrong="none",
    ),
    "backspin": ExpectedCounter(
        face_angle="open",
        face_description="Open paddle face to lift the ball",
        aim_adjustment="none",
        aim_description="No lateral adjustment needed",
        expected_spin_response="counter",
        expected_lift="high",
        likely_error_if_face_wrong="net",
        likely_error_if_aim_wrong="none",
    ),
    "sidespin": ExpectedCounter(
        face_angle="angled_into_spin",
        face_description="Angle paddle into the spin direction",
        aim_adjustment="into_spin",
        aim_description="Aim against the curve direction",
        expected_spin_response="neutral",
        expected_lift="medium",
        likely_error_if_face_wrong="side_drift",
        likely_error_if_aim_wrong="side_miss",
    ),
    "side_top": ExpectedCounter(
        face_angle="closed_plus_angle",
        face_description="Close face AND angle into sidespin",
        aim_adjustment="into_spin",
        aim_description="Aim against curve with compact stroke",
        expected_spin_response="counter",
        expected_lift="low",
        likely_error_if_face_wrong="long_and_side",
        likely_error_if_aim_wrong="side_miss",
    ),
    "side_back": ExpectedCounter(
        face_angle="open_plus_angle",
        face_description="Open face AND angle into sidespin",
        aim_adjustment="into_spin",
        aim_description="Aim against curve with lift",
        expected_spin_response="counter",
        expected_lift="high",
        likely_error_if_face_wrong="net_and_side",
        likely_error_if_aim_wrong="side_miss",
    ),
    "negligible": ExpectedCounter(
        face_angle="neutral",
        face_description="Neutral paddle angle",
        aim_adjustment="none",
        aim_description="Direct aim to target",
        expected_spin_response="neutral",
        expected_lift="medium",
        likely_error_if_face_wrong="unnecessary_compensation",
        likely_error_if_aim_wrong="none",
    ),
}


@dataclass
class ResponseAnalysis:
    """Analysis of player's actual response vs expected."""

    incoming_classification: dict
    expected_counter: ExpectedCounter
    actual_response: dict

    # Computed comparisons
    lift_appropriate: Optional[bool] = None
    spin_response_appropriate: Optional[bool] = None
    lateral_compensation: Optional[float] = None

    # Outcome
    point_won: bool = False
    error_type: Optional[str] = None

    def analyze(self):
        """Compare actual response to expected."""
        expected = self.expected_counter
        actual = self.actual_response

        # Check lift appropriateness
        actual_lift = actual.get("return_vel_y", 0)
        if expected.expected_lift == "high":
            self.lift_appropriate = actual_lift > 2.5
        elif expected.expected_lift == "low":
            self.lift_appropriate = actual_lift < 2.0
        else:
            self.lift_appropriate = 1.5 < actual_lift < 3.0

        # Check spin response
        serve_ry = self.incoming_classification.get("spin", {}).get("components", {}).get("ry", 0)
        return_ry = actual.get("return_ry", 0)

        # For sidespin, check if return compensates appropriately
        if abs(serve_ry) > 3000:
            # Negative correlation expected (compensating)
            same_direction = (serve_ry > 0 and return_ry > 0) or (serve_ry < 0 and return_ry < 0)
            self.spin_response_appropriate = not same_direction
            self.lateral_compensation = -return_ry / serve_ry if serve_ry != 0 else 0


def classify_incoming_shot(position: list[float], velocity: list[float],
                           rotation_rate: list[float], phase: str = "serve") -> dict:
    """
    Classify an incoming shot from telemetry.

    Returns a comprehensive classification dict.
    All classifications are PROVISIONAL pending validation.
    """
    placement = ShotSignature.classify_placement(position[0])
    spin = ShotSignature.classify_spin(rotation_rate)
    vel = ShotSignature.classify_velocity(velocity)

    return {
        "provisional": True,
        "validation_status": "pending",
        "phase": phase,
        "placement": placement,
        "spin": spin,
        "velocity": vel,
        "position_raw": position,
        "catalogue_mapping": {
            "placement": {
                "left": "backhand",  # For right-hander
                "right": "forehand",
                "middle": "middle",
            }.get(placement, "unknown"),
            "spin": spin["type"],
            "direction": spin.get("direction", "unspecified"),
        },
    }


def get_expected_counter(classification: dict) -> ExpectedCounter:
    """Get expected counter-play for a classified shot."""
    spin_type = classification.get("spin", {}).get("type", "negligible")
    return SPIN_COUNTERS.get(spin_type, SPIN_COUNTERS["negligible"])


def analyze_response(serve_classification: dict, return_telemetry: dict,
                     point_won: bool, error_reason: str = None) -> ResponseAnalysis:
    """
    Analyze a player's return response against the expected counter.
    """
    expected = get_expected_counter(serve_classification)

    analysis = ResponseAnalysis(
        incoming_classification=serve_classification,
        expected_counter=expected,
        actual_response=return_telemetry,
        point_won=point_won,
        error_type=error_reason,
    )
    analysis.analyze()

    return analysis


def build_shot_difficulty_ranking(serve_return_pairs: list[dict]) -> list[dict]:
    """
    Build a ranking of shot types by difficulty (failure rate).

    Input: list of dicts with serve telemetry, return telemetry, and outcome
    Output: list of shot type stats sorted by difficulty
    """
    from collections import defaultdict

    stats = defaultdict(lambda: {"attempts": 0, "wins": 0, "examples": []})

    for pair in serve_return_pairs:
        serve = pair.get("serve", {})
        pos = serve.get("position", [0, 0, 0])
        rot = serve.get("rotation_rate", [0, 0, 0])

        classification = classify_incoming_shot(pos, [0, 0, 0], rot)
        key = f"{classification['placement']}_{classification['spin']['type']}"

        stats[key]["attempts"] += 1
        if pair.get("point_won"):
            stats[key]["wins"] += 1
        if len(stats[key]["examples"]) < 5:
            stats[key]["examples"].append(pair)

    # Convert to ranked list
    ranking = []
    for key, data in stats.items():
        if data["attempts"] >= 10:  # Minimum sample size
            failure_rate = 1 - (data["wins"] / data["attempts"])
            ranking.append({
                "shot_type": key,
                "attempts": data["attempts"],
                "wins": data["wins"],
                "failure_rate": failure_rate,
                "examples": data["examples"],
            })

    # Sort by failure rate (highest difficulty first)
    ranking.sort(key=lambda x: x["failure_rate"], reverse=True)

    return ranking
