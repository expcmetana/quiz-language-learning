from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    card_states: Mapped[list["CardState"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    exercise_states: Mapped[list["ExerciseState"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    kind: Mapped[str] = mapped_column(String(16), default="vocab", server_default="vocab")  # vocab | tenses | gap
    level: Mapped[str | None] = mapped_column(String(8), nullable=True)  # A1 | A2 | B1 | B2 | None
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    words: Mapped[list["Word"]] = relationship(back_populates="deck", cascade="all, delete-orphan")
    exercises: Mapped[list["Exercise"]] = relationship(back_populates="deck", cascade="all, delete-orphan")


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (UniqueConstraint("deck_id", "es", "ru"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    es: Mapped[str] = mapped_column(String(256))
    ru: Mapped[str] = mapped_column(String(256))
    example: Mapped[str | None] = mapped_column(String(512), nullable=True)

    deck: Mapped[Deck] = relationship(back_populates="words")


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # conj | gap
    prompt: Mapped[str] = mapped_column(String(512))  # "hablar · Presente · yo" or a gap sentence with "___"
    answer: Mapped[str] = mapped_column(String(128))
    choices: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 3 wrong options, ";"-separated
    hint: Mapped[str | None] = mapped_column(String(256), nullable=True)  # RU translation / context

    deck: Mapped[Deck] = relationship(back_populates="exercises")


class CardState(Base):
    __tablename__ = "card_states"

    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), primary_key=True)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[Profile] = relationship(back_populates="card_states")
    word: Mapped[Word] = relationship()


class ExerciseState(Base):
    __tablename__ = "exercise_states"

    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[Profile] = relationship(back_populates="exercise_states")
    exercise: Mapped[Exercise] = relationship()


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    # Exactly one of word_id / exercise_id is set per row (enforced in code).
    word_id: Mapped[int | None] = mapped_column(ForeignKey("words.id", ondelete="CASCADE"), nullable=True, index=True)
    exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), nullable=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(16))
    grade: Mapped[int] = mapped_column(Integer)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
