const api = new URL("../v1/", import.meta.url);
const amountFormat = new Intl.NumberFormat("en-US");
const metrics = [
  ["free_cash_flow", "自由现金流"],
  ["operating_cash_flow", "经营现金流"],
  ["capex", "资本开支"],
  ["revenue", "营业收入"],
  ["net_income", "净利润"],
];
const labels = new Map(metrics);
const byId = (id) => document.getElementById(id);
const companySelect = byId("symbol");
const periodSelect = byId("period");
const results = byId("results");
const status = byId("status");
const retry = byId("retry");
const cards = byId("metrics");
const factsBody = byId("facts");
const evidenceDescription = byId("evidence-description");
const allFacts = byId("all-facts");

let activeRequest;
let snapshot;
let issuers = [];
let facts = [];

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function money(value) {
  return value === null ? "缺失" : amountFormat.format(BigInt(value));
}

function fiscalLabel(label) {
  return /^\d{4}$/.test(label) ? "FY" + label : label;
}

function setStatus(state, message) {
  status.dataset.state = state;
  status.textContent = message;
  retry.hidden = state !== "error";
}

function begin(message) {
  activeRequest?.abort();
  activeRequest = new AbortController();
  results.hidden = true;
  setStatus("loading", message);
  return activeRequest;
}

async function fetchJSON(path, signal) {
  const response = await fetch(new URL(path, api), {
    signal,
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return {
    data: await response.json(),
    snapshotId: response.headers.get("X-StatementTrace-Snapshot"),
  };
}

function showSnapshotMismatch() {
  setStatus("error", "服务返回了不同的数据快照，请重新读取。");
}

function fillPeriods(preferred) {
  const issuer = issuers.find(({ symbol }) => symbol === companySelect.value);
  const periods = issuer?.periods ?? [];
  periodSelect.replaceChildren(...periods.map((period) => new Option(fiscalLabel(period), period)));
  periodSelect.value = periods.includes(preferred) ? preferred : periods.at(-1) ?? "";
  periodSelect.disabled = periods.length === 0;
}

function rememberSelection(symbol, period) {
  const url = new URL(window.location.href);
  url.searchParams.set("symbol", symbol);
  url.searchParams.set("period", period);
  window.history.replaceState(null, "", url);
}

function filingCell(fact) {
  const cell = element("td");
  let url;
  try {
    url = new URL(fact.source_url);
  } catch {
    // Missing facts have no source URL.
  }
  if (!url || !["https:", "http:"].includes(url.protocol)) {
    cell.textContent = fact.status === "missing_input" ? "截止日前无可用申报" : "无可用链接";
    cell.className = "missing";
    return cell;
  }
  const link = element("a", "查看原始申报");
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  cell.append(link);
  if (fact.accession) cell.append(element("small", fact.accession, "filing"));
  return cell;
}

function showFacts(metric) {
  const keys = metric === "free_cash_flow" ? ["operating_cash_flow", "capex"] : [metric];
  const shown = metric ? keys.flatMap((key) => facts.filter((fact) => fact.metric === key)) : facts;
  const rows = shown.map((fact) => {
    const row = element("tr");
    row.append(
      element("td", labels.get(fact.metric) ?? fact.metric),
      element("td", money(fact.value_usd), fact.value_usd === null ? "missing" : "money"),
      element("td", fact.filed ?? "—"),
      filingCell(fact),
    );
    return row;
  });
  if (!rows.length) {
    const empty = element("td", "该财年没有可展示的来源记录。", "empty");
    empty.colSpan = 4;
    const row = element("tr");
    row.append(empty);
    rows.push(row);
  }
  factsBody.replaceChildren(...rows);
  for (const row of rows) {
    row.setAttribute("role", "row");
    for (const cell of row.cells) cell.setAttribute("role", "cell");
  }
  allFacts.hidden = !metric;
  evidenceDescription.hidden = !metric;
  evidenceDescription.textContent = metric === "free_cash_flow"
    ? "自由现金流 = 经营现金流 − 资本开支"
    : labels.get(metric) ?? "";
  for (const button of cards.querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.metric === metric));
  }
}

