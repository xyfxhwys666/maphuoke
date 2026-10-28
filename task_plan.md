# MapSearch 实施计划

## Goal

按照《地图获客豆包复用设计开发文档.md》完成自然语言获客、公开网页确认真实公司名称、高德网页精确查询地址/电话/POI、证据核验到 ERP 幂等投递的可运行项目，并通过单元、集成、API、前端构建和人工验收。默认采集链路不使用豆包聊天网页。

## Phases

| Phase | Status | Deliverable |
| --- | --- | --- |
| 0. 共享领域层 | complete | 领域模型、标准化、合并、Fake 端到端、基础 API 和持久化 |
| 1. 高德网页 MVP | complete | 独立 CDP 浏览器、搜索/详情提取、暂停/重试 |
| 2. 豆包补全 | complete | 豆包网关、提示词/解析、检查点和候选合并 |
| 3. 证据与 ERP | complete | 地图证据、公开核验、门禁、适配器和幂等台账 |
| 4. API 与批量 | complete | 高德 API、统一 Provider、CSV/Excel、限速队列和工作台 |
| 5. 最终验收 | complete | 两段式公司名发现、服务烟测、自动化回归和高德登录态验收记录 |
| 6. 连接器账号隔离与缓存消费 | complete | 账号范围隔离、SQLite 消费台账、缓存优先搜索、桌面端联调契约 |

## Current Next Step

下一步是用共享环境做一次真实桌面端联调：确认登录后的租户/成员身份能进入 MapSearch 请求头，并记录一条真实公开核验结果；没有合格公开信息时保持 0 条。

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| 进度文件绝对路径少了 worktree 名称 | 1 | 重新使用 `C:\\Users\\Admin\\Documents\\MapSearch\\.worktrees\\map-lead-platform` 路径 |
| Ruff 导入排序失败 | 1 | 调整标准库和项目导入顺序后重跑检查 |
| 领域层 Ruff 导入/UTC 风格检查失败 | 1 | 使用 Ruff `--fix` 后重跑测试和静态检查 |
| Task 4 Ruff 导入排序和 BLE001 检查失败 | 1 | 修正导入并为按公司隔离的宽异常捕获添加明确 lint 说明 |
| Task 5 Ruff 报告 FastAPI Depends 规则和导入格式 | 1 | 配置 B008 为 FastAPI 依赖注入例外，使用 Ruff `--fix` 修复其余格式 |
| Task 5 存储测试导入排序检查失败 | 1 | 使用 Ruff `--fix` 修复测试导入顺序 |
| 聚焦 pytest 从 `backend` 子目录运行导致 `ModuleNotFoundError: backend` | 1 | 改从仓库根目录运行 `backend/tests/...` 测试路径 |
| 重启服务脚本使用 PowerShell 保留变量 `$PID` | 1 | 改用 `$mapBackendPid` 任务专用变量 |
| 旧服务进程未加载最新集合接口 | 本地服务烟测 | 只重启确认的 8017/5187 进程，随后验证任务列表、自然语言计划和独立高德打开接口 |

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| MapSearch 工作树为空 | 初始检查 | 按设计从零建立独立项目；参考样板只读 |
| Chrome 浏览器连接返回 `Browser is not available: chrome` | 真实网页联调 | 已读取 Chrome 排障说明；需要用户在 `Settings -> Computer use` 启用 Chrome 扩展后再做人工登录验收 |
| 批量首轮结果被重试对象回写 | 批量队列测试 | 返回 `BatchResult` 快照，队列当前状态通过 `results()` 单独读取 |
| 8017 服务启动后第二个任务返回 `UNIQUE constraint failed: map_candidates.id` | 本地 API 烟测 | 确认 Provider POI ID 只在任务内唯一；存储层改用任务 ID + 实体 ID 的 SHA-256 行 ID，并增加跨任务回归测试 |
| 真实高德探测返回 `waiting_for_challenge` | 8017 使用独立 Chrome 搜索 | 按安全边界暂停任务；需要用户在高德页面人工完成安全验证后再恢复，不绕过验证码或风控 |
| 详情卡片 DOM 重绘导致单家公司搜索超时 | 真实高德详情补全 | 详情尝试限制为前 2 个缺字段卡片；单卡片失败保留列表候选，并通过回归测试和 Ruff 验证 |
| `base` 环境没有 pytest | 聚焦集合测试 | 改用已安装项目依赖的 `doubao-leads` 环境执行后端命令 |
| 集合服务聚焦测试 `5 passed, 3 failed` | Phase 5 缺口复核 | 三个失败均对应待实现的字段级证据、公开证据注入和异步暂停行为，保留测试并进入实现阶段 |
| 新增合并测试导入不存在符号 | TDD 红灯准备 | 改为模块属性运行时调用，使测试进入明确的缺失行为断言 |
| Phase 5 扩展测试 `11 passed, 9 failed` | TDD 红灯验证 | 失败均对应待实现的集合服务、合并函数、任务列表和专用 Chrome 打开行为 |
| 独立完成审查发现 4 项 Important | 最终审查 | 分别增加目标 URL 去重、实际城市、重启恢复和批量多行状态回归测试，按 TDD 修复后全量通过 |
