# Shenzhen 100-Phone Leads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MapSearch use the CityProspect page hierarchy and continue the Shenzhen public-company-name to exact-Amap workflow until it has 100 unique Amap records with published mainland China mobile numbers.

**Architecture:** Keep the existing two-stage collection boundary: public search discovers formal company names, then the logged-in Amap Chrome session supplies canonical company and contact fields. Add explicit target/completion metadata and deterministic phone-valid counting to the collection domain, make public discovery paginate across existing sources, and render the results section after the complete workbench grid.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, httpx, SQLAlchemy, pytest, React 18, TypeScript, Vite, Vitest, Playwright-backed Amap Chrome provider.

## Global Constraints

- The default natural-language path must not open or call Doubao web chat.
- Public-web results may provide formal company-name candidates and evidence URLs only; final company name, mobile, address, category, coordinates, POI ID, and map URL come from Amap.
- A valid record is an exact-city, exact-company Amap match with a normalized mainland China 11-digit mobile matching `^1[3-9]\\d{9}$`.
- Landlines, 400 numbers, masked numbers, and invalid numbers never count toward the target and cannot be delivered.
- Records without a valid Amap mobile remain visible but do not count toward the target and cannot be delivered.
- Stop successfully only after 100 unique phone-valid records; otherwise report source exhaustion with the true count.
- Preserve pause/resume checkpoints and the existing ERP delivery contract.
- Do not require an Amap API key.

---

### Task 1: Encode the 100-record target and completion evidence

**Files:**
- Modify: `backend/app/collection/intent.py`
- Modify: `backend/app/collection/models.py`
- Modify: `frontend/src/types.ts`
- Test: `backend/tests/collection/test_intent.py`
- Test: `backend/tests/collection/test_service.py`

**Interfaces:**
- Produces: `ParsedCollectionIntent.target_valid_contacts: int | None`
- Produces: `CollectionSummary.target_valid_contacts`, `valid_contact_count`, `no_phone_count`, `rejected_count`, and `source_exhausted`
- Produces: `CollectionTask.completion_reason: Literal['target_reached', 'source_exhausted', 'completed_with_errors'] | None`

- [ ] **Step 1: Write failing intent and model tests**

```python
def test_shenzhen_as_many_as_possible_sets_100_phone_valid_target():
    intent = parse_collection_intent(
        '我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号码，尽量多找。',
        configured_models=set(),
    )
    assert intent.cities == ['深圳市']
    assert intent.required_contacts == ['mobile']
    assert intent.target_valid_contacts == 100


def test_explicit_record_target_wins_over_as_many_as_possible():
    intent = parse_collection_intent(
        '寻找深圳整装公司，需要电话，尽量多找，找 25 条有效信息',
        configured_models=set(),
    )
    assert intent.target_valid_contacts == 25
```

- [ ] **Step 2: Run the focused tests and confirm missing-field failures**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/collection/test_intent.py -q`

Expected: FAIL because `target_valid_contacts` is not defined.

- [ ] **Step 3: Add explicit target extraction and persisted summary fields**

```python
def _extract_target_valid_contacts(text: str, explicit_limit: int | None) -> int | None:
    if explicit_limit is not None:
        return explicit_limit
    if any(term in text for term in ('尽量多找', '越多越好', '多找一些')):
        return 100
    return None
```

Add the produced fields to the Pydantic/dataclass models with backward-compatible defaults, and mirror them exactly in TypeScript.

- [ ] **Step 4: Run intent, repository, and API serialization tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/collection/test_intent.py backend/tests/storage/test_collection_repository.py backend/tests/api/test_collection_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain contract**

```bash
git add backend/app/collection/intent.py backend/app/collection/models.py frontend/src/types.ts backend/tests/collection/test_intent.py backend/tests/collection/test_service.py
git commit -m "feat: track phone-valid collection targets"
```

### Task 2: Count unique Amap mobile records and stop at the target

**Files:**
- Modify: `backend/app/collection/service.py`
- Test: `backend/tests/collection/test_service.py`
- Test: `backend/tests/storage/test_collection_repository.py`

**Interfaces:**
- Produces: `CollectionService._unique_phone_valid_leads(task) -> list[LeadRecord]`
- Produces: `CollectionService._target_reached(task) -> bool`
- Consumes: `CollectionTask.intent.target_valid_contacts`

- [ ] **Step 1: Write failing tests for valid counting, deduplication, and early stop**

```python
def test_only_unique_amap_records_with_phone_count_toward_target():
    names = MultiCompanyNameDiscoveryProvider([
        ('深圳甲设计有限公司', '13800138000', 'A'),
        ('深圳甲设计有限公司', '13800138000', 'A'),
        ('深圳乙软装有限公司', None, 'B'),
        ('深圳丙整装有限公司', '13900139000', 'C'),
    ])
    task = targeted_collection_service(names, target=2).start_task()
    assert task.summary.valid_contact_count == 2
    assert task.summary.no_phone_count == 1
    assert task.completion_reason == 'target_reached'


