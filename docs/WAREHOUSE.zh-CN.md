# 财报分析的列式数据管道

用同一份 Apple、Microsoft、Alphabet 历史财报案例，完成一条可以实际运行的
**Polars → Parquet → DuckDB → dbt** 分析流程。
它连接公开来源、日期口径、SQL 模型与核验结果，适合展示金融数据处理与研究实现能力。

## 每项技术解决什么问题

| 技术 | 本项目中的工作 | 代码入口 |
| --- | --- | --- |
| Polars LazyFrame | 按明确的 schema 扫描 NDJSON，将日期转为 Date、金额保持 Int64，写入列式文件 | [warehouse.py](../src/statementtrace/warehouse.py) |
| Parquet / Zstd | 保存来源事实和分析宽表，携带类型和缺失值 | `source_facts.parquet`、`cashflow.parquet` |
| DuckDB | 直接查询 Parquet，透视四项财务输入，以窗口函数计算相邻财年的增量 | [warehouse_cashflow.sql](../src/statementtrace/data/warehouse_cashflow.sql) |
| dbt Core / dbt-duckdb | 分层 SQL 模型、依赖关系、列类型契约和数据测试 | [warehouse_dbt](../warehouse_dbt) |
| uv | 用锁文件重建可选依赖，基础包仍可独立安装 | [uv.lock](../uv.lock) |
| GitHub Actions | 在 Linux、Windows 和安装后的 wheel 上运行验证 | [warehouse.yml](../.github/workflows/warehouse.yml) |

数据选择复用原有申报日和精确财年规则。Python、直接 DuckDB SQL、dbt SQL
分别计算选定事实的财务结果；三个路径仍共享原始案例和上游选择逻辑。
算术一致不能替代对原始年报抄录和事实可得性的检查。

## 一次运行

在仓库根目录执行；以下 `uv` 命令适用于 Linux、macOS 和 Windows PowerShell：

```bash
uv sync --locked --extra warehouse --extra dbt --extra dev
uv run --locked statementtrace warehouse --out output/warehouse
uv run --locked statementtrace verify-warehouse output/warehouse
uv run --locked python scripts/check_warehouse_dbt.py output/warehouse
```

默认案例截止日为 **2025-02-05**，共有 **24 个输入位置、6 个公司年度**。
直接 DuckDB 计算和 dbt 计算分别核对 **138 个字段**，包括身份、日期、金额、比率和增量。
dbt 验证脚本在临时目录真正构建 3 个模型并运行 21 项数据测试，再将一个输入的
申报日期改为截止日之后，要求 `filing_cutoff` 测试准确报告 1 条违规。
运行后的 dbt 临时数据库和日志自动清理。

只需要 Polars / DuckDB 时，也可以用 pip 安装：

```bash
python -m pip install -e '.[warehouse]'
python -m statementtrace warehouse --out output/warehouse-pip
python -m statementtrace verify-warehouse output/warehouse-pip
```

用 pip 安装不会使用 `uv.lock`。需要复现此仓库固定的完整技术栈时，使用上面的 uv 命令。
所有输出都应选择新的或空的目录；非空目录会被拒绝，避免覆盖已有研究。

## 看一次“未公开”的数据

```bash
uv run --locked statementtrace warehouse --as-of 2025-02-04 --out output/early
uv run --locked statementtrace verify-warehouse output/early
uv run --locked python scripts/check_warehouse_dbt.py output/early
```

这份历史数据包只收录 Alphabet 在 2025-02-05 申报的相关事实。
因此提前一天查看时，它的两个财年保留 8 个 `missing_input` 位置；金额、申报日和
来源身份均为空。模型不会把缺失转换为零，也不会从后一天借用已知数据。
Apple 和 Microsoft 仍按各自已收录事实计算。

使用自备、同一结构的公司案例：

```bash
uv run --locked statementtrace warehouse --case examples/cashflow/case.json --out output/custom
```

`--case` 接受保存的 cash-flow case JSON，默认使用内置三公司案例；
公司标识、申报、单位、财年和歧义规则继续由原引擎校验。

## 手动查看 dbt 依赖图与表

先在根目录生成 `output/warehouse`。以下命令进入 dbt 项目；默认路径相对此目录：

```bash
cd warehouse_dbt
uv run --project .. --locked dbt --no-send-anonymous-usage-stats build --profiles-dir .
uv run --project .. --locked dbt --no-send-anonymous-usage-stats docs generate --profiles-dir .
uv run --project .. --locked dbt --no-send-anonymous-usage-stats docs serve --profiles-dir .
```

