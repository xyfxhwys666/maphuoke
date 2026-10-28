# 地图获客 + 豆包补全平台设计

**日期：** 2026-08-05

**状态：** 已按需求文档确定默认方案

## 目标

在独立的 `MapSearch` 项目中实现完整链路：输入公司名称和城市，通过高德地图发现并让用户选择 POI，调用豆包网页补全公开联系方式和企业信息，保存来源与证据，执行标准化、去重和核验，最后按门禁手动或自动推送 ERP。

实现顺序遵循需求文档的 Phase 0 至 Phase 4。第一版默认单家公司、城市必填、自动 ERP 投递关闭、地图单源结果仅展示；真实高德账号、豆包会话和 ERP 均通过配置接入。

## 方案选择

采用独立新项目并提取样板中的稳定契约，不复制样板工作树。项目使用 FastAPI、SQLAlchemy、SQLite 默认存储和 React/Vite 前端；数据库连接、浏览器路径、CDP 端口、豆包来源名和 ERP 地址全部由配置提供。

直接复制样板会带入其城市批量采集、运行时状态和未提交测试产物，导致新业务与旧页面及任务模型耦合。只做高德 API 会绕开文档要求的网页 MVP。Provider 抽象允许网页实现先交付、API 后替换，不影响补全、核验和投递主链路。

## 系统边界

```text
React UI
  -> FastAPI routes
  -> CompanySearchService
       -> MapDiscoveryProvider
       -> CandidateNormalizer / Deduplicator
       -> DoubaoEnrichmentGateway
       -> EvidenceVerifier
       -> ErpAdapter + DeliveryLedger
  -> SQLAlchemy repositories
```

业务层只依赖协议，不依赖高德 DOM、Playwright 页面对象、豆包页面选择器或某一家 ERP 的字段名。页面选择器集中在地图适配器文件；浏览器 actor 负责单线程页面操作，业务服务只接收结构化结果。

## 领域合同

### `MapPoiCandidate`

必须保存 `candidate_id`、`company_name`、`city`、`address`、`telephone`、`category`、`longitude`、`latitude`、`poi_id`、`source_url`、`discovery_channel`、`raw_text`、`source_metadata`、`captured_at` 和 `evidence_snapshot_id`。地图候选只要有公司名和地址就保留，不因缺少手机号、邮箱或微信丢弃。

### `LeadRecord`

统一记录任务、城市、公司名、手机号、座机、邮箱、微信、联系人和职务、地址、服务简介、地图与公开网页来源、证据片段、字段状态、补全状态、核验状态、投递状态、重试信息和稳定指纹。地图原始字段放在 `source_metadata`，豆包空字段不能覆盖地图地址、电话、来源和简介。

### 证据状态

每个联系方式至少区分 `captured`、`source_backed` 和 `verified`。豆包返回但没有独立证据的手机号可以展示，不能通过默认自动 ERP 门禁。公司名称核验与联系方式核验分别判断；`verified_map` 默认只能展示，`verified_public_web`、`verified_official_page` 和 `verified_cross_source` 才能自动投递。

### 电话规则

`telephone` 保留座机、400 电话和地图原始电话。`mobile` 只接受归一化后的中国大陆 11 位手机号；座机和 400 号码永远不能填入 `mobile` 或 ERP 的 `mobilePhone`。

## Provider 与浏览器

```python
class MapDiscoveryProvider(Protocol):
    id: str
    label: str
    configured: bool

    def search_company(
        self, *, company_name: str, city: str, max_results: int = 5
    ) -> list[MapPoiCandidate]: ...
```

Phase 1 的 `AmapWebProvider` 使用独立 user-data-dir 和固定 localhost CDP 端口。端口占用、登录和验证码在启动或搜索期间转换为可序列化的暂停状态，不绕过安全验证。地图页面 actor 使用 FIFO 命令队列；单家公司有独立超时，失败写入错误和 `retry_after` 后继续其他公司；连续失败达到配置阈值时暂停任务。

地图页面的选择器、备用语义定位和登录/挑战检测集中在页面适配器。提取顺序是可见搜索结果卡片、详情页、原始可见文本摘要；每个候选保存 POI ID、详情 URL、来源类型、抓取时间和字段级证据。Phase 4 的 `AmapApiProvider` 解析 Place Text API 的多页结果，执行间隔、限流重试和 marker URL 生成，输出完全相同的 `MapPoiCandidate`。

