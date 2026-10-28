# MapSearch 账号级缓存结果优先 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 查询优先返回全局结果池中尚未分配、城市和行业意图相符的已核验 MapSearch 线索；没有可用缓存才创建采集任务。

**Architecture:** 保持桌面端与 `POST /connector/v1/search` 契约不变。在 `ConnectorFacade.search()` 解析请求为既有采集意图，用纯辅助函数匹配缓存任务的城市和行业；结果继续由 `_result_items()` 只放行双重 `verified` 数据，并由全局消费台账原子认领一次。

**Tech Stack:** Python、FastAPI、Pydantic、pytest。

## Global Constraints

- 只返回企业名称和联系方式均为 `verified` 的结果。
- 搜索只读取全局已完成任务中的公开已核验结果；任务详情仍由 `account_scope` 隔离。
- 不包含 ERP 投递、跨账号任务共享、验证码绕过或浏览器会话读取。
- 无可用缓存时才创建新任务，现有关键词扩展和异步启动逻辑保持不变。

---

### Task 1: 以城市和行业匹配缓存任务

**Files:**
- Modify: `backend/app/connector/service.py:86-137`
- Modify: `backend/tests/api/test_connector_routes.py:176-239`

**Interfaces:**
- Consumes: `parse_collection_intent(request_text) -> ParsedCollectionIntent`。
- Produces: `_task_matches_cached_search(task: CollectionTask, request_intent: ParsedCollectionIntent) -> bool`。

- [ ] **Step 1: 写失败测试**

```python
def test_connector_search_reuses_same_city_and_industry_cached_result_when_text_differs(client):
    service = client.app.state.collection_service
    cached = service.create_from_text(
        '寻找深圳市室内设计公司，需要 1 条有效信息。',
        account_scope='tenant-a:member-1',
    )
    cached.status = 'completed'
    cached.results = [_verified_lead(cached.id, '深圳市', '深圳室内设计有限公司')]

    response = client.post(
        '/connector/v1/search',
        headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'},
        json={'request_text': '查询深圳软装公司，找 1 条有效信息。'},
    )

    assert response.status_code == 200
    assert response.json()['mode'] == 'cached'
    assert response.json()['items'][0]['company_name'] == '深圳室内设计有限公司'
```

- [ ] **Step 2: 确认测试按预期失败**

Run: `python -m pytest backend/tests/api/test_connector_routes.py::test_connector_search_reuses_same_city_and_industry_cached_result_when_text_differs -q`

Expected: FAIL，因为当前逻辑要求任务请求文本完全相同。

- [ ] **Step 3: 实现最小匹配函数**

在 `service.py` 中导入 `parse_collection_intent` 和 `ParsedCollectionIntent`，并将精确文本判断替换为：

```python
request_intent = parse_collection_intent(payload.request_text)
if not _task_matches_cached_search(task, request_intent):
    continue
```

`_task_matches_cached_search()` 必须：请求指定城市时，要求任务结果至少存在同一城市；将软装、室内设计、装饰、家居、全案设计归为同一稳定行业标签；其他关键词比较清洗后的原词。不得从公司名推测行业。

- [ ] **Step 4: 验证通过并提交**

Run: `python -m pytest backend/tests/api/test_connector_routes.py::test_connector_search_reuses_same_city_and_industry_cached_result_when_text_differs -q`

Expected: PASS。

```text
git add backend/app/connector/service.py backend/tests/api/test_connector_routes.py
git commit -m "MapSearch：按城市行业复用账号缓存结果"
```

### Task 2: 限制消费数量并保留回退语义

**Files:**
- Modify: `backend/app/connector/service.py:93-137`
- Modify: `backend/tests/api/test_connector_routes.py:176-239`

**Interfaces:**
- Consumes: `_task_matches_cached_search()`、`_is_consumed()`、`_record_consumption()`。
- Produces: 最多 `target_valid_contacts` 个 `ConnectorResultItem`，并由全局消费台账原子认领；无项目则 `mode='task'`。

