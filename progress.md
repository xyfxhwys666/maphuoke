# Progress Log

## 2026-08-05

- 读取并核对需求文档的 19 个章节和 Phase 0 至 Phase 4 验收标准。
- 只读检查当前空仓库和参考样板结构。
- 确定独立项目、Provider 抽象、SQLite 默认存储、Fake 端到端优先和 ERP 默认关闭的设计。
- 写入设计文档、任务计划和发现记录；尚未写入业务代码。

## 2026-08-15

- 新增 MapSearch 账号范围字段和 SQLite 消费台账，连接器任务、结果、控制接口按范围隔离。
- 新增 `/connector/v1/search` 缓存优先接口，消费后才允许创建新任务，ERP 继续关闭。
- 桌面主进程从 `BackendSessionClient.getStorageIdentity()` 派生范围请求头，Renderer 只提交查询文本和模型列表。
- 验证：后端 `218 passed`、Ruff 通过；桌面 shell `225 passed`、renderer `324 passed`、类型检查和构建通过。
- 创建 `codex/map-lead-platform` 隔离 worktree。
- 完成 Task 1：FastAPI `/health`、Python 项目配置、Vite/React 骨架和 `.gitignore`。
- 验证：后端 `1 passed`；前端 typecheck 和 build 通过；npm audit `0 vulnerabilities`。
- 完成 Task 2：手机号、座机/400、公司名、邮箱和微信标准化。
- 验证：TDD focused/full tests `4 passed`；Ruff `All checks passed`。
- 完成 Task 3：`MapPoiCandidate`、`DoubaoEnrichment`、`LeadRecord`、字段合并、联系方式/公司去重、SHA-256 指纹和 ERP 证据门禁。
- 验证：领域与全套测试 `11 passed`；Ruff `All checks passed`。
- 完成 Task 4：任务状态迁移、公司级进度、检查点、Fake Map/Doubao/证据/ERP 和内存编排服务。
- 验证：全套后端测试 `16 passed`；Ruff `All checks passed`。
- 配置远程：`origin git@gitee.com:xyfxhwys/map-search.git`。
- 核对高德官方文档后确定：API 不是无限免费保证，且不等同网页搜索；继续以 Chrome 网页搜索为主，API 后置为可选 Provider。
- 完成 Task 5：SQLAlchemy SQLite 存储、任务 Repository、Phase 0 API 路由和状态/检查点恢复。
- 验证：后端全套测试 `21 passed`；Ruff `All checks passed`。
- 批量测试首次运行：`4 passed, 1 failed`；定位为 `BatchResult` 可变对象被重试流程回写，准备增加执行结果快照。
- 完成批量工作流：CSV/XLSX 原始请求体上传、批次创建/启动/查询/失败重试 API、单线程限速队列和前端批量结果表。
- 完成批量失败隔离：失败项保留子任务 ID，重试复用原子任务，不重新创建子任务；批次支持成功/失败状态快照。
- 完成 ERP 失败重试修复：失败投递不写入成功 fingerprint，`retry-errors` 可重新投递并清除当前失败标记。
- 完成地图证据关联：网页和 API Provider 都将稳定 `evidence_snapshot_id` 写回候选 `source_metadata`。
- 前端新增“单家公司 / 批量导入”分段模式、CSV/XLSX 选择、批次状态、失败项重试和子任务打开入口。
- 新增 `README.md`、`.env.example` 和 `docs/operations/mapsearch-acceptance.md`，并完成 UTF-8/乱码标记检查。
- Chrome 真实连接尝试返回 `Browser is not available: chrome`；未绕过登录，也未宣称真实高德/豆包/ERP 验收已完成。
- 最终回归：后端 `70 passed`；Ruff `All checks passed`；前端 Vitest `5 passed`；TypeScript 和 Vite 构建通过。
- 本地服务烟测发现旧数据库中不同任务使用相同 Provider POI ID 会触发主键冲突；新增 TDD 回归测试，并将候选/线索存储行 ID 改为任务隔离的 SHA-256。修复后 8017 重启，Fake 任务搜索返回 `candidates_ready`，批量 CSV 去重烟测返回 2 个任务。
- Chrome 诊断：Google Chrome 已安装且正在运行，Codex Chrome 扩展未安装/未启用；真实高德和豆包网页验收仍等待用户在 `Settings -> Computer use` 启用扩展并人工登录。
- 完成高德网页适配器补强：搜索提交后等待异步结果卡片；候选缺少电话、分类、坐标或 POI ID 时进入详情页，合并详情字段并保留列表地址与详情来源 URL。
- TDD 回归验证：高德网页 Provider 测试 `5 passed`；后端全套测试 `74 passed`；Ruff `All checks passed`；前端 Vitest `6 passed`；TypeScript 与 Vite 构建通过。
- 8017 运行时烟测：健康检查、Provider 列表和 ERP 配置接口通过；Fake 任务验证未满足证据门禁时返回 `display_only`；真实高德探测返回 `waiting_for_challenge`，任务暂停等待人工安全验证。
- Phase 5 审计新增回归测试：持久化 ERP 台账跨服务重启防重复、任务级联系方式门禁和检查点时间字段；首次聚焦测试因从 `backend` 子目录运行导致命名空间导入错误，已确认应从仓库根目录重跑。
- 完成详情预算修复：`AmapPageAdapter` 对缺字段候选最多尝试前 2 个详情卡片，单卡片异常保留列表候选；高德 Provider 测试 `8 passed`。
- 最终自动化回归：后端 `87 passed`，Ruff `All checks passed`，前端 Vitest `6 passed`，TypeScript 与 Vite 构建通过；测试仅保留现有 Starlette/httpx 弃用警告。
- 重启 8017 并启动独立可见 Chrome（CDP 9227）；真实“腾讯科技 / 深圳市”网页搜索返回 4 个候选，包含地址、坐标和地图来源。当前等待用户在新 Chrome 窗口中完成高德登录或安全验证。
- 完成 CityProspect 前端工作台：默认入口改为自然语言获客，保留单家公司和批量导入模式；新增模型选择、持续采集、证据约束 ERP 开关、任务队列、计划进度、城市 × 关键词表和匹配公司结果表。
- 新增前端状态测试、集合任务类型和 API 客户端；前端 Vitest `8 passed`，TypeScript 与 Vite production build 通过。
- 完成集合任务自动 ERP 行为：只有联系方式满足需求且通过独立证据核验时才投递；捕获状态保持 `display_only`。后端新增行为测试，完整回归 `107 passed`，Ruff `All checks passed`。
- 重启当前 worktree 的后端 `8017` 和前端 `5187`；健康检查、集合模型列表和自然语言计划创建烟测通过，计划创建没有触发地图搜索。
- Chrome 控制扩展仍不可用（`Browser is not available: chrome`）；已直接启动可见独立 Chrome，CDP `9227`，打开高德和本地界面，等待用户手动登录/安全验证后再继续真实网页恢复验收。
- Phase 5 缺口复核：集合服务聚焦测试 `5 passed, 3 failed`；失败分别暴露字段级证据门禁、公开证据注入和异步暂停接口。`base` 无 pytest，后续后端命令固定使用 `doubao-leads` 环境。

