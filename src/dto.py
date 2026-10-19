from typing import Literal
from pydantic import BaseModel, ConfigDict

class ParsedIncident(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    services: list[str]
    http_codes: list[str]
    timestamps: list[str]
    language: str | None

class Hypothesis(BaseModel):
    title: str
    reasoning: str
    next_steps: list[str]

class Response(BaseModel):
    category: str
    summary: str
    severity: Literal['low', 'medium', 'high']
    hypotheses: list[Hypothesis]
