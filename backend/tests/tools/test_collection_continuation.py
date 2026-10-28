from __future__ import annotations

import importlib.util
from pathlib import Path


def load_continuation_module():
    module_path = Path(__file__).parents[3] / 'tools' / 'collection_continuation.py'
    spec = importlib.util.spec_from_file_location('collection_continuation', module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_next_keywords_expands_after_the_initial_shenzhen_grid_is_exhausted() -> None:
    continuation = load_continuation_module()
    used_keywords = {
        f'{area}{suffix}'
        for area in continuation.SHENZHEN_AREAS
        for suffix in continuation.TARGET_SUFFIXES
    }

    keywords = continuation.next_keywords(used_keywords, limit=10)

    assert len(keywords) == 10
    assert not (set(keywords) & used_keywords)


def test_next_keywords_keeps_expanding_after_two_keyword_grids_are_exhausted() -> None:
    continuation = load_continuation_module()
    used_keywords = {
        f'{area}{suffix}'
        for area in continuation.SHENZHEN_AREAS
        for suffixes in (
            continuation.TARGET_SUFFIXES,
            continuation.EXPANSION_SUFFIXES,
        )
        for suffix in suffixes
    }

    keywords = continuation.next_keywords(used_keywords, limit=10)

    assert len(keywords) == 10
    assert not (set(keywords) & used_keywords)


def test_next_keywords_uses_a_fourth_customer_side_grid_after_all_existing_grids_are_exhausted() -> None:
    continuation = load_continuation_module()
    used_keywords = {
        f'{area}{suffix}'
        for area in continuation.SHENZHEN_AREAS
        for suffixes in (
            continuation.TARGET_SUFFIXES,
            continuation.EXPANSION_SUFFIXES,
            continuation.DEEP_EXPANSION_SUFFIXES,
        )
        for suffix in suffixes
    }

    keywords = continuation.next_keywords(used_keywords, limit=10)

    assert len(keywords) == 10
    assert not (set(keywords) & used_keywords)


def test_next_keywords_generates_qualified_customer_queries_after_all_suffix_grids() -> None:
    continuation = load_continuation_module()
    used_keywords = {
        f'{area}{suffix}'
        for area in continuation.SHENZHEN_AREAS
        for suffixes in (
            continuation.TARGET_SUFFIXES,
            continuation.EXPANSION_SUFFIXES,
            continuation.DEEP_EXPANSION_SUFFIXES,
            continuation.CUSTOMER_SIDE_EXPANSION_SUFFIXES,
        )
        for suffix in suffixes
    }

    keywords = continuation.next_keywords(used_keywords, limit=10)

    assert len(keywords) == 10
    assert not (set(keywords) & used_keywords)
    assert any(qualifier in keywords[0] for qualifier in continuation.QUALIFIED_QUERY_PREFIXES)


def test_source_exhausted_task_is_extended_instead_of_creating_a_new_task(monkeypatch) -> None:
    continuation = load_continuation_module()
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request_json(url: str, *, method: str = 'GET', payload: dict | None = None) -> dict:
        calls.append((url, method, payload))
        return {'id': 'collection-existing', 'status': 'queued'}

    monkeypatch.setattr(continuation, 'request_json', fake_request_json)

    task = continuation.extend_source_exhausted_task(
        'http://api.test',
        task_id='collection-existing',
        used_keywords={'\u6df1\u5733\u5168\u6848\u8f6f\u88c5\u516c\u53f8'},
    )

    assert task['id'] == 'collection-existing'
    assert calls == [
        (
            'http://api.test/collection-tasks/collection-existing/extend',
            'POST',
            {'keywords': calls[0][2]['keywords']},
        ),
    ]
    assert calls[0][2]['keywords']


def test_browser_reopen_is_skipped_while_a_work_unit_is_running() -> None:
    continuation = load_continuation_module()

    task = {
        'status': 'queued',
        'checkpoint': {'browser_state': 'stopped'},
        'work_units': [{'status': 'running'}],
    }

    assert continuation.browser_needs_reopen(task) is False


def test_browser_reopen_is_allowed_after_the_work_units_stop() -> None:
    continuation = load_continuation_module()

    task = {
        'status': 'paused',
        'checkpoint': {'browser_state': 'stopped'},
        'work_units': [{'status': 'succeeded'}],
    }

    assert continuation.browser_needs_reopen(task) is True