豆包网关复用“独立浏览器、单线程 actor、节流、超时、重连、登录/验证暂停和检查点”模式。提示词只允许返回联网实际出现的联系人、手机号、邮箱、微信和来源，并接受地图地址、电话等已知字段作为上下文；解析失败时保留错误，不降低证据门禁。

## 任务与存储

任务状态为 `created -> discovering_map -> candidates_ready -> enriching_doubao -> verifying -> ready -> delivering -> completed`，任意阶段可进入 `paused`、`waiting_for_login`、`waiting_for_challenge` 或 `completed_with_errors`。每家公司保存发现、补全、核验、投递、重试次数、下一次重试、最后错误和更新时间。

检查点记录当前阶段、当前公司索引和 ID、已完成集合、浏览器状态、最后成功查询时间、失败公司、重试时间、投递指纹和操作 ID。SQLite 是本地默认持久化；Repository 通过 SQLAlchemy 隔离存储细节，使用 `DATABASE_URL` 可以迁移到部署数据库。

## 合并、去重与 ERP

公司级去重使用 `city + normalized_company_name`；联系方式级去重使用手机号、邮箱和微信；payload 指纹对排除抓取时间后的稳定请求体计算 SHA-256。`customerAccountGuid` 使用稳定 UUID5：`map-lead:{city}:{normalized_company_name}`。重复执行只能更新同一公司，不得重复创建客户。

`ErpAdapter` 提供 `build_payload(task, lead)`、`deliver(payload)` 和 `fingerprint(payload)`。默认适配器映射公司名、简介、城市、需求文本、联系方式、地址与来源；座机进入其他联系方式字段。投递台账记录指纹、状态、响应摘要、操作 ID、失败原因和重试次数。没有公司名核验、联系人核验、手机号/邮箱或来源时，结果为 `display_only` 并给出明确门禁原因。

## API 与前端

后端提供 Provider、浏览器状态、任务创建/启动/查看/暂停/恢复/补全/核验/投递/重试、单条线索投递和 ERP 配置接口。创建任务接收公司名、城市、发现/补全 Provider、联系方式要求、自动投递开关和是否允许地图单源核验。

前端首屏是工作台而非营销页：顶部输入公司名和城市，左侧候选列表，右侧选中 POI 的地图来源、补全进度和结果表。候选必须可选择；结果表逐字段显示值、来源、证据、核验状态和投递原因；按钮根据门禁显示可推送、仅展示或重试。桌面和窄屏布局都保持信息可读，不将多个工作状态藏在不可见卡片中。

## 错误与安全

搜索无结果返回空候选并记录 `empty_result`。页面超时、DOM 读取失败、浏览器断开和豆包失败均按公司隔离，最多按配置重试；重连失败则保留检查点。登录和验证码只发出人工处理提示。真实凭据只读环境变量或本地未提交配置，不写入日志、数据库快照或测试夹具。

## 测试与验收

先用 Fake Map Provider、Fake Doubao Gateway、Fake Evidence Verifier 和 Fake ERP 完成端到端测试，再逐步接入网页和 API。单元测试覆盖标准化、解析、合并、证据门禁、去重、指纹和错误状态；集成测试覆盖地址保留、无联系方式候选、无证据号码仅展示、不同手机号冲突、暂停/恢复、断点续跑和 ERP 幂等重试。前端运行类型检查和生产构建。真实环境只用少量人工选定公司验收，确认 POI、地址、来源、证据和 ERP 结果。

## 阶段验收

- Phase 0：不依赖外部服务即可创建任务、合并线索、核验状态并模拟 ERP 投递。
- Phase 1：输入单家公司能返回可选高德候选；登录、验证码、超时和重试不破坏任务。
- Phase 2：豆包补全不会丢失地图字段；豆包失败仍可展示候选。
- Phase 3：无核验证据的号码不能自动投递；重复任务不创建重复客户；ERP 失败可独立重试。
- Phase 4：网页 Provider 替换为 API Provider 后，补全、核验、去重、任务和 ERP 代码无需改动；支持批量输入和限速队列。
