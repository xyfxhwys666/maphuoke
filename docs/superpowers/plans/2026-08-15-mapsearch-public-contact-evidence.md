# MapSearch 公开联系方式证据发现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为已采集联系方式发现独立公开证据，只有企业名与同一联系方式同页出现才升级为可展示结果。

**Architecture:** `PublicEvidenceVerifier` 先验证已有来源页；未命中时访问固定公开搜索入口、提取有限候选 URL，再复用同页精确匹配。连接器和桌面端接口不变。

**Tech Stack:** Python、httpx、HTMLParser、pytest。

## Global Constraints

- 不读 Cookie、不登录、不绕过验证码或访问控制。
- 候选页必须同页精确包含企业名和手机号或邮箱。
- 最多抓取 5 个候选公开页；失败保持 `captured`。
- 不将搜索摘要作为证据，不改 ERP 行为。

---

### Task 1: 发现并验证公开候选页

**Files:**
- Modify: `backend/app/providers/public_web.py:232-289`
- Modify: `backend/tests/providers/test_map_evidence.py:75-100`

- [ ] 写一个失败测试：高德来源页只含企业名，固定搜索入口返回公开联系页，公开联系页同时含同企业名和同手机号时必须返回 `verified_public_web`。
- [ ] 运行该测试，确认当前实现因不做搜索发现而失败。
- [ ] 在 `PublicEvidenceVerifier` 增加可注入 `search_endpoints` 和 `max_discovered_urls=5`；用 `_PublicSearchResultParser` 提取 HTTP(S) 候选 URL，排除搜索入口自身和重复链接。
- [ ] 将发现 URL 追加到现有来源 URL 后，复用现有可见文本、企业名与联系方式精确匹配循环。
- [ ] 新增反例：候选页缺少企业名或缺少联系方式时必须保持 `captured`。
- [ ] 运行 `python -m pytest backend/tests/providers/test_map_evidence.py -q`，预期通过。

### Task 2: 回归与交接

**Files:**
- Modify: `docs/superpowers/specs/2026-08-15-mapsearch-public-contact-evidence-design.md`
- Modify: `docs/superpowers/plans/2026-08-15-mapsearch-public-contact-evidence.md`

- [ ] 运行 `python -m pytest backend/tests/providers/test_map_evidence.py backend/tests/api/test_connector_routes.py -q`，确认未核验电话仍不可见。
- [ ] 运行 `python -m pytest backend/tests -q`，预期通过。
- [ ] 用 UTF-8 验证两份文档并以中文提交，提交只包含本任务文件。
