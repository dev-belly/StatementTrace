# StatementTrace｜把利润增长拆回现金流

[English](README.md) · [直接读中文报告](https://dev-belly.github.io/StatementTrace/cashflow/zh/) · [研究解释](docs/CASHFLOW_STUDY.zh-CN.md)

**利润涨了，扣除资本开支后，现金也增长了吗？**

从 Apple、Microsoft、Alphabet 的公开年报中整理 24 条事实，比较 2023–2024 财年的六个公司年度。每个结果都可以追到原始申报、准确财年区间、计算公式与 SQL。

| 2024 财年同比 | 净利润 | 自由现金流 |
| --- | ---: | ---: |
| Apple | -3.36% | 9.26% |
| Alphabet | 35.67% | 4.70% |
| Microsoft | 21.80% | 24.54% |

以 Alphabet 为例：经营现金流增加 235.53 亿美元，但现金资本开支增加 202.84 亿美元，自由现金流只增加 32.69 亿美元。报告把这两个贡献逐项拆开。

这是申报日截止 **2025-02-05** 的历史案例；三家公司的财年窗口不同，Apple 的 2023 财年有 53 周。同比按各自实际财年计算，没有周数标准化。统一口径为 **FCF = CFO − 现金资本开支**。

## 先生成一份能核验的中文报告

需要 Python 3.11+，安装时可联网获取构建依赖。以下命令从仓库根目录运行。

```bash
python -m pip install .
statementtrace compare --language zh-CN --out output/cashflow-zh
statementtrace verify-comparison output/cashflow-zh
```

直接打开 `output/cashflow-zh/index.html`。中文页面包含结果、增量归因、金额、来源、术语说明和五个内嵌下载；断网、禁用 JavaScript 时也能阅读和下载。系统字体回退覆盖 Windows、macOS 和 Linux，无需字体 CDN。手机上可以横向滚动金额表；浏览器“打印”可保存报告。

**试一个有意义的反例：** 在新输出目录中加上 `--as-of 2025-02-04`，Alphabet 的数据会显示“数据不可得”，不会被填成零。这个数据包没有收录它更早的申报。

`--language en` 生成英文。语言只改变页面文字和记录的展示语言；CSV、SQL、来源数据包与财务计算一致。核验命令会按保存的语言重新计算 HTML，修改中文页面的数字也会核验失败。输出目录必须为空，防止覆盖已有研究。

## 从一份研究继续读实现

| 关注点 | 实际实现 | 入口 |
| --- | --- | --- |
| 财报事实选择 | 申报日截止、准确财年、修订冲突、缺失状态 | [选择引擎](src/statementtrace/engine.py) |
| 现金流归因 | 整数金额、精确分数、相邻财年增量与差额勾稽 | [Python](src/statementtrace/cashflow.py) · [SQL](src/statementtrace/data/cashflow_compare.sql) |
| 数据工程 | Polars → Parquet → DuckDB → dbt；每条 SQL 路径对照 Python 核验 138 个字段 | [中文管道说明](docs/WAREHOUSE.zh-CN.md) |
| 程序调用 | FastAPI / Pydantic；六个只读接口、分页与同一快照标识 | [中文 API 指南](docs/API.zh-CN.md) |
| 来源审阅 | 24 项金额、概念、申报编号与原网页 | [来源 CSV](examples/cashflow/source_facts.csv) |

金额的页面显示经过舍入；CSV 保留整数，JSON 保留精确分数。Excel 导入 CSV 时请选择 UTF-8；精确标识与计算依据以来源 JSON 为准。

Python 与 SQL 一致能支持算术核对；它们使用相同的人工整理来源，不能独立证明抄录准确、历史首次可得性或估值结论。工程演示没有测量生产吞吐。

[完整英文技术文档](README.md) · [CI](https://github.com/dev-belly/StatementTrace/actions) · [MIT 许可证](LICENSE)
