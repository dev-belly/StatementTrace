# 财报数据的只读 API

在列式数据管道上加入 **FastAPI、Pydantic 和 Uvicorn**，让其他程序按公司、财年和
来源指标查询同一份经过核验的数据。原有静态研究报告仍可直接在 GitHub Pages 阅读；
这里的 API 需要在本机启动，不由 GitHub Pages 托管。

## 三分钟运行

在仓库根目录执行，使用一个新的或空的输出目录：

```bash
uv sync --locked --extra warehouse --extra api --extra dev
uv run --locked statementtrace warehouse --out output/api-demo
uv run --locked statementtrace serve-warehouse output/api-demo
```

默认监听 `127.0.0.1:8000`，按 Ctrl+C 停止。可以用 `--port 8080` 更改端口。
也支持用 pip 安装：`python -m pip install -e '.[warehouse,api]'`。

- 浏览器接口文档：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- 查看 Alphabet FY2024：`http://127.0.0.1:8000/v1/cashflow?symbol=GOOGL&period=2024`

Swagger UI 使用 FastAPI 默认的 CDN 脚本与样式。API 本身、OpenAPI JSON 和 curl 查询
在依赖安装后不需要外网；CDN 不可达时可以直接使用这些入口。

Linux/macOS 的 curl 示例；Windows PowerShell 可将 `curl` 换成 `curl.exe`：

```bash
curl "http://127.0.0.1:8000/v1/cashflow?symbol=GOOGL&period=2024"
curl "http://127.0.0.1:8000/v1/facts?symbol=AAPL&period=2024&metric=capex"
curl "http://127.0.0.1:8000/v1/facts?limit=7&offset=7"
```

## 路由与返回内容

| GET 路由 | 内容 | 筛选参数 |
| --- | --- | --- |
| `/healthz` | 已核验快照的 ID 和截止日；成功加载后才会开始服务 | 无 |
| `/v1/snapshot` | 截止日、快照 ID、来源位置数、公司年度数、USD 单位 | 无 |
| `/v1/quality` | 来源质量违规数及 Python / DuckDB 的精确核对结果 | 无 |
| `/v1/issuers` | 公司标识及保存的财年标签 | 无 |
| `/v1/cashflow` | 财务金额、精确比率、现金流增量与残差 | `symbol`、`period`、`limit`、`offset` |
| `/v1/facts` | 选择后的原始事实和明确缺失位置 | 以上参数，以及 `metric` |

`metric` 只接受 `revenue`、`net_income`、`operating_cash_flow` 和 `capex`。
`limit` 默认 100，范围 1–500；`offset` 从 0 开始，必须非负。
分页结果包含 `total`、`next_offset` 和 `snapshot`；下一页为空时 `next_offset` 为 `null`。
格式正确但不存在的公司或财年筛选返回空列表，保留当前快照身份。
公司标识区分大小写，采用案例中的大写形式。

## 金额为何是字符串

返回结构将金额、比率和增量分开。例如 Alphabet FY2024 的部分字段：

```json
{
  "amounts": {"free_cash_flow": "72764000000"},
  "ratios": {"fcf_growth": {"numerator": "3269", "denominator": "69495"}},
  "bridge": {"negative_delta_capex": "-20284000000", "bridge_residual": "0"}
}
```

这是完整响应中部分字段的摘录。API 金额与比率分子、分母都使用十进制整数字符串，
避免 JavaScript 的 Number 或其他客户端浮点类型损失整数精度。
Python 客户端可用 `int(value)`、`Fraction(int(numerator), int(denominator))` 继续精确计算。
未定义的比率返回 `null`；合法零比率返回 `{"numerator":"0","denominator":"1"}`。

测试覆盖 `9007199254740993` 和 `18446744073709551615` 的 HTTP 表达。
它们是合成边界输入，原有历史财报事实没有被替换成这些值。

## 如何防止查询时混入另一份数据

应用工厂先捕获数据包的全部文件，再核验捕获内容的哈希、来源选择、schema 与计算结果。
通过核验后才建立应用；核验失败时不会启动服务。
请求读取内存中的固定结果，不再重新读取外部数据包文件。
因此启动后修改或移走原目录，不会让一个分页请求突然混入另一批金额。

每个响应有 `X-StatementTrace-Snapshot` 头；分页数据也在 `snapshot` 中返回相同 ID 与截止日。
ID 是来源与产物哈希清单的 SHA-256，用来区分确切的数据包，不是数字签名或数据真实性证明。
多个应用可以同时服务不同截止日的数据，不共享全局结果缓存。

`as_of` 不是查询参数。传入 `?as_of=2025-02-04` 会收到 HTTP 422，防止调用者误以为
已经切换到另一份历史数据。未知参数和重复参数同样被拒绝。切换截止日的方式是：

```bash
uv run --locked statementtrace warehouse --as-of 2025-02-04 --out output/api-early
uv run --locked statementtrace serve-warehouse output/api-early --port 8001
```

在 8001 端口查询 GOOGL 时，两个财年的八个来源位置均保持 `missing_input`，
对应金额、申报日与来源 ID 返回 `null`。8000 端口的原应用仍保持原来的截止日。

## 实际验证

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/check_api.py output/api-demo
uv run --locked python scripts/check_warehouse_wheel.py
```

单元与接口测试覆盖金额精度、缺失值、来源身份、分页、并发请求、非法参数、
多应用隔离、源目录变化，以及重新计算哈希后的篡改拦截。
HTTP 脚本启动真实 Uvicorn 子进程，通过回环地址查询六个数据路由，检查文档入口及 422/405 返回。
wheel 检查会将包及其 API 依赖装入独立环境，在源码目录之外生成数据并启动真实服务。
Linux 与 Windows CI 都会执行这些步骤。

## 面试可以这样讲

“数据管道生成可核验的 Parquet 后，我增加了类型明确的只读 API。启动时捕获并核验整份数据包，
让分页和并发请求始终使用同一快照。金额跨 JSON 边界时用整数字符串，缺失和零明确区分。
调用方不能用一个未经支持的 as_of 参数假装切换截止日，还可以追到原始申报日、accession 和事实 ID。”

这仍是三家公司、24 个手工整理财报事实的本地研究服务。
没有生产部署、鉴权、多租户或吞吐量结果的主张。输入口径与财务解释见
[现金流研究简报](CASHFLOW_STUDY.zh-CN.md)。
