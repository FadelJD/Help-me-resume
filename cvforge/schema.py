"""Pydantic models for the profile, hats and the selected/rendered CV. No I/O here."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]*$"
YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

Id = Annotated[str, Field(pattern=ID_PATTERN)]


class Strict(BaseModel):
    """Unknown keys are an error: a typo must not silently drop data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_date(value: object, allow_present: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"date must be YYYY-MM{' or present' if allow_present else ''}")
    if allow_present and value == "present":
        return value
    if not YEAR_MONTH.match(value):
        raise ValueError(f"date must be YYYY-MM{' or present' if allow_present else ''}")
    return value


class Person(Strict):
    name: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = []


class Bullet(Strict):
    id: Id
    text: str = Field(min_length=1)
    skills: list[str] = []
    weight: int = Field(default=3, ge=1, le=5)


class Experience(Strict):
    id: Id
    title: str = Field(min_length=1)
    org: str = Field(min_length=1)
    location: str | None = None
    start: str
    end: str
    tags: list[str] = []
    bullets: list[Bullet] = []

    @field_validator("start", mode="before")
    @classmethod
    def _start(cls, v: object) -> str:
        return _check_date(v, allow_present=False)

    @field_validator("end", mode="before")
    @classmethod
    def _end(cls, v: object) -> str:
        return _check_date(v, allow_present=True)


class Project(Strict):
    id: Id
    name: str = Field(min_length=1)
    url: str | None = None
    start: str | None = None
    end: str | None = None
    tags: list[str] = []
    bullets: list[Bullet] = []

    @field_validator("start", mode="before")
    @classmethod
    def _start(cls, v: object) -> str | None:
        return None if v is None else _check_date(v, allow_present=False)

    @field_validator("end", mode="before")
    @classmethod
    def _end(cls, v: object) -> str | None:
        return None if v is None else _check_date(v, allow_present=True)


class Education(Strict):
    id: Id
    degree: str = Field(min_length=1)
    org: str = Field(min_length=1)
    start: str | None = None
    end: str
    bullets: list[Bullet] = []

    @field_validator("start", mode="before")
    @classmethod
    def _start(cls, v: object) -> str | None:
        return None if v is None else _check_date(v, allow_present=False)

    @field_validator("end", mode="before")
    @classmethod
    def _end(cls, v: object) -> str:
        return _check_date(v, allow_present=True)


class Profile(Strict):
    person: Person
    skills: dict[Id, str] = {}
    experience: list[Experience] = []
    projects: list[Project] = []
    education: list[Education] = []

    def sections_with_items(self) -> list[str]:
        out = []
        for name in ("experience", "projects", "skills", "education"):
            if getattr(self, name):
                out.append(name)
        return out

    def all_items(self) -> list[Experience | Project | Education]:
        items: list[Experience | Project | Education] = []
        items.extend(self.experience)
        items.extend(self.projects)
        items.extend(self.education)
        return items

    def find_item(self, item_id: str) -> Experience | Project | Education | None:
        for item in self.all_items():
            if item.id == item_id:
                return item
        return None


SectionName = Literal["experience", "projects", "skills", "education"]


class Hat(Strict):
    """Weights skills and section order for a role family. Holds no facts about the person."""

    name: str = Field(min_length=1)
    title_line: str = ""
    sections: list[SectionName] = ["experience", "projects", "skills", "education"]
    skill_weights: dict[str, float] = {}
    skill_groups: dict[str, list[str]] = {}

    @field_validator("skill_weights")
    @classmethod
    def _positive(cls, v: dict[str, float]) -> dict[str, float]:
        for key, weight in v.items():
            if weight < 0:
                raise ValueError(f"skill weight for {key!r} must be >= 0")
        return v
