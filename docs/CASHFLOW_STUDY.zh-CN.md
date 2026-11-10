# 利润增长，为什么没有变成同幅度的自由现金流增长？

**研究对象：Apple、Microsoft、Alphabet；各自 FY2023 与 FY2024。**
这是以 **2025-02-05** 为财报申报截止日的历史案例，整理日期为 2026-11-10。
三家公司的财年分别在 9 月、6 月和 12 月结束；先做各自同比，再讨论差异。
Apple FY2023 为 53 周，FY2024 为 52 周；本文使用报表原值，没有按周调整。

## 结论先行

Alphabet 的净利润增长 **35.67%**，但自由现金流只增长 **4.70%**。
经营现金流增加 235.53 亿美元，现金资本开支增加 202.84 亿美元，
两者相减，自由现金流只增加 32.69 亿美元。
这说明利润增长和资本投入后的现金余量需要分别分析。

| 各自 FY2024 | 净利润同比 | 自由现金流同比 | FCF / 收入 | 现金资本开支 / CFO |
| --- | ---: | ---: | ---: | ---: |
| Apple | -3.36% | 9.26% | 27.83% | 7.99% |
| Microsoft | 21.80% | 24.54% | 30.22% | 37.52% |
| Alphabet | 35.67% | 4.70% | 20.79% | 41.93% |

计算结果来自 [六个公司年度的明细](../examples/cashflow/comparison.csv)，
对应 [24 条选中原始事实](../examples/cashflow/source_facts.csv)。
比率的精确分数保存在 [analysis.json](../examples/cashflow/analysis.json)，表格按百分比保留两位小数。

## 把结论拆回金额

定义 **FCF = 经营现金流 CFO − 现金购置固定资产支出**。
capex 保存为正的流出金额。该口径不扣除收购支出，不包含非现金租赁增加额。

单位：十亿美元。以下是每家公司自己的同比，不是同期横截面排名。

| 公司 | FY2023 FCF | CFO 增量 | 现金 capex 影响（负号表示增加支出） | FY2024 FCF | 勾稽残差 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Apple | 99.584 | +7.711 | +1.512 | 108.807 | 0 |
| Microsoft | 59.475 | +30.966 | -16.370 | 74.071 | 0 |
| Alphabet | 69.495 | +23.553 | -20.284 | 72.764 | 0 |

**Apple：** 净利润下降与自由现金流上升同时存在。年报还披露了与欧盟税务裁决有关的
102 亿美元一次性所得税费用；应继续核对税务附注和支付时点，不能直接把 CFO / 净利润上升解释为经营质量改善。
来源：[Apple FY2024 10-K，所得税说明及现金流量表](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm)。

**Microsoft：** CFO 增量覆盖了现金 capex 增量，因此 FCF 增长。
这里的 FCF 没有扣除收购，也没有覆盖所有非现金资本投入；它不是可全部分配给股东的金额。
来源：[Microsoft FY2024 10-K，现金流量表](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm)。

**Alphabet：** 现金 capex 增量抵消了大部分 CFO 增量，FCF 利润率由 22.61% 降至 20.79%。
年报把固定资产购买增加主要联系到技术基础设施投入；这不能据此证明相关投资未来回报较差。
来源：[Alphabet FY2024 10-K，流动性讨论及现金流量表](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm)。

以上金额变化是算术归因；税务、基础设施及商业模式的进一步解释需要附注和分部信息。
三家公司也不构成一个有代表性的行业样本。

## 从数据到判断，具体做了什么

1. 从三份 FY2024 10-K 的比较列，手工整理两年收入、净利润、CFO、现金 capex，共 24 条事实。
2. 美元百万统一为整数美元；保留 CIK、会计概念、期间、申报日期、accession 和来源。
3. 复用 StatementTrace 的申报日和精确财年选择，不把后来的比较数据伪装成更早已知的数据。
4. Python 使用整数和精确分数计算六个年度；SQLite 从选中事实独立重算金额、比率和同比桥。
5. 输出完整 CSV、SQL、来源包和无需 JavaScript 的研究页面。保留缺失，不把不可见数据补成零。

[实现](../src/statementtrace/cashflow.py) · [SQL](../src/statementtrace/data/cashflow_compare.sql) ·
[离线来源包](../src/statementtrace/data/cashflow_case.json) · [财务预期与时间边界测试](../tests/test_cashflow.py)。

来源包是人工整理的 CompanyFacts 形状 JSON，并非原始 SEC API 响应。
SQLite 对照验证选中数据之后的算术，不独立认证抄录，也不独立重做事实选择。

## 五分钟复现与一个反事实

在仓库根目录安装 `python -m pip install -e .`，然后运行：

```bash
statementtrace compare --out output/cashflow
statementtrace verify-comparison output/cashflow
python -m http.server 8000 --directory output/cashflow
```

打开 `http://localhost:8000`，沿结果表、现金流增量图、原始事实和 SEC 来源检查。
安装包自带冻结来源与 SQL，不需要在线取数或 API 密钥。

把截止日提前一天：

```bash
statementtrace compare --as-of 2025-02-04 --out output/before-alphabet-filing
statementtrace verify-comparison output/before-alphabet-filing
```

Alphabet 两个年度均变为 `missing_input`：本包只收录 2025-02-05 申报文件中的比较数据。
这不表示 Alphabet FY2023 在现实中此前没有披露，而是这份来源包没有更早文件。
[SEC 申报索引](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/0001652044-25-000014-index.htm)
给出的 filed date 为 2 月 5 日，accepted 时间在 2 月 4 日晚间；项目始终采用前者的日粒度规则。

`verify-comparison` 从保存的来源包与截止日重建全部六个文件；它验证计算一致性，不能发现一份被整体、一致地替换的来源包。

## 下一步该查什么

若继续这项研究，应先拆分非现金调整、营运资本及税务支付，核对现金 capex 与融资租赁，
再加入分部收入和资本投入信息。估值和股票回报需要另外的价格、股份和资本成本数据。
当前结果只回答这个历史样本的现金流问题。
