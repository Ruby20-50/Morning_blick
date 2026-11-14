"""Pydantic models for the calculator endpoints."""

from typing import Literal

from pydantic import BaseModel

Operation = Literal["add", "subtract", "multiply", "divide"]


class CalculationRequest(BaseModel):
    a: float
    b: float


class CalculationResponse(BaseModel):
    operation: Operation
    a: float
    b: float
    result: float | None
