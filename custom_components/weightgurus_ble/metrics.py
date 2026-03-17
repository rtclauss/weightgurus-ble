"""Reusable A6 profile and derived-metric helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping


def _round(value: float) -> float:
    return round(value, 1)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _normalize_sex(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"m", "male"}:
        return "male"
    if normalized in {"f", "female"}:
        return "female"
    raise ValueError(f"Unsupported sex value: {value!r}")


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"Unsupported boolean value: {value!r}")


def _normalize_birthday(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return date.fromisoformat(normalized)
    raise ValueError(f"Unsupported birthday value: {value!r}")


def _normalize_reference_date(value: Any) -> date:
    if value is None:
        return datetime.now().astimezone().date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).astimezone().date()
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return datetime.now().astimezone().date()
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            return date.fromisoformat(normalized)
    raise ValueError(f"Unsupported reference date value: {value!r}")


@dataclass(frozen=True, slots=True)
class A6UserProfile:
    """User attributes required for A6-derived body metrics."""

    height_cm: float | None = None
    birthday: date | None = None
    sex: str | None = None
    athlete: bool | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "A6UserProfile":
        return cls(
            height_cm=float(data["height_cm"]) if data.get("height_cm") is not None else None,
            birthday=_normalize_birthday(data.get("birthday")),
            sex=_normalize_sex(data.get("sex")),
            athlete=_normalize_bool(data["athlete"]) if data.get("athlete") is not None else None,
        )

    def merged(
        self,
        *,
        height_cm: float | None = None,
        birthday: Any = None,
        sex: str | None = None,
        athlete: bool | None = None,
    ) -> "A6UserProfile":
        return A6UserProfile(
            height_cm=self.height_cm if height_cm is None else float(height_cm),
            birthday=self.birthday if birthday is None else _normalize_birthday(birthday),
            sex=self.sex if sex is None else _normalize_sex(sex),
            athlete=self.athlete if athlete is None else bool(athlete),
        )

    def age_on(self, reference: Any = None) -> int | None:
        if self.birthday is None:
            return None

        today = _normalize_reference_date(reference)
        years = today.year - self.birthday.year
        if (today.month, today.day) < (self.birthday.month, self.birthday.day):
            years -= 1
        return years

    def is_complete(self) -> bool:
        age = self.age_on()
        return (
            self.height_cm is not None
            and self.height_cm > 0
            and age is not None
            and age > 0
            and self.sex in {"male", "female"}
            and self.athlete is not None
        )

    def has_any_value(self) -> bool:
        return any(
            value is not None
            for value in (self.height_cm, self.birthday, self.sex, self.athlete)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "height_cm": self.height_cm,
            "birthday": self.birthday.isoformat() if self.birthday is not None else None,
            "sex": self.sex,
            "athlete": self.athlete,
        }


def compute_a6_derived_metrics(
    *,
    weight_kg: float,
    impedance_metric: float | None,
    profile: A6UserProfile,
    measured_at: Any = None,
) -> dict[str, float]:
    """Mirror the vendor SDK's A6 client-side calculations."""

    if weight_kg <= 0 or profile.height_cm is None or profile.height_cm <= 0:
        return {}

    assert profile.height_cm is not None

    height_m = profile.height_cm * 0.01
    if height_m <= 0:
        return {}

    bmi = _round(weight_kg / (height_m**2))
    derived: dict[str, float] = {"bmi": bmi}

    age = profile.age_on(measured_at)
    if (
        impedance_metric is None
        or impedance_metric <= 0
        or age is None
        or age <= 0
        or profile.sex not in {"male", "female"}
        or profile.athlete is None
    ):
        return derived

    derived["age_years"] = float(age)
    is_male = profile.sex == "male"
    athlete = profile.athlete

    if is_male:
        body_fat = ((((impedance_metric * 4.4e-4) + 1.479) * bmi) + (age * 0.1)) - 21.764
    else:
        body_fat = ((((impedance_metric * 3.908e-4) + 1.506) * bmi) + (age * 0.1)) - 12.834
    if athlete:
        body_fat -= (impedance_metric / 500.0) + 4.0
    derived["body_fat_percent"] = _round(_clamp(body_fat, 5.0, 60.0))

    if athlete:
        if is_male:
            muscle = ((bmi * -0.819) - (impedance_metric * 0.00486) - (age * 0.382)) + 77.389
        else:
            muscle = ((bmi * -0.685) - (impedance_metric * 0.00283) - (age * 0.274)) + 59.225
    elif is_male:
        muscle = ((bmi * -0.811) - (impedance_metric * 0.00565) - (age * 0.367)) + 74.627
    else:
        muscle = ((bmi * -0.694) - (impedance_metric * 0.00344) - (age * 0.255)) + 57.0
    derived["muscle_percent"] = _round(_clamp(muscle, 25.0, 75.0))

    if is_male:
        water = ((bmi * -1.162) - (impedance_metric * 0.00813) + (age * 0.07594)) + 87.51
    else:
        water = ((bmi * -1.148) - (impedance_metric * 0.00573) + (age * 0.06448)) + 77.721
    if athlete:
        water += (((impedance_metric + 10.0) * 1.35) / 1500.0) + 3.0
    derived["body_water_percent"] = _round(_clamp(water, 43.0, 73.0))

    return derived
