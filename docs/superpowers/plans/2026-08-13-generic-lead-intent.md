# Generic Lead Intent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a natural-language lead request use its stated customer types as Amap keywords even when the request is outside the residential-decoration domain.

**Architecture:** Keep the existing residential keyword matrix for residential requests. For other requests, extract explicit company-type phrases following the user's search verb, use them as keywords, and leave competitor terms empty unless the user has stated their own business.

**Tech Stack:** Python 3, dataclasses, regular expressions, pytest.

## Global Constraints

- Preserve the existing residential keyword matrix and its filters.
- Never infer a competitor industry when the requester did not state one.
- Keep cross-task company and ERP fingerprint deduplication unchanged.

---

### Task 1: Parse explicit non-residential customer types

**Files:**
- Modify: `backend/app/collection/intent.py`
- Test: `backend/tests/collection/test_intent.py`

**Interfaces:**
- Consumes: `parse_collection_intent(request_text, configured_models, model_keywords)`.
- Produces: `ParsedCollectionIntent.keywords` and `ParsedCollectionIntent.competitor_terms`.

- [x] **Step 1: Write the failing test**

```python
intent = parse_collection_intent(
    '找广州的口腔诊所和牙科诊所，需要手机号，尽量多找。',
    configured_models=set(),
)
assert {'口腔诊所', '牙科诊所'} <= set(intent.keywords)
assert intent.competitor_terms == []
```

- [x] **Step 2: Verify the failure**

Run: `conda run -n huoke --no-capture-output python -m pytest backend/tests/collection/test_intent.py::test_target_only_request_builds_generic_keywords_without_competitor_terms -q`

Expected: failure because the prior fallback keyword was `软装公司`.

- [x] **Step 3: Implement the minimal parser**

Add a search-clause pattern and a suffix-bounded target-type pattern. Use its matches only when the established residential keyword pattern found no keyword.

- [x] **Step 4: Verify the focused test passes**

Run: `conda run -n huoke --no-capture-output python -m pytest backend/tests/collection/test_intent.py::test_target_only_request_builds_generic_keywords_without_competitor_terms -q`

Expected: `1 passed`.