def test_target_reached_skips_remaining_work_units():
    task, provider = targeted_collection_with_three_units(target=1)
    assert len(provider.company_lookup_calls) == 1
    assert task.work_units[1].status == 'skipped_limit'
    assert task.completion_reason == 'target_reached'
```

- [ ] **Step 2: Run the service tests and verify target behavior is absent**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/collection/test_service.py -q`

Expected: FAIL on valid counts, completion reason, and remaining provider calls.

Add the shown `MultiCompanyNameDiscoveryProvider`, `targeted_collection_service`, and `targeted_collection_with_three_units` test helpers beside the existing `FakeCompanyCandidateDiscoveryProvider` and `FakeExactCompanyMapProvider`. They must construct real `CompanyNameCandidate` and `MapPoiCandidate` instances and use `CollectionService.create_from_text()` and `start()`; they must not mutate a completed task directly.

- [ ] **Step 3: Implement canonical validity keys and target checks**

```python
def _unique_phone_valid_leads(self, task: CollectionTask) -> list[LeadRecord]:
    unique: list[LeadRecord] = []
    companies: set[str] = set()
    phones: set[str] = set()
    pois: set[str] = set()
    for lead in task.results:
        phone = normalize_mobile(lead.mobile) or normalize_mobile(lead.telephone)
        if not phone:
            continue
        candidate = next((item for item in task.candidates if f'lead-{item.candidate_id}' == lead.id), None)
        company = normalize_company_name(lead.company_name) or lead.company_name
        poi = candidate.poi_id if candidate and candidate.poi_id else ''
        if company in companies or phone in phones or (poi and poi in pois):
            continue
        companies.add(company)
        phones.add(phone)
        if poi:
            pois.add(poi)
        unique.append(lead)
    return unique


def _target_reached(self, task: CollectionTask) -> bool:
    target = task.intent.target_valid_contacts
    return target is not None and len(self._unique_phone_valid_leads(task)) >= target
```

Refresh the summary after each exact Amap result, break candidate and work-unit loops when the target is met, mark later units `skipped_limit`, and set `completion_reason='target_reached'`. When all units end below target, set `completion_reason='source_exhausted'` and `summary.source_exhausted=True`; failures take `completed_with_errors` precedence.

- [ ] **Step 4: Run service, persistence, and API tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/collection backend/tests/storage/test_collection_repository.py backend/tests/api/test_collection_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit deterministic target stopping**

```bash
git add backend/app/collection/service.py backend/tests/collection/test_service.py backend/tests/storage/test_collection_repository.py
git commit -m "feat: stop collection at unique phone target"
```

### Task 3: Exhaust public company-name discovery before reporting a shortfall

**Files:**
- Modify: `backend/app/providers/public_web.py`
- Modify: `backend/app/runtime.py`
- Test: `backend/tests/providers/test_public_company_names.py`

**Interfaces:**
- Produces: `PublicCompanyNameDiscoveryProvider(max_search_pages=5)` page-aware discovery
- Preserves: `discover_company_names(*, city, keyword, request_text, max_results) -> list[CompanyNameCandidate]`

- [ ] **Step 1: Write failing pagination and cross-page deduplication tests**

