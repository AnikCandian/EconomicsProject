"""Pydantic request bodies for the game API.

Only the client -> server direction needs strict schema validation; response
shapes are documented in API_PROTOCOL.md and built directly as dicts in
server.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StartSessionRequest(BaseModel):
    """Optional per-session season configuration -- any field left out (or
    the whole body left out) falls back to dataset.default_season_config().
    Immutable once the session is created; there's no endpoint to change
    these after POST /sessions. See API_PROTOCOL.md, "Season configuration."
    """

    train_seasons: list[int] | None = Field(
        None, description="Seasons to train every model on. Defaults to seasons 1-10."
    )
    basic_test_seasons: list[int] | None = Field(
        None,
        description="Seasons scored live while students play. Defaults to the same seasons as train_seasons.",
    )
    final_test_seasons: list[int] | None = Field(
        None, description="Seasons held out until the session ends. Defaults to every remaining season."
    )


class JoinRequest(BaseModel):
    full_name: str = Field(..., min_length=1, description="The student's full name")


class VariablesRequest(BaseModel):
    variables: list[str] = Field(
        ..., min_length=1, description="Column headers from USABLE_COLUMNS to model with"
    )


class ExploreRequest(VariablesRequest):
    pass


class FinalizeRequest(VariablesRequest):
    pass