## 2026-08-06

- 完成 Phase 5 缺口收尾：集合任务支持后台启动、暂停/恢复/重试；注入公开证据核验器；按任务要求执行字段级联系方式门禁；ERP 投递台账跨任务持久化幂等；任务列表和专用高德打开接口已注册。
- 仅重启当前 `map-lead-platform` 工作树对应的后端 `8017` 和前端 `5187` 进程，未修改 SQLite 数据库或独立 Chrome 登录 profile。
- 本地烟测通过：`/health`、自然语言计划创建（只计划不搜索）、`/api/v1/collection-tasks` 列表恢复、任务详情和 `/api/v1/collection-browser/amap/open` 返回 `ready`。
- 独立可见 Chrome 的 CDP `9227` 同时保留高德地图和本地工作台标签；高德登录/安全验证仍需用户在该窗口人工完成。
- 新鲜自动化回归通过：后端 `117 passed`（保留 1 个既有 Starlette/httpx 弃用警告）、Ruff `All checks passed`、前端 Vitest `9 passed`、TypeScript 检查通过、Vite production build 通过。
- 根据用户纠正，集合默认链路已替换为公开网页真实公司名发现后再调用高德 `search_company()` 精确查询；不再用高德宽关键词搜索产生最终公司候选，也不调用豆包聊天网页判断或补全。
- 新增 TDD 回归：公开搜索标题提取正式公司名并保存来源；集合服务禁止在两段式模式调用 `search_keyword()`，必须将真实公司名逐个传入高德精确查询，并保留高德电话、地址、POI 与公开名称证据。
- 移除自然语言工作台的模型选择和豆包登录提示，统计改为公开网页确认公司名和高德精确查询；聚焦后端 `23 passed`、Ruff 和前端 TypeScript 检查通过，完整回归待执行。
- 按 CityProspect 的任务队列、执行面板和信息表结构重做自然语言工作台；ERP 接收 URL、可选 Bearer Token、批量推送、城市筛选和单条人工推送均已接入。
- 最终表只展示高德精确匹配的公司名、电话、地址、分类、坐标、POI 与高德链接；公开网页仅显示为公司名称来源。批量推送自动跳过没有高德电话/手机的记录，单条推送会明确拒绝这类记录。
- ERP payload 默认来源更正为高德地图网页精确查询，并携带高德 URL、分类、坐标和 POI ID；不再声明豆包补全来源。
- 高德网页 Provider 改为复用已打开的高德搜索标签；只有当前页面不在高德时才进入首页，并将首次导航限制为 10 秒。
- 本地 `8017` 后端、`5187` 前端和 `9227` 高德窗口已重新打开。重启服务树时曾关闭高德窗口，已使用原独立 profile 恢复；需要时仍由用户在该窗口手动处理登录/安全验证。
- 本轮完整验证：后端 `136 passed`（仅 1 条既有 Starlette/httpx 弃用警告）、Ruff 通过、前端 Vitest `12 passed`、TypeScript 检查和 Vite production build 均通过。
- 继续真实高德小样本验收：最终持久化 9 个公开网页正式公司名，高德精确匹配 1 个真实 POI，返回地址、坐标、POI ID 和高德链接；该 POI 未公开电话，按规则保留但不推送。
- 修复真实 Playwright 页面文本读取异常被错误回退掩盖的问题；高德 Provider 测试增至 `11 passed`。
- 修复集合任务完成后检查点仍显示 `running/stopped` 的问题；完成终态和 Provider 浏览器状态现在同步持久化。
- 首页自然语言主文案移除“模型判断”，明确为公开网页确认公司全称后由高德逐家公司精确查询；左栏任务队列在需求编辑器之前显示。
- 更新 README 和验收记录：默认自然语言链路不再描述为高德关键词发现或豆包判断，豆包仅保留在可选旧单家公司补全流程；记录真实深圳软装任务、高德精确 POI 和无电话不投递结论。
- 新鲜全量回归：后端 `137 passed`（1 条既有 Starlette/httpx 弃用警告），Ruff `All checks passed`；前端 Vitest `13 passed`，TypeScript 检查和 Vite production build 通过。
- 独立代码审查发现并修复四项重要问题：ERP 去重按目标 URL 隔离、高德实际城市校验、重启遗留运行任务恢复为暂停、批量推送一次合并所有行状态；新增回归测试均先红后绿。
- “持续采集”现在有明确语义：默认开启跑完计划，关闭时每个工作单元后暂停；两份 CityProspect 设计/实施文档已重写为当前两段式默认链路。
- 修复后的新鲜全量回归：后端 `142 passed`（1 条既有 Starlette/httpx 弃用警告），Ruff `All checks passed`；前端 Vitest `14 passed`，TypeScript 检查和 Vite production build 通过。
- 只重启 8017 后端到 PID `20200`，9227 高德 Chrome 保持 PID `34520`；健康检查返回 `ok`。
- 右侧 851px 工作台最终刷新确认：持续采集默认勾选，页面无横向溢出，真实任务加载今至软装结果、批量推送和 1 条高德最终结果。
- 修复后只读复审确认 6 个检查区域均无剩余 Critical/Important 问题，结论为 `Ready to merge`。
