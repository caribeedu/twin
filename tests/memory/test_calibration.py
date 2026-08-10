"""Source calibration matrix (twin.store.calibration)."""

from twin.store.calibration import calibrated_confidence


def test_calibration_matrix():
    fact = calibrated_confidence("git", "fact", 0.9)
    pref = calibrated_confidence("git", "preference", 0.9)
    assert fact > pref
