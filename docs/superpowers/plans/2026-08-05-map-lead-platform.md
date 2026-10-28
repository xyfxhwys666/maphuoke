# Map Lead Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify the complete map-discovery, Doubao-enrichment, evidence-verification, idempotent ERP-delivery, API, UI, and batch workflow defined by the project design.

**Architecture:** A FastAPI backend owns task orchestration and persistence. Domain modules expose provider-independent contracts for candidates, leads, evidence, checkpoints, and delivery. A React/Vite workbench consumes the versioned API. Amap web and API providers, Doubao web enrichment, evidence verification, and ERP delivery are adapters behind those contracts.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic Settings, httpx, Playwright, pytest, Ruff, React, TypeScript, Vite, lucide-react, SQLite by default.

## Global Constraints

- Keep `MapDiscoveryProvider` independent from page DOM and use the same contract for Amap web and Amap API.
- Keep a map candidate when it has a company name and address even when all contact fields are empty.
- Preserve map address, telephone, source URL, category, coordinates, POI ID, raw text, and source metadata when enrichment returns empty values.
- Store `telephone` separately from `mobile`; only a normalized mainland China 11-digit mobile number may enter `mobile`.
- Treat `captured`, `source_backed`, and `verified` as distinct evidence states; unverified model output is display-only by default.
- Do not bypass login, CAPTCHA, or security verification; pause and expose a resumable task state.
- Use dedicated browser profiles and a single actor/command queue for each browser session.
- Make ERP delivery idempotent with stable UUID5 account IDs, stable payload SHA-256 fingerprints, and a delivery ledger.
- Keep automatic delivery disabled by default and do not log secrets, cookies, tokens, or raw authorization headers.
- Write new Markdown as UTF-8 and run the backend tests plus frontend typecheck/build before completion claims.

## File Map

### Backend foundation

- Create: `backend/pyproject.toml` for runtime and development dependencies.
- Create: `backend/app/config.py` for typed environment configuration.
- Create: `backend/app/db.py` for SQLAlchemy engine and session creation.
- Create: `backend/app/main.py` for FastAPI application construction.
- Create: `backend/app/domain/models.py` for immutable domain contracts and status enums.
- Create: `backend/app/domain/normalization.py` for field normalization.
- Create: `backend/app/domain/merge.py` for candidate-to-lead merging.
- Create: `backend/app/domain/evidence.py` for evidence grades and ERP gates.
- Create: `backend/app/domain/dedup.py` for normalized identity and payload fingerprints.
- Create: `backend/app/domain/delivery.py` for ERP adapter and result contracts.
- Create: `backend/app/domain/task_state.py` for allowed transitions and checkpoint data.
- Create: `backend/app/providers/protocols.py` for map, Doubao, verifier, and ERP protocols.
- Create: `backend/app/providers/fake.py` for deterministic test providers.
- Create: `backend/app/services/search_task.py` for the Phase 0 orchestration service.
- Create: `backend/app/storage/models.py` for task, candidate, lead, checkpoint, and delivery tables.
- Create: `backend/app/storage/repositories.py` for persistence operations used by services and routes.
- Create: `backend/app/api/routes.py` for Phase 0 API endpoints.

### Tests

- Create: `backend/tests/conftest.py` for isolated SQLite and fake-provider fixtures.
- Create: `backend/tests/domain/test_normalization.py`.
- Create: `backend/tests/domain/test_merge.py`.
- Create: `backend/tests/domain/test_evidence.py`.
- Create: `backend/tests/domain/test_dedup.py`.
- Create: `backend/tests/domain/test_task_state.py`.
- Create: `backend/tests/services/test_search_task.py`.
- Create: `backend/tests/api/test_routes.py`.
- Create: provider, browser, API, ERP, and batch test files as each phase introduces the adapter.

### Frontend

- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, and `frontend/index.html`.
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/labels.ts`, and `frontend/src/styles.css`.
- Create: `frontend/src/labels.test.ts` and add component-level tests only for behavior that cannot be covered through the API contract.

---

### Task 1: Bootstrap Phase 0 project and test harness

**Files:**
- Create the backend and frontend foundation files listed above only as empty package/config scaffolding.
- Test: `backend/tests/test_health.py` and `frontend/src/labels.test.ts`.

**Interfaces:**
- Produces a runnable FastAPI app with `GET /health` and a frontend that typechecks.

- [ ] **Step 1: Add the failing health test**

```python
def test_health_returns_ok(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
```

- [ ] **Step 2: Run the test and confirm the expected failure**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/test_health.py -q`.
Expected: collection fails because the new `app` package and FastAPI application do not yet exist.

- [ ] **Step 3: Add the minimum project configuration and health route**

Create the package files, `backend/pyproject.toml` with the documented dependencies, and `app.main:create_app()` with the health route. Use `DATABASE_URL=sqlite:///./mapsearch.db` as the local default and read all external service settings from `Settings`.

- [ ] **Step 4: Run backend and frontend smoke checks**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/test_health.py -q` and `npm.cmd --prefix frontend run typecheck`.
Expected: the health test passes and the TypeScript command exits 0.

- [ ] **Step 5: Commit the bootstrap**

Run: `git add backend frontend && git commit -m "chore: bootstrap mapsearch project"`.

### Task 2: Define and test normalization contracts

**Files:**
- Test: `backend/tests/domain/test_normalization.py`.
- Create: `backend/app/domain/normalization.py`.

**Interfaces:**
- Produces `normalize_company_name(value) -> str`, `normalize_city(value) -> str`, `normalize_mobile(value) -> str | None`, `normalize_telephone(value) -> str | None`, `normalize_email(value) -> str | None`, and `normalize_wechat(value) -> str | None`.

- [ ] **Step 1: Write failing tests for the required classifications**

```python
def test_phone_normalization_separates_mobile_landline_and_400():
    assert normalize_mobile('+86 138-0013-8000') == '13800138000'
    assert normalize_mobile('0755-12345678') is None
    assert normalize_mobile('400-800-1234') is None
    assert normalize_telephone('0755-12345678') == '075512345678'

def test_company_identity_removes_spacing_and_punctuation():
    assert normalize_company_name(' 深圳示例科技有限公司 ') == '深圳示例科技有限公司'
```

- [ ] **Step 2: Run only this test file and verify it fails for missing functions**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/domain/test_normalization.py -q`.
Expected: import failure for `app.domain.normalization`.

- [ ] **Step 3: Implement the smallest pure normalization functions**

Strip Unicode whitespace, remove phone separators, accept `+86` only for mobile normalization, require the `1[3-9]` mainland prefix and 11 digits, preserve telephone as a separate normalized value, and return `None` for empty or invalid email/WeChat values.

- [ ] **Step 4: Run the focused test and then all backend tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/domain/test_normalization.py -q` and `conda run -n doubao-leads --no-capture-output python -m pytest -q`.
Expected: focused tests pass; the full suite contains only the existing health test and passes.

- [ ] **Step 5: Commit the normalization contract**

Run: `git add backend/app/domain/normalization.py backend/tests/domain/test_normalization.py && git commit -m "feat: add lead field normalization"`.

### Task 3: Define domain models, merge behavior, identity, and evidence gates

**Files:**
- Test: `backend/tests/domain/test_merge.py`, `backend/tests/domain/test_dedup.py`, `backend/tests/domain/test_evidence.py`.
- Create: `backend/app/domain/models.py`, `merge.py`, `dedup.py`, and `evidence.py`.

**Interfaces:**
- Produces `MapPoiCandidate`, `LeadRecord`, `EvidenceValue`, `EvidenceResult`, `DeliveryDecision`, `merge_candidate_with_enrichment(candidate, enrichment)`, `company_identity(city, company_name)`, `contact_identity(lead)`, `payload_fingerprint(payload)`, and `evaluate_delivery_gate(task, lead)`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_empty_enrichment_preserves_map_fields():
    lead = merge_candidate_with_enrichment(
        candidate_with_address_and_telephone(),
        DoubaoEnrichment(company_name=None, address=None, telephone=None),
    )
    assert lead.address == '广东省深圳市南山区示例路 1 号'
    assert lead.telephone == '075512345678'
    assert lead.source_urls == ['https://uri.amap.com/marker?id=poi-1']

def test_unverified_model_mobile_is_display_only():
    decision = evaluate_delivery_gate(task_with_defaults(), lead_with_captured_mobile())
    assert decision.status == 'display_only'
    assert 'contact_unverified' in decision.reasons

def test_payload_fingerprint_ignores_capture_time():
    assert payload_fingerprint({'company': 'A', 'captured_at': 'one'}) == payload_fingerprint({'company': 'A', 'captured_at': 'two'})
```

- [ ] **Step 2: Run the focused tests and confirm the domain imports are missing**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/domain/test_merge.py backend/tests/domain/test_dedup.py backend/tests/domain/test_evidence.py -q`.
Expected: collection fails because domain models and functions are absent.

- [ ] **Step 3: Implement typed contracts and merge rules**

Use Pydantic models or frozen dataclasses with explicit nullable fields. Make map company name and address authoritative, retain all map source metadata, accept non-empty enrichment fields only when they do not erase existing map values, attach field-level evidence, and calculate the gate from company verification, contact verification, required contact presence, source URLs, and the `allow_map_only_verification` flag.

- [ ] **Step 4: Run focused and full backend tests**

Run the three focused test files followed by `conda run -n doubao-leads --no-capture-output python -m pytest -q`.
Expected: all tests pass with no warnings caused by the new code.

- [ ] **Step 5: Commit the domain layer**

Run: `git add backend/app/domain backend/tests/domain && git commit -m "feat: add map lead domain contracts"`.

### Task 4: Add task states and deterministic fake providers

**Files:**
- Test: `backend/tests/domain/test_task_state.py` and `backend/tests/services/test_search_task.py`.
- Create: `backend/app/domain/task_state.py`, `backend/app/providers/protocols.py`, `backend/app/providers/fake.py`, and `backend/app/services/search_task.py`.

**Interfaces:**
- Produces `TaskStatus`, `CompanyProgress`, `TaskCheckpoint`, `FakeMapDiscoveryProvider`, `FakeDoubaoGateway`, `FakeEvidenceVerifier`, `FakeErpAdapter`, and `CompanySearchService` methods `create_task`, `discover`, `enrich`, `verify`, and `deliver`.

- [ ] **Step 1: Write failing fake end-to-end tests**

```python
def test_fake_pipeline_keeps_candidate_without_map_contact():
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    assert service.get_task(task.id).candidates[0].address
    assert service.get_task(task.id).candidates[0].telephone is None

def test_pipeline_records_checkpoint_and_does_not_auto_deliver_unverified_lead():
    task = service.create_task(company_name='深圳示例科技有限公司', city='深圳市')
    service.discover(task.id)
    service.enrich(task.id, candidate_id=task.candidates[0].id)
    service.verify(task.id)
    result = service.deliver(task.id, candidate_id=task.candidates[0].id)
    assert result.status == 'display_only'
    assert service.get_task(task.id).checkpoint.current_stage == 'verifying'
```

- [ ] **Step 2: Run the tests and confirm missing task/provider contracts**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/domain/test_task_state.py backend/tests/services/test_search_task.py -q`.
Expected: collection or import failure for the missing contracts.

- [ ] **Step 3: Implement transition validation and fake providers**

Permit only the documented state transitions, keep company progress isolated, and make fakes deterministic. The fake map provider returns a candidate with a company name and address but no contacts; the fake Doubao gateway returns configurable enrichment; the fake verifier returns configurable evidence; the fake ERP records payloads and fingerprints.

- [ ] **Step 4: Implement service orchestration and checkpoint updates**

Create the task, run discovery, persist candidates, enrich only explicitly selected candidates, verify leads, evaluate delivery gates, and update the checkpoint after each stage. A provider exception updates the affected company error and task `completed_with_errors` or a pause state without discarding successful companies.

- [ ] **Step 5: Run the fake pipeline and full backend tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/domain backend/tests/services -q` and then `conda run -n doubao-leads --no-capture-output python -m pytest -q`.
Expected: the complete Fake Map -> Fake Doubao -> Fake verifier -> Fake ERP chain passes.

- [ ] **Step 6: Commit Phase 0 service contracts**

Run: `git add backend/app/providers backend/app/services backend/app/domain/task_state.py backend/tests/domain/test_task_state.py backend/tests/services/test_search_task.py && git commit -m "feat: add fake map lead pipeline"`.

### Task 5: Persist Phase 0 tasks and expose API routes

**Files:**
- Test: `backend/tests/api/test_routes.py`.
- Create/modify: `backend/app/storage/models.py`, `backend/app/storage/repositories.py`, `backend/app/api/routes.py`, `backend/app/main.py`, and `backend/tests/conftest.py`.

**Interfaces:**
- Produces `GET /api/v1/providers`, `GET /api/v1/browser-status`, `POST /api/v1/company-search-tasks`, `POST /api/v1/company-search-tasks/{task_id}/start`, `GET /api/v1/company-search-tasks/{task_id}`, `POST .../pause`, `POST .../resume`, `POST .../enrich`, `POST .../verify`, `POST .../deliver`, `POST .../retry-errors`, `POST /api/v1/leads/{lead_id}/deliver`, and `GET /api/v1/erp-config`.

- [ ] **Step 1: Write failing route tests**

Test task creation validation, provider listing, candidate visibility, selection-required behavior, pause/resume state, and display-only delivery responses. Assert JSON includes map fields, enrichment fields, evidence state, and delivery reason separately.

- [ ] **Step 2: Run the API test file and confirm routes/storage are absent**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/api/test_routes.py -q`.
Expected: route import or 404 failures.

- [ ] **Step 3: Add SQLAlchemy tables and repositories**

Persist tasks, candidates, leads, checkpoints, evidence snapshots, and delivery ledger entries. Serialize structured metadata as JSON, use UTC timestamps, and never store authorization headers. Rehydrate domain models through repository methods.

- [ ] **Step 4: Add routes and dependency wiring**

Validate city and company name, expose only configured providers, select a candidate explicitly before enrichment/delivery, return stable error codes, and map pause/error states to HTTP responses without leaking secrets.

- [ ] **Step 5: Run API, backend, and frontend smoke checks**

Run backend full tests and `npm.cmd --prefix frontend run typecheck`. Expected: all current backend tests pass and frontend types compile.

- [ ] **Step 6: Commit Phase 0**

Run: `git add backend && git commit -m "feat: expose persistent phase zero API"`.

### Task 6: Build the Phase 0 frontend workbench

**Files:**
- Test: `frontend/src/labels.test.ts`.
- Create/modify: all files under `frontend/src` listed in the file map.

**Interfaces:**
- Consumes the Phase 0 API response contract and produces a single-company search, candidate selection, enrichment, verification, and delivery workbench.

- [ ] **Step 1: Write failing label and state tests**

Cover status labels for `display_only`, `ready`, `waiting_for_login`, `waiting_for_challenge`, and `completed_with_errors`, and ensure a non-selected candidate cannot enable enrichment.

- [ ] **Step 2: Run the frontend focused test**

Run: `cd frontend && npm.cmd test -- --run`.
Expected: the configured test command is absent or the new label behavior is missing; add the smallest supported Vitest setup if needed.

- [ ] **Step 3: Implement typed API client and workbench UI**

Build the input bar, candidate list, selected POI detail/source section, enrichment progress, field evidence table, and delivery action states. Include accessible labels, loading/error/empty states, and stable layout dimensions. Use the existing icon dependency for action buttons.

- [ ] **Step 4: Verify frontend typecheck and production build**

Run: `cd frontend && npm.cmd run typecheck && npm.cmd run build`.
Expected: both commands exit 0.

- [ ] **Step 5: Commit the Phase 0 UI**

Run: `git add frontend && git commit -m "feat: add map lead workbench"`.

### Task 7: Implement dedicated CDP browser lifecycle and Amap web MVP

**Files:**
- Test: `backend/tests/providers/test_amap_web.py` and `backend/tests/providers/test_browser_lifecycle.py`.
- Create: `backend/app/browser/actor.py`, `backend/app/browser/lifecycle.py`, `backend/app/providers/amap_selectors.py`, `backend/app/providers/amap_web.py`.

**Interfaces:**
- Produces `BrowserState`, `DedicatedBrowser`, `AmapPageAdapter`, `AmapWebProvider`, and selector functions that return `MapPoiCandidate` data without exposing Playwright objects to the service layer.

- [ ] **Step 1: Write parser and lifecycle tests first**

Use saved visible-text fixtures and fake page objects to test result-card parsing, detail extraction, fallback selectors, port collision, login detection, challenge detection, timeout conversion, and one reconnect attempt.

- [ ] **Step 2: Run provider tests and confirm missing adapter failures**

Run: `conda run -n mapsearch --no-capture-output python -m pytest backend/tests/providers/test_amap_web.py backend/tests/providers/test_browser_lifecycle.py -q`.
Expected: import failures for the new adapter modules.

- [ ] **Step 3: Implement the actor and dedicated lifecycle**

Use an isolated user-data-dir, fixed local CDP port from settings, a FIFO command queue, per-search timeout, and explicit `STOPPED`, `STARTING`, `READY`, `SEARCHING`, `DETAIL_LOADING`, `EXTRACTING`, `WAITING_FOR_LOGIN`, `WAITING_FOR_CHALLENGE`, `FAILED`, and `RECONNECTING` states. Detect a port already owned by another process before launching.

- [ ] **Step 4: Implement centralized selectors and visible-text extraction**

Locate the search field and result cards by semantic role/text first, retain fallback selectors in `amap_selectors.py`, open details only for selected candidates, and capture URL, POI ID, coordinates, visible text, category, address, telephone, and timestamp.

- [ ] **Step 5: Implement failure isolation and pause transitions**

Map empty results to `empty_result`, page timeouts to a retriable company failure, login to `waiting_for_login`, challenge to `waiting_for_challenge`, and DOM errors to one reconnect followed by a retriable failure. Pause after the configured consecutive-failure threshold.

- [ ] **Step 6: Run provider, service, API, and full backend tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers backend/tests/services backend/tests/api -q` and then the full suite.

- [ ] **Step 7: Commit the web MVP**

Run: `git add backend/app/browser backend/app/providers/amap_selectors.py backend/app/providers/amap_web.py backend/tests/providers && git commit -m "feat: add amap web discovery provider"`.

### Task 8: Implement Doubao web enrichment behind the shared gateway

**Files:**
- Test: `backend/tests/providers/test_doubao_web.py` and `backend/tests/services/test_enrichment.py`.
- Create: `backend/app/providers/doubao_prompt.py`, `backend/app/providers/doubao_parser.py`, `backend/app/providers/doubao_web.py`, and `backend/app/services/enrichment.py`.

**Interfaces:**
- Produces `DoubaoEnrichmentGateway.enrich_company(company_name, city, requested_contacts, known_fields)` and parser functions for fixed JSON plus safe natural-language fallback.

- [ ] **Step 1: Write failing parser and preservation tests**

Cover valid JSON, fenced JSON, malformed JSON, missing source URL, forbidden guessed contacts, known map address/telephone context, and merge preservation when enrichment fails.

- [ ] **Step 2: Run focused tests and confirm missing gateway/parser failures**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_doubao_web.py backend/tests/services/test_enrichment.py -q`.

- [ ] **Step 3: Implement the prompt and parser contracts**

Require fixed JSON fields, actual public occurrence, source URLs and evidence quotes, and null for unsubstantiated contacts. Parse a natural-language fallback only into captured fields; mark it unverified when source evidence is absent.

- [ ] **Step 4: Implement the browser gateway and checkpoint integration**

Reuse the actor/lifecycle abstraction, enforce request pacing, detect login/challenge, reconnect once, isolate one-company failures, and save enrichment checkpoints. Pass map address, telephone, source URL, category, and POI ID as known context.

- [ ] **Step 5: Run enrichment, regression, and full backend tests**

Run the focused files, then `conda run -n doubao-leads --no-capture-output python -m pytest -q`.

- [ ] **Step 6: Commit Phase 2**

Run: `git add backend/app/providers/doubao* backend/app/services/enrichment.py backend/tests/providers/test_doubao_web.py backend/tests/services/test_enrichment.py && git commit -m "feat: add doubao web enrichment"`.

### Task 9: Add map evidence verification, public evidence, and ERP delivery

**Files:**
- Test: `backend/tests/providers/test_map_evidence.py`, `backend/tests/providers/test_erp.py`, `backend/tests/services/test_delivery.py`.
- Create: `backend/app/providers/map_evidence.py`, `backend/app/providers/public_web.py`, `backend/app/providers/erp.py`, `backend/app/services/verification.py`, and `backend/app/services/delivery.py`.

**Interfaces:**
- Produces `MapEvidenceVerifier.verify(candidate, expected_company_name, expected_contact)`, `PublicEvidenceVerifier`, configurable `ErpAdapter`, `DeliveryLedger`, and service methods for manual delivery, automatic-gate evaluation, and retry.

- [ ] **Step 1: Write failing evidence and delivery tests**

Cover map snapshots, company-name mismatch, model-only mobile display-only gate, verified public-web delivery, stable UUID5, telephone-to-other-contact mapping, duplicate fingerprint, nonzero ERP `errCode`, timeout, and retry.

- [ ] **Step 2: Run focused tests and confirm missing verifier/delivery modules**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_map_evidence.py backend/tests/providers/test_erp.py backend/tests/services/test_delivery.py -q`.

- [ ] **Step 3: Implement evidence mapping and grades**

Persist source type, URL, POI ID, captured time, raw visible text or structured response summary, and field-level evidence. The map verifier may return `verified_map` only when company identity and map evidence match; it must not infer that a marker URL proves a mobile number.

- [ ] **Step 4: Implement ERP payload, fingerprint, and idempotent ledger**

Build the default payload through an adapter, derive stable account identity from city and normalized company, place telephone in the configured non-mobile contact field, store operation IDs and failure details, and prevent a second delivery for the same stable fingerprint.

- [ ] **Step 5: Implement gate-aware manual, automatic, and retry delivery**

Manual delivery must still return a clear reason for blocked fields; automatic delivery requires all configured gates and is disabled unless explicitly enabled. Retry only failed operations and preserve successful delivery records.

- [ ] **Step 6: Run full backend and frontend verification**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest -q` and `npm.cmd --prefix frontend run typecheck && npm.cmd --prefix frontend run build`.

- [ ] **Step 7: Commit Phase 3**

Run: `git add backend/app/providers backend/app/services backend/tests/providers backend/tests/services && git commit -m "feat: add evidence gates and idempotent erp delivery"`.

### Task 10: Add Amap API provider and provider substitution tests

**Files:**
- Test: `backend/tests/providers/test_amap_api.py` and `backend/tests/services/test_provider_substitution.py`.
- Create: `backend/app/providers/amap_api.py` and `backend/app/providers/http.py`.
- Modify: configuration, provider registry, and service dependency wiring.

**Interfaces:**
- Produces `AmapApiProvider` implementing the exact `MapDiscoveryProvider` contract and configurable provider selection `amap_web`, `amap_api`, or automatic fallback.

- [ ] **Step 1: Write failing API mapping and substitution tests**

Use a fake HTTP transport to cover multi-page response mapping, company/address-only POIs, city restriction, request interval, retry on network/limit errors, marker URL, and identical downstream behavior for web and API candidates.

- [ ] **Step 2: Run the focused tests and verify the missing provider**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_amap_api.py backend/tests/services/test_provider_substitution.py -q`.

- [ ] **Step 3: Implement typed API transport and response mapping**

Read `AMAP_API_KEY`, `AMAP_BASE_URL`, `AMAP_MAX_PAGES`, `AMAP_REQUEST_INTERVAL_SECONDS`, and `AMAP_RETRY_LIMIT`. Parse all valid company/address results even when telephone is absent, apply bounded backoff, and convert coordinates and marker URLs into the shared candidate model.

- [ ] **Step 4: Register provider selection without changing downstream services**

Expose both providers in `/api/v1/providers`, use the configured provider for discovery, and keep enrichment, verification, deduplication, checkpoint, and ERP calls provider-agnostic.

- [ ] **Step 5: Run API, substitution, full backend, and frontend verification**

Run the focused tests, `conda run -n doubao-leads --no-capture-output python -m pytest -q`, and the frontend typecheck/build commands.

- [ ] **Step 6: Commit Phase 4 provider support**

Run: `git add backend/app/providers/amap_api.py backend/app/providers/http.py backend/app/config.py backend/app/api/routes.py backend/tests/providers/test_amap_api.py backend/tests/services/test_provider_substitution.py && git commit -m "feat: add amap api provider"`.

### Task 11: Add CSV/Excel batch input and rate-limited queue

**Files:**
- Test: `backend/tests/batch/test_import.py` and `backend/tests/services/test_batch_queue.py`.
- Create: `backend/app/batch/importers.py`, `backend/app/batch/queue.py`, and `backend/app/api/batch_routes.py`.
- Modify: `backend/app/main.py`, task models, frontend API/types, and workbench UI.

**Interfaces:**
- Produces `CompanyInputImporter.from_csv`, `CompanyInputImporter.from_xlsx`, and a bounded `BatchQueue` that schedules one-company discovery/enrichment work with configured pacing and isolated errors.

- [ ] **Step 1: Write failing import and queue tests**

Cover UTF-8 CSV, required company and city columns, XLSX rows, duplicate company identity collapse, one-company failure isolation, retry-after persistence, and request pacing.

- [ ] **Step 2: Run focused tests and confirm missing batch modules**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/batch backend/tests/services/test_batch_queue.py -q`.

- [ ] **Step 3: Implement importers with explicit validation**

Accept UTF-8 CSV and `.xlsx`, normalize headers, reject rows without company name or city with row-numbered errors, and deduplicate by normalized city/company identity before creating tasks.

- [ ] **Step 4: Implement bounded queue and checkpoint-aware resume**

Use one worker for browser-bound operations, keep rate limiting at the provider boundary, persist queued/running/completed/error states, resume only incomplete company IDs, and do not re-run successful delivery fingerprints.

- [ ] **Step 5: Add batch API/UI controls**

Expose upload, batch status, pause/resume, retry-errors, and per-company result links. Keep single-company workflow unchanged and show each company’s failure independently.

- [ ] **Step 6: Run all backend tests and frontend build**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest -q` and `npm.cmd --prefix frontend run typecheck && npm.cmd --prefix frontend run build`.

- [ ] **Step 7: Commit batch support**

Run: `git add backend frontend && git commit -m "feat: add batch company input and queue"`.

### Task 12: Run final requirement audit and manual acceptance

**Files:**
- Modify: `task_plan.md`, `progress.md`, and `findings.md` with evidence only.
- Create: `.env.example`, `README.md`, and `docs/operations/mapsearch-acceptance.md`.

**Interfaces:**
- Produces reproducible local startup commands, configuration documentation, and an acceptance record for external-service behavior.

- [ ] **Step 1: Add reproducible configuration and startup documentation**

Document local SQLite startup, `AMAP_API_KEY`, dedicated browser profile/CDP settings, Doubao manual login/challenge handling, ERP configuration, automatic-delivery default off, and test commands. Keep the document UTF-8.

- [ ] **Step 2: Run the complete automated verification**

Run backend unit/integration/API tests, Ruff, frontend typecheck/build, and a smoke request against a local server. Record exact pass counts and any external-service checks that cannot run without credentials.

- [ ] **Step 3: Run a controlled real-environment acceptance sample**

Use a small manually selected company set. Record candidate correctness, address, source URL, Doubao evidence, ERP create/update result, duplicate behavior, browser pause/resume, and restart-from-checkpoint behavior without printing credentials.

- [ ] **Step 4: Audit every requirement against evidence**

Re-read the source requirements and verify each named endpoint, status, invariant, provider substitution rule, delivery gate, and final acceptance item against code, tests, command output, and manual records. Keep unmet external credential checks explicitly marked unverified.

- [ ] **Step 5: Update plans and commit the verified documentation**

Mark a phase complete only when its tests and acceptance criteria have evidence. Run `git diff --check`, then commit the final docs with `git add` and `git commit`.