```python
def test_public_company_discovery_reads_configured_pages_and_deduplicates():
    requested_pages: list[int] = []
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get('page', '1'))
        requested_pages.append(page)
        name = '深圳甲软装设计有限公司' if page == 1 else '深圳乙室内设计有限公司'
        html = f'<li class="res-list"><h3><a href="https://example.com/{page}">{name}</a></h3><p>{name} 软装设计</p></li>'
        return httpx.Response(200, text=html, request=request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = PublicCompanyNameDiscoveryProvider(
        client=client,
        search_sources=(SOGOU_SOURCE,),
        max_search_pages=2,
    )
    items = provider.discover_company_names(
        city='深圳市', keyword='软装设计', request_text='家具客户', max_results=20,
    )
    assert {item.company_name for item in items} == {
        '深圳甲软装设计有限公司', '深圳乙室内设计有限公司',
    }
    assert set(requested_pages) == {1, 2}
```

- [ ] **Step 2: Run provider tests and confirm only page 1 is requested**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_public_company_names.py -q`

Expected: FAIL because `max_search_pages` is currently not used.

- [ ] **Step 3: Loop pages with source-specific page parameters and stable evidence merge**

```python
for page in range(1, self.max_search_pages + 1):
    params = {parameter: query, page_parameter: page_value(page)}
    response = self.client.get(source_url, params=params, headers=headers)
    # Parse, filter, merge URLs/quotes, and stop only when limit is reached.
```

Represent each source as `(url, query_parameter, page_parameter, page_value)` so Sogou, 360, and Bing receive their expected pagination value. Keep failed sources isolated and raise only when every request fails. Configure the runtime with five pages and a modest request interval; do not add a new external service.

- [ ] **Step 4: Run provider and full collection tests**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests/providers/test_public_company_names.py backend/tests/collection -q`

Expected: PASS.

- [ ] **Step 5: Commit exhaustive candidate discovery**

```bash
git add backend/app/providers/public_web.py backend/app/runtime.py backend/tests/providers/test_public_company_names.py
git commit -m "feat: paginate public company discovery"
```

### Task 4: Move collection results to the absolute bottom in CityProspect order

**Files:**
- Modify: `frontend/src/CollectionWorkbench.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/types.ts`
- Test: `frontend/src/collection.test.ts`

**Interfaces:**
- Produces: `collection-layout` containing sidebar and execution controls only
- Produces: `collection-results` as the final business child of `collection-workspace`
- Consumes: summary target, valid, no-phone, rejected, and exhaustion fields from Task 1

- [ ] **Step 1: Write failing server-render and summary-label tests**

```typescript
import { renderToStaticMarkup } from 'react-dom/server';
import CollectionWorkbench from './CollectionWorkbench';

test('renders results after the complete workbench grid', () => {
  const html = renderToStaticMarkup(<CollectionWorkbench />);
  expect(html.indexOf('class="collection-results')).toBeGreaterThan(
    html.indexOf('class="collection-layout'),
  );
  expect(html.lastIndexOf('class="collection-results')).toBeGreaterThan(
    html.lastIndexOf('class="collection-delivery'),
  );
});

test('labels the hard phone-valid target', () => {
  expect(collectionTargetLabel(37, 100, false)).toBe('有效手机 37 / 100');
  expect(collectionTargetLabel(37, 100, true)).toContain('数据源已耗尽');
});
```

- [ ] **Step 2: Run Vitest and confirm structural and helper failures**

Run: `npm.cmd test -- --run src/collection.test.ts`

Workdir: `frontend`

Expected: FAIL because results are nested in `collection-main` and `collectionTargetLabel` does not exist.

- [ ] **Step 3: Extract the result section and render it after `collection-layout`**

```tsx
<div className="collection-layout">
  <div className="collection-sidebar">{requestSection}{queueSection}</div>
  <div className="collection-main">{overviewSection}{statsSection}{planSection}{deliverySection}</div>
</div>
<section className="collection-results panel" aria-label="采集结果">
  {resultsHeading}
  {resultsTable}
</section>
```

The names in this structural sketch identify the existing JSX blocks to move; do not add new stateful components or variables with those names. Keep each existing block byte-for-byte where possible, close `collection-main` and `collection-layout` immediately after the delivery section, then place the existing results section after both closing tags.

Render the result section even before a task exists so the page hierarchy is stable. Show `有效手机 N / 100`, no-valid-mobile count, and source-exhaustion state next to the total Amap count. Rename the result contact column to `高德手机`, and only enable delivery for rows with a normalized mobile.

