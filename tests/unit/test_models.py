import pytest
from pydantic import ValidationError

from agents.models import SkinMetrics, StepAnalysisResult


@pytest.mark.parametrize("field", tuple(SkinMetrics.model_fields))
@pytest.mark.parametrize("invalid", [-1, 101, 1000])
def test_skin_metric_bounds(field, invalid):
    metrics = dict.fromkeys(SkinMetrics.model_fields, 50)
    metrics[field] = invalid
    with pytest.raises(ValidationError):
        SkinMetrics(**metrics)


@pytest.mark.parametrize("boundary", [0, 100])
def test_skin_metric_endpoints_are_valid(boundary):
    assert SkinMetrics(**dict.fromkeys(SkinMetrics.model_fields, boundary))


def test_duplicate_steps_are_rejected_before_graph_construction(routine_state):
    plan = routine_state["step_analysis_data"]
    plan["routine_steps"][1]["step_name"] = "Cleanser"
    with pytest.raises(ValidationError):
        StepAnalysisResult.model_validate(plan)


@pytest.mark.parametrize("count", [0, 1, 9])
def test_routine_size_limits(routine_state, count):
    plan = routine_state["step_analysis_data"]
    plan["routine_steps"] = [
        {**plan["routine_steps"][0], "step_name": f"Step {index}"}
        for index in range(count)
    ]
    plan["routine_summary"]["total_steps"] = count
    with pytest.raises(ValidationError):
        StepAnalysisResult.model_validate(plan)


def test_summary_count_must_match_actual_steps(routine_state):
    plan = routine_state["step_analysis_data"]
    plan["routine_summary"]["total_steps"] = 7
    with pytest.raises(ValidationError):
        StepAnalysisResult.model_validate(plan)
