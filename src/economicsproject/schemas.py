"""Pydantic request bodies for the game API.

Only the client -> server direction needs strict schema validation; response
shapes are documented in API_PROTOCOL.md and built directly as dicts in
server.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
