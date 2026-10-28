# MapSearch 账号隔离与缓存消费交接

> 阶段：2026-08-15
> 责任边界：MapSearch 连接器与桌面端主进程

## 已实现

1. `CollectionTask.account_scope` 保存 `tenantId:memberId` 形式的账号范围。没有范围的旧内部调用仍可运行；带范围的连接器请求只能读取同范围任务。
2. `/connector/v1/tasks`、任务详情、结果读取和暂停/继续/取消都读取 `X-MapSearch-Account-Scope`，跨账号任务统一返回 404 或不出现在列表中。
3. 新增 `POST /connector/v1/search`：先按账号范围和规范化查询文本查找已完成任务，只选择企业、联系方式和公开证据均已核验的结果，过滤已消费结果并写入 `collection_result_consumptions`；有缓存返回 `mode=cached`，缓存耗尽才创建并异步启动新任务返回 `mode=task`。
4. ERP 投递保持关闭，连接器只返回展示字段，不返回令牌、投递地址或原始任务描述。

## API 示例

桌面端主进程发送身份范围，渲染层不得传入或覆盖该字段：

```http
POST /connector/v1/search
X-MapSearch-Account-Scope: 138:19
Content-Type: application/json

{"request_text":"查询深圳软装公司，找 1 条有效信息。","models":[]}
```

缓存命中：`{"mode":"cached","task_id":null,"status":"completed","items":[...]}`

缓存耗尽：`{"mode":"task","task_id":"collection-...","status":"queued","items":[]}`

## 数据与兼容性

- 消费记录表由 SQLAlchemy `create_all` 创建：`collection_result_consumptions`。
- 记录键为 `account_scope + result_fingerprint`，同一账号重启后不会重复消费；不同账号即使拿到同一企业也互不影响。
- 旧任务没有 `account_scope` 时不会泄漏给带身份范围的桌面请求；无范围的内部测试调用仍可读取。
- 公开信息不足时返回 0 条，不伪造手机号、证据或企业信息。

## 联调约定

- 开发二后端只需要部署 MapSearch 连接器和数据库表；不要让 Renderer 直接设置账号范围。
- 桌面端配置 MapSearch 地址并登录后，主进程会自动添加请求头。
- 手动验收优先调用 `/connector/v1/search`，不要直接调用旧的 `/connector/v1/tasks` 创建接口验证缓存规则。
- ERP 不参与本阶段验收；结果直接显示在 MapSearch WorkMate 面板并登记数字资产。
