"""Deterministic synthetic system evaluation for Phases 1 through 4."""

from .runner import EvaluationOptions, run_evaluation
from .scenarios import SCENARIOS, ScenarioName

__all__ = ["EvaluationOptions", "SCENARIOS", "ScenarioName", "run_evaluation"]