- [ ] **Step 1: 写失败测试**

```python
def test_connector_search_returns_requested_number_of_matching_unconsumed_results(client):
    service = client.app.state.collection_service
    cached = service.create_from_text('寻找深圳软装公司，找 2 条有效信息。', account_scope='tenant-a:member-1')
    cached.status = 'completed'
    cached.results = [
        _verified_lead(cached.id, '深圳市', '深圳第一软装有限公司', phone='0755-10000001'),
        _verified_lead(cached.id, '深圳市', '深圳第二软装有限公司', phone='0755-10000002'),
        _verified_lead(cached.id, '广州市', '广州软装有限公司', phone='020-10000003'),
        _captured_lead(cached.id, '深圳市', '深圳未核验有限公司'),
    ]
    response = client.post('/connector/v1/search', headers={'X-MapSearch-Account-Scope': 'tenant-a:member-1'}, json={'request_text': '查询深圳室内设计公司，找 1 条有效信息。'})
    assert response.json()['mode'] == 'cached'
    assert [item['company_name'] for item in response.json()['items']] == ['深圳第一软装有限公司']
```

- [ ] **Step 2: 确认测试按预期失败**

Run: `python -m pytest backend/tests/api/test_connector_routes.py::test_connector_search_returns_requested_number_of_matching_unconsumed_results -q`

Expected: FAIL，因为当前缓存循环没有按目标数量截断。

- [ ] **Step 3: 实现限制**

```python
limit = max(request_intent.target_valid_contacts or 1, 1)
for task in self._service.list_tasks(account_scope=account_scope):
    # 仅在 _task_matches_cached_search() 为真时进入
    for item in self._result_items(task):
        if len(items) >= limit:
            break
        # 保持既有 fingerprint 去重和 _record_consumption()
    if len(items) >= limit:
        break
```

异城和仅 `captured` 的记录必须仍分别由任务匹配和 `_result_items()` 排除；没有合格项目时保留既有创建、关键词扩展和 `resume_async()` 分支。

- [ ] **Step 4: 全量连接器回归并提交**

Run: `python -m pytest backend/tests/api/test_connector_routes.py -q`

Expected: PASS，包括既有的账号隔离、重复消费和仅已核验结果测试。

```text
git add backend/app/connector/service.py backend/tests/api/test_connector_routes.py
git commit -m "MapSearch：限制缓存结果数量并保持账号隔离"
```

### Task 3: 真实桌面端验收

**Files:**
- Modify: `docs/superpowers/plans/2026-08-15-mapsearch-account-cached-results.md`

**Interfaces:**
- Consumes: `POST /connector/v1/search` 的 `cached` / `task` 响应。
- Produces: 不含账号、密钥和原始联系方式的验收记录。

- [ ] **Step 1: 调用本机连接器搜索深圳软装一条有效信息**

Expected: 有当前账号未消费的合格缓存时响应 `mode=cached` 且仅一项；无缓存时响应 `mode=task` 与新任务 ID。

- [ ] **Step 2: 在桌面端能力中心执行相同查询**

Expected: 缓存命中时直接展示一条结果并写入数字资产；无缓存时展示任务进度；不出现 ERP 投递界面。

- [ ] **Step 3: 运行后端全量回归与提交验收记录**

Run: `python -m pytest backend/tests -q`

Expected: PASS。

```text
git add docs/superpowers/plans/2026-08-15-mapsearch-account-cached-results.md
git commit -m "文档：记录MapSearch缓存优先验收"
```

## Self-review

- 规格中的同账号、同城市行业、已核验、未消费、无缓存才建任务由任务 1 和任务 2 覆盖。
- 接口与桌面端调用不变，未扩大协作接口或权限范围。
- 每个实现任务都从失败测试开始，并包含可重复的验证命令。
