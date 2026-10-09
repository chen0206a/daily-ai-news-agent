from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator

SOURCE_IDS = ("openai", "huggingface", "google_ai", "techcrunch")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(StrictModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class Preferences(StrictModel):
    topics: list[str] = Field(default_factory=lambda: ["AI", "LLM", "Agent"], min_length=1, max_length=8)
    sources: list[Literal["openai", "huggingface", "google_ai", "techcrunch"]] = Field(
        default_factory=lambda: ["openai", "huggingface", "google_ai"], min_length=1, max_length=4)
    language: Literal["zh", "en"] = "zh"
    max_articles: int = Field(default=5, ge=1, le=8)
    lookback_days: int = Field(default=3, ge=1, le=14)
    timezone: str = "Asia/Shanghai"
    delivery_time: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_enabled: bool = False
    in_app_enabled: bool = True
    email_enabled: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone")
        return value

    @field_validator("topics")
    @classmethod
    def valid_topics(cls, values):
        if any(not v.strip() or len(v) > 60 or any(ord(c) < 32 for c in v) for v in values):
            raise ValueError("Topics must contain 1–60 printable characters")
        return list(dict.fromkeys(v.strip() for v in values))


class DigestItem(StrictModel):
    article_id: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=20, max_length=1200)
    evidence_quote: str = Field(min_length=20, max_length=500)


class SaveDigestArgs(StrictModel):
    title: str = Field(min_length=3, max_length=150)
    items: list[DigestItem] = Field(min_length=1, max_length=8)
