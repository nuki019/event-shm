"""Leakage-resistant metrics for the frozen long-term alarm protocol."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import chi2


@dataclass(frozen=True)
class RobustScoreModel:
    """Per-path high-tail normalization fitted on healthy calibration data."""

    median: np.ndarray
    mad_scale: np.ndarray

    @classmethod
    def fit(cls, healthy_features: np.ndarray) -> "RobustScoreModel":
        healthy_features = np.asarray(healthy_features, dtype=np.float64)
        if healthy_features.ndim != 2:
            raise ValueError("healthy_features must have shape (records, paths)")
        median = np.median(healthy_features, axis=0)
        mad = np.median(np.abs(healthy_features - median), axis=0)
        # 1.4826 makes a Gaussian MAD comparable to standard deviation.  The
        # floor protects constant paths without allowing division by zero.
        mad_scale = np.maximum(1.4826 * mad, 1e-12)
        return cls(median=median, mad_scale=mad_scale)

    def score(self, features: np.ndarray) -> np.ndarray:
        features = np.asarray(features, dtype=np.float64)
        if features.shape[-1] != len(self.median):
            raise ValueError("feature path count differs from calibration model")
        z = (features - self.median) / self.mad_scale
        return np.max(z, axis=-1)


def frozen_threshold_grid(calibration_scores: np.ndarray) -> np.ndarray:
    """Predeclared high-tail thresholds derived from calibration only."""

    calibration_scores = np.asarray(calibration_scores, dtype=np.float64)
    if calibration_scores.ndim != 1 or not len(calibration_scores):
        raise ValueError("calibration_scores must be a non-empty vector")
    quantiles = np.array([0.90, 0.95, 0.975, 0.99, 0.995, 0.9975, 0.999, 0.9995, 0.9999])
    return np.quantile(calibration_scores, quantiles)


def incident_starts(times: np.ndarray, exceeded: np.ndarray, merge_gap_minutes: int = 30) -> np.ndarray:
    """Return one start per incident, merging persistent/repeated excursions.

    A later exceedance belongs to the same incident whenever it occurs within
    ``merge_gap_minutes`` of the previous exceedance.  This makes a sustained
    condition one alert instead of hundreds of record-level false calls.
    """

    times = np.asarray(times).astype("datetime64[s]")
    exceeded = np.asarray(exceeded, dtype=bool)
    if len(times) != len(exceeded):
        raise ValueError("times and exceeded must have identical length")
    active = times[exceeded]
    if not len(active):
        return np.empty(0, dtype="datetime64[s]")
    gaps = np.diff(active).astype("timedelta64[s]").astype(np.int64)
    starts = np.concatenate(([True], gaps > merge_gap_minutes * 60))
    return active[starts]


def exposure_days(times: np.ndarray) -> float:
    """Wall-clock exposure including one median sampling interval at the end."""

    times = np.asarray(times).astype("datetime64[s]")
    if not len(times):
        return 0.0
    if len(times) == 1:
        return 1.0 / 24.0
    intervals = np.diff(times).astype("timedelta64[s]").astype(np.int64)
    cadence = max(1, int(np.median(intervals)))
    span = int((times[-1] - times[0]).astype("timedelta64[s]").astype(np.int64)) + cadence
    return span / 86400.0


def poisson_rate_interval(count: int, days: float, confidence: float = 0.95) -> tuple[float, float]:
    """Exact Poisson interval for a call rate in calls/day."""

    if count < 0 or days <= 0:
        raise ValueError("count must be non-negative and days must be positive")
    alpha = 1.0 - confidence
    lower = 0.0 if count == 0 else 0.5 * chi2.ppf(alpha / 2.0, 2 * count) / days
    upper = 0.5 * chi2.ppf(1.0 - alpha / 2.0, 2 * (count + 1)) / days
    return float(lower), float(upper)


def evaluate_alarm_threshold(
    times: np.ndarray,
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float,
    merge_gap_minutes: int = 30,
) -> dict:
    """Evaluate one frozen threshold without using labels to set it.

    Labels are used only after scoring: to identify the healthy exposure and
    the single observed post-onset period.  The returned detection fields are
    descriptive outcomes, not an estimated population probability of
    detection.
    """

    times = np.asarray(times).astype("datetime64[s]")
    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype=np.float64)
    if not (len(times) == len(labels) == len(scores)):
        raise ValueError("times, labels, and scores must have identical length")
    exceeded = scores > threshold
    healthy = labels == 0
    damaged = labels > 0
    healthy_times = times[healthy]
    all_incidents = incident_starts(times, exceeded, merge_gap_minutes)
    if len(all_incidents):
        incident_indices = np.searchsorted(times, all_incidents)
        healthy_incidents = all_incidents[healthy[incident_indices]]
    else:
        healthy_incidents = all_incidents
    healthy_days = exposure_days(healthy_times)
    calls_per_day = float(len(healthy_incidents) / healthy_days) if healthy_days else float("nan")
    lower, upper = poisson_rate_interval(len(healthy_incidents), healthy_days) if healthy_days else (float("nan"), float("nan"))

    onset_index = int(np.flatnonzero(damaged)[0]) if np.any(damaged) else None
    onset_time = times[onset_index] if onset_index is not None else None
    post_onset_incidents = all_incidents[all_incidents >= onset_time] if onset_index is not None else np.empty(0, dtype="datetime64[s]")
    first_post_onset = post_onset_incidents[0] if len(post_onset_incidents) else None
    pre_onset_active = False
    if onset_index is not None:
        earlier = np.flatnonzero(exceeded[:onset_index])
        if len(earlier):
            last_earlier = times[earlier[-1]]
            pre_onset_active = bool(
                (onset_time - last_earlier).astype("timedelta64[s]").astype(np.int64) <= merge_gap_minutes * 60
            )
    delay_minutes = (
        float((first_post_onset - onset_time).astype("timedelta64[s]").astype(np.int64) / 60.0)
        if first_post_onset is not None and onset_time is not None
        else None
    )
    damage_record_coverage = float(np.mean(exceeded[damaged])) if np.any(damaged) else None
    if np.any(damaged):
        dates = times[damaged].astype("datetime64[D]")
        covered_days = sum(bool(np.any(exceeded[damaged][dates == day])) for day in np.unique(dates))
        damage_day_coverage = float(covered_days / len(np.unique(dates)))
    else:
        damage_day_coverage = None

    return {
        "threshold": float(threshold),
        "healthy_records": int(np.sum(healthy)),
        "healthy_exposure_days": float(healthy_days),
        "healthy_incident_count": int(len(healthy_incidents)),
        "false_calls_per_day": calls_per_day,
        "false_calls_per_day_ci95": [lower, upper],
        "first_post_onset_alarm": None if first_post_onset is None else str(first_post_onset),
        "first_post_onset_delay_minutes": delay_minutes,
        "pre_onset_incident_active_at_onset": pre_onset_active if onset_index is not None else None,
        "post_onset_record_exceedance_coverage": damage_record_coverage,
        "post_onset_day_exceedance_coverage": damage_day_coverage,
    }


def temperature_support_distance(calibration_temperatures: np.ndarray, target_temperatures: np.ndarray) -> np.ndarray:
    """Distance to the nearest calibration temperature, in degrees Celsius."""

    calibration_temperatures = np.asarray(calibration_temperatures, dtype=np.float64)
    target_temperatures = np.asarray(target_temperatures, dtype=np.float64)
    if not len(calibration_temperatures):
        raise ValueError("calibration_temperatures must not be empty")
    calibration_temperatures = np.sort(calibration_temperatures)
    insertion = np.searchsorted(calibration_temperatures, target_temperatures, side="left")
    right_index = np.clip(insertion, 0, len(calibration_temperatures) - 1)
    left_index = np.clip(insertion - 1, 0, len(calibration_temperatures) - 1)
    right_distance = np.abs(target_temperatures - calibration_temperatures[right_index])
    left_distance = np.abs(target_temperatures - calibration_temperatures[left_index])
    return np.minimum(left_distance, right_distance)