function renderMetrics(amounts) {
  const buttons = metrics.map(([metric, label]) => {
    const button = element("button", undefined, metric === "free_cash_flow" ? "metric featured" : "metric");
    button.type = "button";
    button.dataset.metric = metric;
    button.setAttribute("aria-controls", "facts");
    const value = amounts[metric];
    button.append(element("span", label), element("strong", money(value), value === null ? "missing" : ""));
    button.addEventListener("click", () => {
      showFacts(metric);
      byId("evidence").scrollIntoView({ block: "nearest" });
    });
    return button;
  });
  cards.replaceChildren(...buttons);
}

async function showSelection() {
  const controller = begin("正在查询财报…");
  const { value: symbol } = companySelect;
  const { value: period } = periodSelect;
  if (!symbol || !period) {
    setStatus("empty", "没有可查询的公司或财年。");
    return;
  }
  const query = new URLSearchParams({ symbol, period });
  try {
    rememberSelection(symbol, period);
    const [cashflow, source] = await Promise.all([
      fetchJSON("cashflow?" + query, controller.signal),
      fetchJSON("facts?" + query, controller.signal),
    ]);
    if (activeRequest !== controller) return;
    if ([cashflow, source].some((page) =>
      page.snapshotId !== snapshot.snapshot_id || page.data.snapshot.snapshot_id !== snapshot.snapshot_id
    )) {
      showSnapshotMismatch();
      return;
    }
    const row = cashflow.data.items[0];
    if (!row) {
      setStatus("empty", "该公司与财年没有查询结果。");
      return;
    }
    facts = source.data.items;
    renderMetrics(row.amounts);
    showFacts();
    results.hidden = false;
    const dates = [row.symbol, fiscalLabel(row.period), row.start + " 至 " + row.end];
    if (row.status === "missing_input") dates.push("存在缺失金额");
    setStatus("ready", dates.join(" · "));
  } catch {
    if (activeRequest === controller) setStatus("error", "读取财报失败，请重新读取。");
  }
}

async function initialize() {
  const controller = begin("正在读取数据快照…");
  companySelect.disabled = true;
  periodSelect.disabled = true;
  byId("snapshot").hidden = true;
  try {
    const [metadata, catalog] = await Promise.all([
      fetchJSON("snapshot", controller.signal),
      fetchJSON("issuers", controller.signal),
    ]);
    if (activeRequest !== controller) return;
    snapshot = metadata.data;
    if (!snapshot.snapshot_id || [metadata, catalog].some((item) => item.snapshotId !== snapshot.snapshot_id)) {
      showSnapshotMismatch();
      return;
    }
    const cutoff = byId("cutoff");
    cutoff.dateTime = snapshot.as_of;
    cutoff.textContent = snapshot.as_of;
    byId("snapshot-id").textContent = snapshot.snapshot_id.slice(0, 8);
    byId("snapshot-id").title = snapshot.snapshot_id;
    byId("snapshot").hidden = false;

    issuers = catalog.data;
    if (!issuers.length) {
      setStatus("empty", "当前快照没有可浏览的公司。");
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const preferred = params.get("symbol");
    const match = issuers.find(({ symbol }) => symbol === preferred);
    companySelect.replaceChildren(...issuers.map(({ symbol }) => new Option(symbol, symbol)));
    companySelect.value = (match ?? issuers[0]).symbol;
    companySelect.disabled = false;
    fillPeriods(match ? params.get("period") : null);
    await showSelection();
  } catch {
    if (activeRequest === controller) setStatus("error", "读取快照失败，请重新读取。");
  }
}

companySelect.addEventListener("change", () => {
  fillPeriods(periodSelect.value);
  void showSelection();
});
periodSelect.addEventListener("change", showSelection);
allFacts.addEventListener("click", () => showFacts());
retry.addEventListener("click", initialize);
void initialize();
