# Amap Challenge Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Amap challenge triggers and pause safely at the current checkpoint when challenge-like pages or repeated result timeouts occur.

**Architecture:** Strengthen `AmapPageAdapter` pause-state inspection at timeout boundaries, then add an adaptive pacing and suspicious-failure circuit breaker to `AmapWebProvider`. Reuse the collection service's existing `ProviderPaused` checkpoint path so no work unit is falsely completed.

**Tech Stack:** Python 3, pytest, Playwright adapter abstractions, existing collection service and browser lifecycle types.

## Global Constraints

- Never automate or bypass Amap slider challenges.
- Preserve the active work-unit checkpoint on `ProviderPaused`.
- Do not change mobile evidence, deduplication, or ERP delivery rules.
- Run all Python commands through the `doubao-leads` conda environment.

---

### Task 1: Detect challenge state at timeout boundaries

**Files:**
- Modify: `backend/app/providers/amap_web.py`
- Test: `backend/tests/providers/test_amap_web.py`

**Interfaces:**
- Consumes: `detect_pause_state(visible_text: str) -> BrowserState | None`
- Produces: `AmapPageAdapter._ensure_accessible()` raising `ChallengeRequired` when timeout diagnostics show a challenge.

- [ ] **Step 1: Write a failing test**

Add a page fixture that changes to `请完成验证 拖动滑块` on the final result wait and assert `search_keyword()` raises `ChallengeRequired` instead of `TimeoutError`.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_amap_web.py -k challenge_at_result_timeout -q`

Expected: FAIL because the adapter currently raises `TimeoutError`.

- [ ] **Step 3: Implement timeout diagnostics**

Collect visible text plus safe page title and URL text in `_ensure_accessible()`. Re-run this check immediately before timeout returns or raises in result and detail waits.

- [ ] **Step 4: Run provider tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_amap_web.py -q`

Expected: PASS.

### Task 2: Add adaptive pacing and suspicious-failure circuit breaker

**Files:**
- Modify: `backend/app/providers/amap_web.py`
- Test: `backend/tests/providers/test_amap_web.py`

**Interfaces:**
- Produces: provider state fields for consecutive suspicious failures and adaptive delay calculation.
- Produces: `ChallengeRequired` after two consecutive result timeouts.

- [ ] **Step 1: Write failing tests**

Add tests proving two consecutive `TimeoutError` results raise `ChallengeRequired`, successful searches reset the counter, and the next delay grows after one suspicious failure.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_amap_web.py -k "circuit_breaker or adaptive_delay" -q`

Expected: FAIL because provider failures do not currently pause and pacing is fixed.

- [ ] **Step 3: Implement minimal provider state machine**

Classify result timeouts as suspicious, increment a separate counter, apply a bounded delay multiplier, and raise `ChallengeRequired` at threshold 2. Reset the counter after a successful normal result. Change the default batch size to 4 and use a longer batch cooldown.

- [ ] **Step 4: Run provider tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_amap_web.py -q`

Expected: PASS.

### Task 3: Verify checkpoint preservation and regression suite

**Files:**
- Test: `backend/tests/collection/test_service.py`

**Interfaces:**
- Consumes: existing `CollectionService._pause_for_provider()` behavior.

- [ ] **Step 1: Add or tighten checkpoint regression test**

Assert a provider circuit-breaker pause leaves the active work unit as `needs_attention`, keeps its candidate/exact-search index unchanged, and sets the task to `needs_attention`.

- [ ] **Step 2: Run collection tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/collection/test_service.py -q`

Expected: PASS.

- [ ] **Step 3: Run full verification**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests -q`

Run: `conda run -n doubao-leads --no-capture-output python -m ruff check backend`

Expected: all tests pass and Ruff reports no errors.

