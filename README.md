# MapSearch

MapSearch 是一个本地 CityProspect 线索工作台：用户输入自然语言客户需求，系统拆解城市和行业关键词，从公开网页发现真实、正式的公司全称，再按“城市 + 公司全称”逐家到高德网页精确查询。最终电话、地址、分类、坐标、POI 和高德链接以高德结果为准，并可按门禁投递 ERP。

默认主路径是独立 Chrome 网页高德搜索。高德 Place Text API 已实现为可选 Provider，但它不是网页搜索的等价替代，也不是无限免费服务；是否有免费额度、调用上限和超额价格取决于高德账号认证、Key 配额和当前服务条款。

## 本地启动

在项目根目录打开两个终端。

后端：

```text
conda run -n doubao-leads --no-capture-output python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8017
```

前端：

```text
cd frontend
npm.cmd run dev -- --host 127.0.0.1
```

打开 <http://127.0.0.1:5187>。后端健康检查为 <http://127.0.0.1:8017/health>。

需要单独打开高德 Chrome 窗口时，使用独立 profile 和 CDP 端口，避免复用日常浏览器会话：

```text
chrome.exe --remote-debugging-port=9227 --user-data-dir="%TEMP%\map-lead-platform\profiles\amap" https://www.amap.com/
```

高德登录、验证码和安全验证必须由用户在这个窗口中完成。Chrome 控制扩展未连接时，项目仍会显示本地界面，但不会自动绕过登录或验证。

## 配置

复制 `.env.example` 为 `.env`，再按实际环境填写。默认 SQLite 数据库、ERP 自动投递关闭，空的 `AMAP_API_KEY` 不会启用 API Provider。

高德网页使用独立 CDP 端口和独立浏览器 profile。遇到登录、验证码或安全验证时，任务会暂停并显示 `等待登录` 或 `等待人工处理`，必须在 Chrome 中人工完成后点击恢复；项目不会绕过验证。豆包网页只保留在可选的旧单家公司补全流程中，不参与默认自然语言采集。

## 工作流

- 自然语言获客：默认首页输入“找深圳和广州做高端家装的公司，需要手机号和邮箱，每城最多 20 家”等需求，先自动展开城市和业务关键词，再点击“开始采集”。每个工作单元先从公开网页提取正式公司全称，再用“城市 + 公司全称”调用高德网页精确查询；只有公司全称严格匹配的高德结果才进入最终信息表。
- 计划执行：任务队列保留计划、暂停、人工处理、部分失败和重试状态；高德安全验证暂停后，在独立 Chrome 完成处理，再点击“继续采集”。
- 单家公司：输入公司名和城市，选择正确 POI，点击豆包补全，再查看字段级来源、证据和 ERP 门禁。
- 批量导入：切换到“批量导入”，上传包含“公司名称”和“城市”列的 UTF-8 CSV 或 XLSX。队列单线程顺序搜索地图，失败项可单独重试，成功项不会重新创建子任务。
- 批量阶段当前负责发现 POI 并生成子任务；点击批次中的“打开”可以回到单家公司工作台继续补全、核验和投递。
- 没有独立公开证据的联系方式可以展示，但默认不能自动投递 ERP。座机和 400 电话保存在 `telephone`，不会误填进手机号字段。

自然语言任务对应的主要接口是 `POST /api/v1/collection-tasks/from-natural-language`、`POST /api/v1/collection-tasks/{task_id}/start`、`POST /api/v1/collection-tasks/{task_id}/pause`、`POST /api/v1/collection-tasks/{task_id}/resume` 和 `POST /api/v1/collection-tasks/{task_id}/retry-errors`。创建任务只生成计划，不会立刻搜索地图。

## Provider

`GET /api/v1/providers` 会列出网页和 API Provider 的配置状态。业务层只依赖统一的 `MapDiscoveryProvider` 合同。默认自然语言链路使用公开网页作为公司名称来源证据，并以高德网页字段作为最终结果；可选高德 API Provider 和旧单家公司豆包补全不会改变这条默认规则。

高德 API 需要 Key、配额和合规配置；网页搜索更接近人工网页使用方式，但吞吐和页面稳定性受浏览器状态影响。生产批量运行前应先用少量公司人工验收。

## 验证命令

```text
conda run -n doubao-leads --no-capture-output python -m pytest -q
conda run -n doubao-leads --no-capture-output ruff check backend/app backend/tests
cd frontend
npm.cmd test -- --run
npm.cmd run typecheck
npm.cmd run build
```

真实高德网页采集需要独立 Chrome 登录态；ERP 联调需要实际接收 URL 和凭据；高德 API Provider 需要 `AMAP_API_KEY`。默认自然语言链路不需要豆包登录态，旧单家公司豆包补全流程除外。