- [ ] **Step 4: Add full-width spacing and responsive constraints**

```css
.collection-results { width: 100%; margin-top: 18px; overflow: hidden; }
.collection-results-tools { flex-wrap: wrap; justify-content: flex-end; }
@media (max-width: 620px) {
  .collection-results-tools { align-items: stretch; flex-direction: column; }
}
```

Remove result-specific layout assumptions from `.collection-main`; keep table overflow inside `.collection-table-wrap`.

- [ ] **Step 5: Run frontend tests, typecheck, and production build**

Run: `npm.cmd test -- --run`

Run: `npm.cmd run typecheck`

Run: `npm.cmd run build`

Workdir: `frontend`

Expected: all commands PASS.

- [ ] **Step 6: Commit the CityProspect result hierarchy**

```bash
git add frontend/src/CollectionWorkbench.tsx frontend/src/styles.css frontend/src/types.ts frontend/src/collection.test.ts
git commit -m "feat: place collection results below workbench"
```

### Task 5: Full verification and real Shenzhen collection

**Files:**
- Modify: `docs/operations/mapsearch-acceptance.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: backend task API at `http://127.0.0.1:8017`
- Consumes: frontend at `http://127.0.0.1:5187`
- Consumes: dedicated logged-in Amap Chrome CDP session at port `9227`

- [ ] **Step 1: Run the complete automated verification suite**

Run: `conda run -n doubao-leads --no-capture-output python -m pytest backend/tests -q`

Run: `conda run -n doubao-leads --no-capture-output python -m ruff check backend`

Run: `npm.cmd test -- --run`

Run: `npm.cmd run typecheck`

Run: `npm.cmd run build`

Expected: all backend and frontend checks PASS with no new warnings beyond recorded third-party deprecations.

- [ ] **Step 2: Restart only MapSearch backend/frontend processes and preserve Chrome**

Use a Python process helper to resolve listeners on 8017 and 5187, terminate only the owning MapSearch processes, and launch the project commands hidden. Do not terminate or recreate the Chrome process on CDP 9227.

- [ ] **Step 3: Create and start the real Shenzhen task**

```json
{
  "request_text": "我是做家具的，寻找深圳全案软装公司、设计公司和整装公司，需要手机号码，尽量多找。",
  "continuous_mode": true,
  "verified_auto_deliver": false,
  "models": []
}
```

POST to `/api/v1/collection-tasks`, then POST `/api/v1/collection-tasks/{id}/start`. Poll the task without exposing cookies or credentials. If Amap requests login or verification, open the existing dedicated Chrome window and wait for the user-visible session to become ready; do not bypass a challenge.

- [ ] **Step 4: Verify every accepted row and the hard target**

Assert from the final task payload that:

```python
assert task['summary']['valid_contact_count'] >= 100
assert task['completion_reason'] == 'target_reached'
assert len(unique_amap_mobile_keys(task)) >= 100
assert all(item['source_url'].startswith('https://www.amap.com/') for item in mobile_valid_candidates(task))
```

If sources are exhausted below 100, preserve the task and exact counts, improve only evidence-backed discovery gaps, and rerun. Never alter the validity rule or import non-Amap phone numbers to satisfy the target.

- [ ] **Step 5: Perform visual acceptance at desktop and mobile widths**

Use the in-app browser to inspect `http://127.0.0.1:5187/` at 1440×900 and 390×844. Verify that the result section follows ERP controls and is the final business section; body width equals viewport width; the table scrolls internally; buttons, labels, and values do not overlap. Save screenshots and report their paths in the acceptance document.

- [ ] **Step 6: Update UTF-8 acceptance and progress records**

Record the task ID, final counts, completion reason, sampled Amap URLs, automated command results, viewport geometry, and screenshot paths. Decode every edited Chinese Markdown file as UTF-8 and run the standard Chinese mojibake-marker scan; inspect and correct every hit before commit.

- [ ] **Step 7: Commit acceptance evidence**

```bash
git add docs/operations/mapsearch-acceptance.md task_plan.md findings.md progress.md
git commit -m "test: verify Shenzhen 100-phone collection"
```
