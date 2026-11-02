from __future__ import annotations

import pytest
from pydantic import ValidationError

from cvforge.schema import Bullet, Experience, Hat


def test_bullet_weight_defaults_to_3() -> None:
    assert Bullet(id="b1", text="Did a thing.").weight == 3


@pytest.mark.parametrize("weight", [0, 6])
def test_bullet_weight_range(weight: int) -> None:
    with pytest.raises(ValidationError):
        Bullet(id="b1", text="x", weight=weight)


@pytest.mark.parametrize("value", ["2025-13", "2025-6", "June 2025", "25", 1850, "2025-1"])
def test_dates_reject_free_text(value: object) -> None:
    with pytest.raises(ValidationError):
        Experience(id="exp-01", title="t", org="o", start=value, end="present")


def test_present_only_allowed_for_end() -> None:
    with pytest.raises(ValidationError):
        Experience(id="exp-01", title="t", org="o", start="present", end="present")


def test_unknown_keys_are_errors() -> None:
    with pytest.raises(ValidationError):
        Bullet.model_validate({"id": "b1", "text": "x", "wieght": 2})


def test_id_pattern() -> None:
    with pytest.raises(ValidationError):
        Bullet(id="b 1", text="x")


def test_hat_rejects_negative_weight() -> None:
    with pytest.raises(ValidationError):
        Hat(name="dev", skill_weights={"py": -1})


@pytest.mark.parametrize("value", ["2025", 2025])
def test_year_only_dates_are_accepted(value: object) -> None:
    # Some CVs give only a year; the profile keeps exactly that rather than guessing a month.
    assert Experience(id="exp-01", title="t", org="o", start=value, end="present").start == "2025"
