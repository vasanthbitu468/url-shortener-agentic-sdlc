"""Request and response models (these define the OpenAPI contract)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(
        ..., description="Target URL (http or https)", examples=["https://example.com/a/long/path"]
    )
    custom_alias: str | None = Field(
        None, description="Optional custom code, 3-32 chars of [A-Za-z0-9_-]", examples=["my-link"]
    )
    expires_at: datetime | None = Field(
        None, description="Optional expiry (ISO 8601; UTC if no offset)"
    )


class UrlResponse(BaseModel):
    code: str
    short_url: str
    long_url: str
    created_at: datetime
    expires_at: datetime | None
    is_custom: bool


class DailyClicks(BaseModel):
    day: str
    clicks: int


class StatsResponse(BaseModel):
    code: str
    total_clicks: int
    last_accessed_at: datetime | None
    clicks_by_day: list[DailyClicks]


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
