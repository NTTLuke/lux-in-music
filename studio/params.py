"""YuE2 generation parameters.

Mirrors the request options documented in vendor/audio.cpp/docs/models/yue2.md.
Only options the user actually sets are forwarded, so audio.cpp defaults apply
for everything else.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

SEMANTIC_FPS = 25  # semantic codec frames per second of audio


class GenerationParams(BaseModel):
    # --- core ---
    title: str | None = Field(None, max_length=80, description="Song title (UI only, not sent to the model)")
    lyrics: str = Field(..., min_length=1, description="Lyrics with [Verse]/[Chorus]/... section tags")
    style: str = Field(..., min_length=1, description="Style prompt: language, genre, instruments, vocal, mix")
    cot: Literal["off", "melody", "full"] = Field("off", description="Symbolic planning route")
    seed: int = Field(1234, ge=0, lt=2**63)
    num_inference_steps: int | None = Field(None, gt=0, description="NAR ODE steps (default 8)")
    guidance_scale: float | None = Field(None, ge=0, le=20)

    # --- ABC conditioning (cot=melody|full) ---
    abc: str | None = Field(None, description="Inline ABC score")

    # --- semantic sampling (controls the song itself, incl. length) ---
    semantic_temperature: float | None = Field(None, ge=0, le=5)
    semantic_top_p: float | None = Field(None, ge=0, le=1)
    semantic_top_k: int | None = Field(None, ge=1)
    semantic_repetition_penalty: float | None = Field(None, gt=0)
    semantic_min_tokens: int | None = Field(None, ge=0)
    semantic_max_tokens: int | None = Field(None, ge=1)

    # --- ABC planner sampling ---
    abc_temperature: float | None = Field(None, ge=0, le=5)
    abc_top_p: float | None = Field(None, ge=0, le=1)
    abc_top_k: int | None = Field(None, ge=1)

    # --- convenience: max length in seconds -> semantic_max_tokens ---
    max_duration_s: float | None = Field(None, gt=0, le=360)

    @model_validator(mode="after")
    def _check(self):
        if self.abc and self.cot == "off":
            raise ValueError("abc requires cot=melody or cot=full")
        if self.max_duration_s and self.semantic_max_tokens is None:
            self.semantic_max_tokens = int(self.max_duration_s * SEMANTIC_FPS)
        lo, hi = self.semantic_min_tokens, self.semantic_max_tokens
        if hi is not None and lo is None and hi < 200:
            # audio.cpp default min is 200 tokens (8s); keep the pair valid
            self.semantic_min_tokens = hi
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("semantic_max_tokens must be >= semantic_min_tokens")
        return self

    def to_request(self) -> dict:
        """Build the body for audio.cpp POST /v1/tasks/run (`request` field)."""
        skip = {"title", "lyrics", "seed", "max_duration_s"}
        options = {
            k: str(v).lower() if isinstance(v, bool) else str(v)
            for k, v in self.model_dump(exclude_none=True).items()
            if k not in skip
        }
        return {"lyrics": self.lyrics, "seed": self.seed, "options": options}
