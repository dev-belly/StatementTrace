# 利润到现金，中间发生了什么？

[中文报告](https://dev-belly.github.io/StatementTrace/cashflow/profit-bridge/) · [English report](https://dev-belly.github.io/StatementTrace/cashflow/profit-bridge/en/) · [六个年度的计算结果](../examples/profit-bridge/bridge.csv) · [逐项来源](../examples/profit-bridge/sources.csv)

完成日期：2026-11-15。沿用原研究的 Apple、Microsoft、Alphabet FY2023/FY2024 及 **2025-02-05 申报日截止**，继续拆解原先只展示总额的经营现金流（CFO）。三家公司财年不同；Apple FY2023 为 53 周，未作周数调整。

## 先看 CFO 的增长来自哪里

单位：十亿美元；全部为各家公司自己的同比。

| FY2023 → FY2024 | 净利润增量 | 非现金及其他调节增量 | 经营资产负债变动的增量 | CFO 增量 | 勾稽差额 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Apple | -3.259 | +0.742 | +10.228 | +7.711 | 0 |
| Microsoft | +15.775 | +10.979 | +4.212 | +30.966 | 0 |
| Alphabet | +26.323 | +1.791 | -4.561 | +23.553 | 0 |

**Apple：** 净利润减少，CFO 仍增加。经营资产负债变动的同比贡献为 +10.228；其中应付账款一行贡献 +7.909，其他流动及非流动负债贡献 +12.521，被资产端等变化部分抵消。报表没有把这些合并行完整拆成业务与税务原因，不能将全部变化直接归因于某项税务裁决，也不能据此判断盈利质量改善。

**Microsoft：** 净利润增加不是 CFO 增长的全部来源。调节项增量中，“折旧、摊销及其他”贡献 +8.426；该行含“其他”，不能把全额称为纯折旧增量。经营资产负债变动中也包含长期资产、长期负债与所得税，不能统称为狭义营运资本释放。

**Alphabet：** 经营资产负债变动的同比影响为 -4.561，抵消了部分利润与调节项增长。再结合原研究的现金 capex 增量 20.284，解释为什么利润增长明显快于 FCF。这里只做报表金额的算术归因，没有估计投资回报或股票价值。

## 三种税款数字分开看

| FY2024 | 所得税费用 | 所得税净现金支付 | 披露精度 |
| --- | ---: | ---: | --- |
| Apple | 29.749 | 26.102 | 两项均披露至百万美元 |
| Microsoft | 19.651 | ≈23.4 | 税费至百万；现金支付至 1 亿美元 |
| Alphabet | 19.697 | ≈27.4 | 税费至百万；现金支付至 1 亿美元 |

税费、现金支付、递延税调节与税项资产负债变化分别保留。现金支付已经在 CFO 内，不能从 FCF 再扣一次；“税费减现金支付”也不是完整的 CFO 归因。

Apple 年报说明 FY2024 包含与欧盟 State Aid Decision 相关的约 10.2 十亿美元净税费。这个费用数不等于同年度同金额现金流出；此研究未把它机械加回利润，也未将全部其他负债变动视为该事项的现金贡献。

## 现金 capex、融资租赁和收购边界

保留原定义：**FCF = CFO − 现金 capex**。

| FY2024 | 现金 capex | 新增融资租赁资产（非现金） | 融资租赁本金现金支付 | 收购等投资现金支出 |
| --- | ---: | ---: | ---: | ---: |
| Apple | 9.447 | 未单独整理 | 未单独整理 | 未单独整理 |
| Microsoft | 44.477 | 11.633 | 1.286 | 69.132 |
| Alphabet | 52.535 | 0.313 | 0.405 | 2.931 |

- 新增融资租赁资产是非现金投入；不能作为当期现金支出从 FCF 扣除。
- 融资租赁利息已经计入 CFO；本金列于融资活动。报告另示 FCF 减本金的单独口径情景，不再扣利息。
- Microsoft 的 69.132 包含收购公司、无形及其他资产；Alphabet 的 2.931 包含收购与无形资产，均不能简称纯收购支出。
- Apple 摘录的投资活动 `Other` 为混合行；没有将它全部归为收购。租赁附注披露的使用权资产增加为合并口径，也没有擅自全部归为融资租赁。

Microsoft 的原始 FCF 为 74.071；单独扣除其报表收购等投资支出后为 **4.939**，单独扣融资租赁本金后为 **72.785**。两项展示各自从原始 FCF 出发，只说明口径差异，不是公司披露的标准 FCF，也不代表可以全部分配给股东的现金。

## 116 个选中值，8 个明确缺失

原研究仍保留 24 条总额事实。新增报告从其中选取 18 条净利润/CFO/capex 锚点，再补入 68 个经营现金流调节值和 30 个附注值，共 **116 个选中值**。另有 **8 个未单独整理的补充字段**，以空值和 `not_extracted` 保存。来源 CSV 共 124 行，包含来源表名、原文行名、中文说明、申报编号、披露日期、披露精度和身份哈希。

人工抄录来自同三份 FY2024 年报的两年比较列，不重建历史 API 版本。来源数据的整美元换算保持百万或 1 亿美元的原始披露精度；它不代表来源披露了精确到一美元的金额。

| 公司 | 原始申报 | 本轮核查位置 |
| --- | --- | --- |
| Apple | [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm) | 现金流量表；Note 7 税务；Note 8 租赁 |
| Microsoft | [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm) | 现金流量表；Note 12 税务；Note 13 租赁 |
| Alphabet | [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm) | 现金流量表；Note 4 租赁；Note 14 税务 |

Python 与 SQLite 从选中来源行分别计算六个年度的金额与同比桥，精确对照 **144 个字段**。任一完整 CFO 桥无法勾稽时拒绝发布；缺一条调节行时保留缺失，不用零凑平。两条路径只核对选中数据后的算术，不能独立认证抄录和分类。

## 离线复现和截止日反事实

在仓库根目录执行，需 Python 3.11+：

```bash
python -m pip install -e .
statementtrace profit-bridge --out output/profit-bridge
statementtrace verify-profit-bridge output/profit-bridge
```

直接打开 `output/profit-bridge/index.html`。页面不需要 JavaScript 或外部字体，五个下载文件嵌在 HTML 内。英文使用 `--language en`。

Windows 无需激活虚拟环境，可用 `.\.venv\Scripts\python.exe -m statementtrace` 替换 `statementtrace`。

```bash
statementtrace profit-bridge --as-of 2025-02-04 --out output/profit-bridge-earlier
statementtrace verify-profit-bridge output/profit-bridge-earlier
```

Alphabet 的比较数字在这个包中都来自 2025-02-05 申报文件，因此提前一天后变为缺失；这不表示现实中没有更早披露。采用 filed date 的日粒度规则，不声称重建了实际盘中可见时刻。

六文件数据包的全部金额、来源 CSV、SQL、分析 JSON 和 HTML 都会重建核验。它能发现单项变更及派生结果不一致，不能识别一份被整体一致替换的来源包；来源审阅仍是独立步骤。
