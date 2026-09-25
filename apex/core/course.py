"""Core data models for the APEX learning engine.

Defines Course, Chapter, and Lesson as Pydantic-validated models
with full type hints and docstrings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Lesson(BaseModel):
    """A single lesson within a chapter.

    Attributes:
        title: Human-readable lesson title.
        content: The lesson body text or markdown.
        difficulty: Subjective difficulty on a 1-10 scale, where 1 is
            trivial and 10 is expert-level material.
    """

    title: str
    content: str
    difficulty: int = Field(ge=1, le=10, default=5)


class Chapter(BaseModel):
    """A chapter grouping related lessons.

    Attributes:
        title: Chapter heading.
        lessons: Ordered list of lessons belonging to this chapter.
    """

    title: str
    lessons: list[Lesson] = Field(default_factory=list)


class Course(BaseModel):
    """A complete course composed of chapters.

    Attributes:
        id: Unique machine-readable course identifier.
        title: Human-readable course name.
        description: Short blurb describing the course.
        chapters: Ordered list of chapters.
        depth: Granularity of the course material.
        length: Estimated total study time in hours.
        created_at: Timestamp when the course was first created.
        updated_at: Timestamp of the most recent edit.
    """

    id: str
    title: str
    description: str
    chapters: list[Chapter] = Field(default_factory=list)
    depth: Literal["survey", "working", "mastery"] = "survey"
    length: int = Field(ge=0, default=0)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Serialize course to a plain dict (JSON-compatible)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Course:
        """Deserialize from a dict into a Course object."""
        return cls.model_validate(data)
