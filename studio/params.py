"""Shared song inputs. Model adapters validate their own options."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GenerationParams(BaseModel):
    model_config = ConfigDict(extra="allow")  # legacy flat options are normalized by adapters
    title: str | None = Field(None, max_length=80)
    lyrics: str = ""
    instrumental: bool = False
    style: str = Field(..., min_length=1)
    seed: int = Field(1234, ge=0, lt=2**63)
    model_options: dict[str, Any] = Field(default_factory=dict)