默认数据库为 `output/research.duckdb`，与只读核验的数据包分开。
`STATEMENTTRACE_FACTS` 可指定其他来源 Parquet 的绝对路径；
`STATEMENTTRACE_DUCKDB` 可指定其他数据库文件。改变来源文件后，要重新 `dbt build`。
此项目不需要云账户、数据库服务或 DuckDB 扩展下载。
项目配置、验证脚本和这些手动命令均关闭 dbt 匿名使用统计。

dbt 的依赖顺序是：

1. `frozen_packet.source_facts`：带来源和截止日的 Parquet。
2. `stg_facts`：列类型契约及来源质量测试。
3. `int_annual_cashflow`：每个精确财年四项输入及 FCF。
4. `mart_cashflow`：相邻财年增量、现金流桥和比率的整数分子分母。

可在 DuckDB 中运行：

```sql
SELECT symbol, period, free_cash_flow, delta_cfo, negative_delta_capex,
       delta_fcf, bridge_residual
FROM mart_cashflow
ORDER BY symbol, start;
```

FY2024 手算期望，单位为美元：

| 公司 | FCF | ΔCFO | −Δ现金 capex | ΔFCF | 残差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 108,807,000,000 | 7,711,000,000 | 1,512,000,000 | 9,223,000,000 | 0 |
| MSFT | 74,071,000,000 | 30,966,000,000 | −16,370,000,000 | 14,596,000,000 | 0 |
| GOOGL | 72,764,000,000 | 23,553,000,000 | −20,284,000,000 | 3,269,000,000 | 0 |

## 产物与精度

| 文件 | 用途 |
| --- | --- |
| `case.json` / `request.json` | 保存原始案例及本次实际使用的截止日 |
| `source_facts.jsonl` | 保存选择后的来源行，包含缺失位置 |
| `source_facts.parquet` | Polars 生成的来源列式文件；Int64 金额、Date 日期 |
| `cashflow.sql` | 此次使用的 DuckDB SQL |
| `cashflow.parquet` | DuckDB 生成的分析表；金额和比率分子分母为 Decimal(38,0) |
| `analysis.json` | 可直接阅读的计算结果；比率化为精确分数 |
| `quality.json` | 来源质量违规数和 Python / DuckDB 核对结果 |
| `manifest.json` | 输入和产物的 SHA-256 以及工具版本 |

金额不经过浮点数，测试包括 **2⁵³ + 1**，以及两个合法 Int64 金额之差超出 Int64 的情况。
所以原始值用 Int64，计算前升级为 Decimal(38,0)。比率保留整数分子和分母，
不使用 DuckDB 的浮点除法作为精确结果。分母为零时两个字段均为空。

`verify-warehouse` 既检查哈希，也从 `case.json` 和截止日重新选择事实，
核对来源 Parquet 的类型和内容，重算 SQL，并核对保存的分析表。
修改数值或来源身份后即使更新哈希，仍无法通过语义核验。
Parquet 二进制字节可能随引擎版本变化；跨版本重建比较的是类型与精确数值。
哈希和重算用于内部一致性核验，不提供数字签名或源文件真实性证明。

## 可以怎样讲这个项目

“我把公开年报中的财务事实做成可复现的数据管道。Polars 按明确的整数和日期
schema 写入 Parquet，DuckDB 用 SQL 透视和窗口函数重算现金流，dbt 管理三层模型
及质量检查。提前截止日时，未申报的公司数据必须保持缺失；金额超过浮点精度边界时
也不能丢一美元。我用 Python 结果逐项核对，并主动构造未来申报日验证测试确实会失败。”

当前案例只有 24 个手工整理的公开事实，供研究和工程展示。
没有吞吐量、分布式计算、生产运维或实盘效果结论。
`scan_ndjson` 使用 lazy 执行，但上游 Python 仍会把输入案例载入内存。
财年窗口不同，仍应先比较各公司自身同比；完整财务解释见
[研究简报](CASHFLOW_STUDY.zh-CN.md)。

实现参考：[Polars lazy scan](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_ndjson.html)、
[DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview)、
[dbt 数据测试](https://docs.getdbt.com/docs/build/data-tests)、
[dbt-duckdb](https://github.com/duckdb/dbt-duckdb)。
