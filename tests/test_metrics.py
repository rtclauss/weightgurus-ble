from __future__ import annotations

import unittest

from custom_components.weightgurus_ble.metrics import (
    A6UserProfile,
    compute_a6_derived_metrics,
)


class MetricsTests(unittest.TestCase):
    def test_age_rolls_over_on_birthday(self) -> None:
        profile = A6UserProfile.from_mapping(
            {
                "height_cm": 180,
                "birthday": "1990-03-03",
                "sex": "male",
                "athlete": False,
            }
        )

        self.assertEqual(profile.age_on("2026-03-02"), 35)
        self.assertEqual(profile.age_on("2026-03-03"), 36)
        self.assertEqual(profile.age_on("2026-03-04"), 36)

    def test_bmi_is_available_with_partial_profile(self) -> None:
        profile = A6UserProfile(height_cm=180)

        derived = compute_a6_derived_metrics(
            weight_kg=85.5,
            impedance_metric=None,
            profile=profile,
            measured_at="2026-03-03T09:32:09-06:00",
        )

        self.assertEqual(derived, {"bmi": 26.4})

    def test_age_years_uses_measurement_date(self) -> None:
        profile = A6UserProfile.from_mapping(
            {
                "height_cm": 180,
                "birthday": "1990-03-03",
                "sex": "male",
                "athlete": False,
            }
        )

        before_birthday = compute_a6_derived_metrics(
            weight_kg=85.5,
            impedance_metric=36.6,
            profile=profile,
            measured_at="2026-03-02T09:32:09-06:00",
        )
        on_birthday = compute_a6_derived_metrics(
            weight_kg=85.5,
            impedance_metric=36.6,
            profile=profile,
            measured_at="2026-03-03T09:32:09-06:00",
        )

        self.assertEqual(before_birthday["age_years"], 35.0)
        self.assertEqual(on_birthday["age_years"], 36.0)


if __name__ == "__main__":
    unittest.main()
