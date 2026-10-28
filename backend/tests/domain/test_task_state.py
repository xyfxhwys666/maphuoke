import pytest
from backend.app.domain.task_state import transition_task_status


def test_documented_task_transition_is_allowed() -> None:
    assert transition_task_status('created', 'discovering_map') == 'discovering_map'
    assert transition_task_status('discovering_map', 'candidates_ready') == 'candidates_ready'


def test_invalid_task_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match='invalid task transition'):
        transition_task_status('created', 'delivering')
