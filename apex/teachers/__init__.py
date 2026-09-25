"""APEX Teacher Personas — AI-guided instruction."""

from .teacher_config import TEACHER_PROFILES, TeacherProfile, get_teacher, list_teachers
from .teacher_engine import (
    LessonContent,
    diagnose_errors,
    generate_socratic_questions,
    get_tts_voice,
    instruct,
)

__all__ = [
    "TEACHER_PROFILES",
    "LessonContent",
    "TeacherProfile",
    "diagnose_errors",
    "generate_socratic_questions",
    "get_teacher",
    "get_tts_voice",
    "instruct",
    "list_teachers",
]
