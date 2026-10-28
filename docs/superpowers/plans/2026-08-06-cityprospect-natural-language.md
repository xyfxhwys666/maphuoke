# CityProspect Natural-Language Collection Implementation Plan

**Goal:** 将 MapSearch 默认入口实现为 CityProspect 风格的自然语言获客工作台，并完成“公开网页正式公司名 -> 高德实际城市与全称精确匹配 -> 高德最终字段 -> 可选 ERP 推送”的可恢复链路。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、SQLite、Pydantic、pytest、Ruff、React、TypeScript、Vitest、Vite。

## Final Architecture

```text
Natural-language brief
  -> deterministic city/keyword expansion
  -> public-web formal company names
  -> Amap city + exact company lookup
  -> actual-city + exact-name validation
  -> Amap-canonical lead fields
  -> destination-scoped ERP delivery
```

默认链路不调用豆包聊天网页或模型判断。旧单家公司和 CSV/XLSX 批量入口继续保留。

## Constraints

- 创建计划时不启动外部网页搜索。
- 高德登录、验证码和安全验证只允许人工处理。
- 公开网页只作为公司名称来源证据。
- 高德电话、地址、分类、坐标、POI 和链接是最终字段。
- 无高德电话的记录保留为 `display_only`，不得推送。
- 高德实际城市或公司全称不匹配时拒绝候选。
- 自动 ERP 默认关闭；投递按目标 URL 隔离幂等。
- 服务重启后的非终态任务必须变为明确可恢复状态。
- 所有中文 Markdown 使用 UTF-8。

## Completed Work

### 1. Shared domain and persistence

- [x] Map/lead/evidence/delivery contracts
- [x] SQLite task, candidate, checkpoint and delivery ledger persistence
- [x] Stable task-isolated candidate/lead IDs
- [x] Field-level evidence and delivery gates

### 2. Amap browser and providers

- [x] Dedicated visible Chrome and CDP lifecycle
- [x] Amap list/detail extraction with bounded timeouts
- [x] Phone, address, category, coordinates, POI and source URL parsing
- [x] Optional Amap API Provider behind the same map contract
- [x] Login/challenge pause and resume behavior

### 3. Natural-language collection

- [x] Deterministic city and keyword expansion
- [x] Tier-3-plus nationwide city scope
- [x] Stable city x keyword work units
- [x] Public-web formal company-name discovery
- [x] Exact Amap lookup for each formal company name
- [x] Fuzzy company-name rejection
- [x] Actual-city extraction and cross-city rejection
- [x] Continuous mode: run all by default, pause per unit when disabled

### 4. Recovery and delivery

- [x] Background start, pause, resume and failed-unit retry
- [x] Checkpoint persistence after each work unit
- [x] Restart recovery from stale `queued/running` to resumable `paused`
- [x] ERP URL and optional Bearer Token controls
- [x] Batch and per-row delivery
- [x] Destination-scoped delivery fingerprint
- [x] Batch delivery merges every returned row into frontend state

### 5. CityProspect workbench

- [x] Task queue before the request composer
- [x] Natural-language request editor and examples
- [x] Execution status, summary and city progress
- [x] ERP delivery controls
- [x] Amap final-results table and city filter
- [x] Responsive narrow/desktop layouts without page-level overflow
- [x] Existing single-company and batch tabs retained

### 6. Documentation and acceptance

- [x] README startup, workflow and external configuration boundaries
- [x] Real Amap sample task recorded
- [x] UTF-8 and mojibake validation
- [x] Full backend/frontend automated verification
- [x] Local service health check and visual browser verification

## Verification Commands

```text
conda run -n doubao-leads --no-capture-output python -m pytest -q
conda run -n doubao-leads --no-capture-output ruff check backend/app backend/tests
npm.cmd --prefix frontend run test -- --run
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
git diff --check
```

The exact current counts and real sample evidence belong in `docs/operations/mapsearch-acceptance.md`, `progress.md`, and `findings.md`; update them only from fresh command or runtime output.

## External Configuration Boundaries

- ERP create/update/duplicate behavior against the user's actual system remains pending until a real target URL and credentials are supplied.
- Amap Place Text API remains unconfigured while `AMAP_API_KEY` is empty.
- Amap phone availability depends on the selected POI; no other source may be substituted as an Amap phone.
