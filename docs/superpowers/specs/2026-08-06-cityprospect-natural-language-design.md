# CityProspect 自然语言获客工作流设计

**日期：** 2026-08-06  
**状态：** 已实现并完成真实高德小样本验证

## 1. 产品目标

MapSearch 的默认入口是 CityProspect 风格的自然语言获客工作台。用户描述自己的业务和目标客户，系统自动展开城市与业务关键词，从公开网页发现真实公司全称，再逐家公司到高德网页精确查询。

默认链路为：

```text
自然语言需求
  -> 确定性意图解析与关键词扩展
  -> 城市 x 关键词工作单元
  -> 公开网页发现正式公司全称
  -> 高德网页按“城市 + 公司全称”精确查询
  -> 实际城市 + 公司全称严格匹配
  -> 高德字段形成最终线索
  -> 可选 ERP 人工/批量推送
```

默认自然语言链路不调用豆包聊天网页，也不使用模型相关性判断。豆包仅保留在兼容的旧单家公司补全流程中。

## 2. 数据权威边界

- 公开网页只提供公司名称候选、来源 URL 和证据摘要。
- 高德网页是最终电话、地址、分类、坐标、POI ID 和地图链接的权威来源。
- 公开网页号码不能覆盖、补齐或冒充高德电话。
- 高德返回的公司全称或实际城市不一致时，候选必须拒绝。
- 高德没有公开中国大陆 11 位手机号时仍保留公司和地址，但状态为 `display_only`，不能推送。座机和 400 电话不作为有效联系方式。
- 高德 Place Text API 是可选 Provider，不等同网页搜索；是否可用取决于 `AMAP_API_KEY`、配额和服务条款。

## 3. 意图与执行计划

`parse_collection_intent()` 将自然语言解析为：

- 明确城市，或全国三线及以上城市清单。
- 去重后的业务关键词，最多 24 个。
- 联系方式要求与 `any/all` 匹配规则。
- 每城数量上限。

`CollectionPlanner` 生成稳定的城市 x 关键词工作单元。创建任务只保存计划，用户点击“开始采集”后才访问外部网页。

`continuous_mode` 默认开启：

- 开启：按计划连续执行所有工作单元。
- 关闭：每完成一个工作单元即进入 `paused`，用户点击继续后执行下一个。

## 4. 公司名发现与高德精确匹配

`CompanyCandidateDiscoveryProvider` 从公开搜索结果提取正式公司全称，过滤“推荐榜、哪家好、十大品牌”等泛化标题。每个候选保存：

- 公司全称
- 城市和命中关键词
- 公司名称来源 URL
- 可复核证据摘要

`MapDiscoveryProvider.search_company()` 使用“城市 + 公司全称”查询高德。高德解析器优先从详情地址和可见文本提取实际城市；服务使用“实际城市 + 规范化公司全称”比较候选身份，拒绝跨城市或模糊名称。

高德详情提取受单次预算限制。单个详情超时只保留已经取得的列表字段，不阻塞整个任务；登录、验证码或安全验证转为可恢复的 `needs_attention`。

## 5. 线索与投递

最终 `LeadRecord` 保留高德字段和公司名称来源证据。ERP 推送支持：

- 接收 URL
- 可选 Bearer Token
- 批量推送
- 每行人工推送

投递前必须存在高德公开且格式有效的中国大陆 11 位手机号。座机和 400 电话不得触发投递。去重指纹由“规范化目标 URL + payload 指纹”组成，因此同一线索可分别推送到不同系统，同一目标内仍保持幂等。

ERP 失败不会删除线索，也不会消耗成功投递状态。持久化台账记录尝试、结果和 operation ID，不记录 Token 或 Authorization header。

## 6. 状态与恢复

任务状态：

```text
planned -> queued -> running -> completed
                     |-> completed_with_errors
                     |-> paused -> queued/running
                     |-> needs_attention -> queued/running
```

检查点保存当前工作单元、已完成/失败单元和浏览器状态。服务重启后，数据库中遗留的 `queued/running` 任务会恢复为明确可继续的 `paused`，不会在没有工作线程时永久显示运行中。

已完成工作单元不会在恢复或失败重试时重复执行。

## 7. API

主要接口：

```text
POST /api/v1/collection-tasks/from-natural-language
GET  /api/v1/collection-tasks
GET  /api/v1/collection-tasks/{task_id}
POST /api/v1/collection-tasks/{task_id}/start
POST /api/v1/collection-tasks/{task_id}/pause
POST /api/v1/collection-tasks/{task_id}/resume
POST /api/v1/collection-tasks/{task_id}/retry-errors
POST /api/v1/collection-tasks/{task_id}/deliver
POST /api/v1/collection-tasks/{task_id}/leads/{lead_id}/deliver
POST /api/v1/collection-browser/amap/open
```

请求可保留 `models` 字段用于旧客户端兼容，但默认自然语言执行不依赖模型或豆包。

## 8. 前端信息架构

工作台沿用 CityProspect 的紧凑任务界面：

- 左侧任务队列。
- 自然语言需求编辑器和示例。
- 持续采集与自动投递开关。
- 任务状态、总体统计和城市进度。
- ERP URL、可选 Token 和批量推送。
- 高德最终结果表及每行人工推送。

结果表展示城市、公司、高德电话、地址、分类/坐标、公司名来源、高德链接、推送状态和操作。窄视口使用可滚动表格，不允许页面级横向溢出或控件重叠。

## 9. 安全与外部边界

- 高德登录和安全验证只能由用户在独立 Chrome 中人工完成，项目不绕过验证码或风控。
- 默认使用独立 profile 和 CDP `9227`，避免复用日常浏览器会话。
- ERP URL/凭据未配置时只展示，不声称真实 ERP 联调完成。
- `AMAP_API_KEY` 未配置时 API Provider 显示未配置，网页 Provider 仍可使用。
- 不记录密码、Cookie、Bearer Token、Authorization header 或完整敏感页面数据。

## 10. 验收

自动化覆盖：

- 意图解析、城市/关键词矩阵和持续采集语义。
- 公开公司名发现、模糊名称和跨城市拒绝。
- 高德地址/电话/坐标/POI 解析及详情超时隔离。
- 无高德电话保留但禁止推送。
- 任务暂停、恢复、重启恢复和持久化。
- ERP 目标 URL 隔离幂等、失败重试和批量多行状态更新。
- API、前端状态、TypeScript、生产构建和响应式布局。

真实验收只使用少量公司。已验证任务及外部配置边界记录在 `docs/operations/mapsearch-acceptance.md`。
