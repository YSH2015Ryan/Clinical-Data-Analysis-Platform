/** ChartAsset → ECharts option（docs/09 §3 单数据源；T6.4 前端渲染）。

每种 kind 输出一个或多个面板（混淆矩阵/HR 森林按模型拆分）。
CI 区间用「透明底条 + 误差条」堆叠实现（避免 custom renderItem）。
 */

import type { EChartsOption, SeriesOption } from "echarts";
import type { TFunction } from "i18next";
import type { ChartAsset } from "./api";

export interface Panel {
  title: string;
  option: EChartsOption;
  height?: number;
}

function toolbox(t: TFunction) {
  return { feature: { saveAsImage: { title: t("charts.exportPng") } } };
}

interface Series {
  model_key: string;
  [k: string]: unknown;
}

function num(v: unknown): number {
  return typeof v === "number" ? v : Number(v);
}

function numArr(v: unknown): number[] {
  return Array.isArray(v) ? v.map(num) : [];
}

function seriesOf(data: Record<string, unknown>): Series[] {
  return (Array.isArray(data.series) ? data.series : []) as Series[];
}

function lineSeries(name: string, xs: number[], ys: number[], extra: Record<string, unknown> = {}) {
  return {
    name,
    type: "line",
    showSymbol: false,
    data: xs.map((x, i) => [x, ys[i]]),
    ...extra,
  } as SeriesOption;
}

function rocOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(
      `${s.model_key} (AUC=${s.auc != null ? num(s.auc).toFixed(3) : "—"})`,
      numArr(s.fpr),
      numArr(s.tpr),
    ),
  );
  series.push(lineSeries(t("charts.randomGuess"), [0, 1], [0, 1], { lineStyle: { type: "dashed" } }));
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: "FPR", min: 0, max: 1 },
    yAxis: { type: "value", name: "TPR", min: 0, max: 1 },
    series,
  };
}

function prCurveOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(
      `${s.model_key} (AUPRC=${s.auprc != null ? num(s.auprc).toFixed(3) : "—"})`,
      numArr(s.recall),
      numArr(s.precision),
    ),
  );
  const prevalence = typeof data.prevalence === "number" ? data.prevalence : null;
  if (prevalence != null) {
    series.push(
      lineSeries(
        t("charts.randomGuessPrevalence", { value: prevalence.toFixed(2) }),
        [0, 1],
        [prevalence, prevalence],
        { lineStyle: { type: "dashed" } },
      ),
    );
  }
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: t("charts.recall"), min: 0, max: 1 },
    yAxis: { type: "value", name: t("charts.precision"), min: 0, max: 1 },
    series,
  };
}

function calibrationOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(
      `${s.model_key} (Brier=${s.brier != null ? num(s.brier).toFixed(3) : "—"})`,
      numArr(s.prob_pred),
      numArr(s.prob_true),
      { showSymbol: true },
    ),
  );
  series.push(
    lineSeries(t("charts.idealCalibration"), [0, 1], [0, 1], { lineStyle: { type: "dashed" } }),
  );
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: t("charts.predictedProbability"), min: 0, max: 1 },
    yAxis: { type: "value", name: t("charts.actualFrequency"), min: 0, max: 1 },
    series,
  };
}

function dcaOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(String(s.model_key), numArr(s.thresholds), numArr(s.net_benefit)),
  );
  const treatAll = (data.treat_all ?? {}) as Record<string, unknown>;
  series.push(
    lineSeries(t("charts.treatAll"), numArr(treatAll.thresholds), numArr(treatAll.net_benefit), {
      lineStyle: { type: "dashed" },
    }),
  );
  series.push(
    lineSeries(t("charts.treatNone"), [0, 1], [0, 0], { lineStyle: { type: "dotted" } }),
  );
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: t("charts.thresholdProbability"), min: 0, max: 1 },
    yAxis: { type: "value", name: t("charts.netBenefit") },
    series,
  };
}

function confusionPanels(data: Record<string, unknown>, t: TFunction): Panel[] {
  const models = (Array.isArray(data.models) ? data.models : []) as Record<string, unknown>[];
  return models.map((m) => {
    const labels = (m.labels ?? []) as (string | number)[];
    const matrix = (m.matrix ?? []) as number[][];
    const cells: [number, number, number][] = [];
    let max = 0;
    matrix.forEach((row, i) =>
      row.forEach((v, j) => {
        cells.push([j, i, v]);
        max = Math.max(max, v);
      }),
    );
    return {
      title: `${m.model_key}`,
      height: 300,
      option: {
        tooltip: {},
        toolbox: toolbox(t),
        grid: { left: 80, bottom: 60 },
        xAxis: { type: "category", name: t("charts.predicted"), data: labels.map(String) },
        yAxis: {
          type: "category",
          name: t("charts.actual"),
          data: labels.map(String),
          inverse: true,
        },
        visualMap: {
          min: 0,
          max: Math.max(max, 1),
          calculable: true,
          orient: "horizontal",
          left: "center",
          inRange: { color: ["#f6f9ff", "#2f54eb"] },
        },
        series: [
          {
            type: "heatmap",
            data: cells,
            label: { show: true },
          },
        ],
      } as EChartsOption,
    };
  });
}

function kmOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(`${s.model_key}/${s.group}`, numArr(s.times), numArr(s.survival), {
      step: "end",
    }),
  );
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: t("charts.time") },
    yAxis: { type: "value", name: t("charts.survivalProbability"), min: 0, max: 1 },
    series,
  };
}

/** CI 森林图（cindex / HR 共用）：透明底条 + 误差条 + 中心散点。 */
function forestOption(
  categories: string[],
  lows: number[],
  highs: number[],
  points: number[],
  xName: string,
  logScale: boolean,
  t: TFunction,
): EChartsOption {
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }).dataIndex;
        return `${categories[i]}<br/>${xName}=${points[i].toFixed(4)}<br/>95% CI [${lows[i].toFixed(4)}, ${highs[i].toFixed(4)}]`;
      },
    },
    toolbox: toolbox(t),
    grid: { left: 100 },
    xAxis: { type: logScale ? "log" : "value", name: xName },
    yAxis: { type: "category", data: categories, inverse: true },
    series: [
      {
        type: "bar",
        stack: "ci",
        data: lows,
        itemStyle: { color: "transparent" },
        tooltip: { show: false },
        silent: true,
        barWidth: 4,
      },
      {
        type: "bar",
        stack: "ci",
        data: lows.map((l, i) => highs[i] - l),
        itemStyle: { color: "#91caff" },
        barWidth: 4,
      },
      {
        type: "scatter",
        data: points.map((v, i) => [v, categories[i]]),
        symbolSize: 10,
        itemStyle: { color: "#1677ff" },
        z: 10,
      },
    ],
  };
}

function cindexForestOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const rows = (Array.isArray(data.rows) ? data.rows : []) as Record<string, unknown>[];
  return forestOption(
    rows.map((r) => String(r.model_key)),
    rows.map((r) => num(r.ci_lower)),
    rows.map((r) => num(r.ci_upper)),
    rows.map((r) => num(r.c_index)),
    "C-index",
    false,
    t,
  );
}

function hrForestPanels(data: Record<string, unknown>, t: TFunction): Panel[] {
  const models = (Array.isArray(data.models) ? data.models : []) as Record<string, unknown>[];
  return models.map((m) => {
    const rows = (Array.isArray(m.rows) ? m.rows : []) as Record<string, unknown>[];
    const option = forestOption(
      rows.map((r) => String(r.feature)),
      rows.map((r) => num(r.ci_lower)),
      rows.map((r) => num(r.ci_upper)),
      rows.map((r) => num(r.hr)),
      "HR (log)",
      true,
      t,
    );
    const base = option.series;
    const baseSeries: SeriesOption[] = Array.isArray(base) ? base : base ? [base] : [];
    option.series = [
      ...baseSeries,
      {
        type: "scatter",
        data: [],
        markLine: {
          symbol: "none",
          lineStyle: { type: "dashed", color: "#999" },
          data: [{ xAxis: 1 }],
          label: { formatter: "HR=1" },
        },
      } as SeriesOption,
    ];
    return { title: `${m.model_key}`, height: Math.max(260, rows.length * 44 + 120), option };
  });
}

function featureImportanceOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const features = (Array.isArray(data.features) ? data.features : []).map(String);
  const series = seriesOf(data).map((s) => ({
    name: s.model_key,
    type: "bar",
    data: numArr(s.values),
  }));
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: toolbox(t),
    grid: { left: 120 },
    xAxis: { type: "value", name: t("charts.normalizedImportance"), max: 1 },
    yAxis: { type: "category", data: features, inverse: true },
    series: series as SeriesOption[],
  };
}

function scatterOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data);
  const all = series.flatMap((s) => [...numArr(s.y_true), ...numArr(s.y_pred)]);
  const lo = all.length ? Math.min(...all) : 0;
  const hi = all.length ? Math.max(...all) : 1;
  const lines: SeriesOption[] = series.map(
    (s) =>
      ({
        name: `${s.model_key} (RMSE=${s.rmse != null ? num(s.rmse).toFixed(3) : "—"})`,
        type: "scatter",
        data: numArr(s.y_true).map((y, i) => [y, numArr(s.y_pred)[i]]),
      }) as SeriesOption,
  );
  lines.push(
    lineSeries(t("charts.idealPrediction"), [lo, hi], [lo, hi], {
      lineStyle: { type: "dashed" },
    }),
  );
  return {
    tooltip: { trigger: "item" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: t("charts.trueValue"), min: lo, max: hi },
    yAxis: { type: "value", name: t("charts.predictedValue"), min: lo, max: hi },
    series: lines,
  };
}

/** P1-14（updateplan §44）：残差图（residual vs fitted）+ y=0 参考线。 */
function residualOption(data: Record<string, unknown>, t: TFunction): EChartsOption {
  const series = seriesOf(data);
  const lines: SeriesOption[] = series.map(
    (s) =>
      ({
        name: s.model_key,
        type: "scatter",
        data: numArr(s.fitted).map((f, i) => [f, numArr(s.residuals)[i]]),
      }) as SeriesOption,
  );
  const fittedAll = series.flatMap((s) => numArr(s.fitted));
  const lo = fittedAll.length ? Math.min(...fittedAll) : 0;
  const hi = fittedAll.length ? Math.max(...fittedAll) : 1;
  lines.push(
    lineSeries(t("charts.zeroReference"), [lo, hi], [0, 0], {
      lineStyle: { type: "dashed" },
    }),
  );
  return {
    tooltip: { trigger: "item" },
    legend: {},
    toolbox: toolbox(t),
    xAxis: { type: "value", name: t("charts.fittedValue") },
    yAxis: { type: "value", name: t("charts.residual") },
    series: lines,
  };
}

/** ChartAsset → 面板列表（多数 kind 单面板；混淆矩阵/HR 森林按模型拆分）。 */
export function buildPanels(chart: ChartAsset, t: TFunction): Panel[] {
  const d = chart.data;
  switch (chart.kind) {
    case "roc":
      return [{ title: chart.title, option: rocOption(d, t) }];
    case "pr_curve":
      return [{ title: chart.title, option: prCurveOption(d, t) }];
    case "calibration":
      return [{ title: chart.title, option: calibrationOption(d, t) }];
    case "dca":
      return [{ title: chart.title, option: dcaOption(d, t) }];
    case "confusion_matrix":
      return confusionPanels(d, t).map((p) => ({ ...p, title: `${chart.title} — ${p.title}` }));
    case "km":
      return [{ title: chart.title, option: kmOption(d, t), height: 420 }];
    case "cindex_forest":
      return [{ title: chart.title, option: cindexForestOption(d, t) }];
    case "hr_forest":
      return hrForestPanels(d, t).map((p) => ({ ...p, title: `${chart.title} — ${p.title}` }));
    case "feature_importance":
      return [{ title: chart.title, option: featureImportanceOption(d, t), height: 420 }];
    case "prediction_scatter":
      return [{ title: chart.title, option: scatterOption(d, t) }];
    case "residual_plot":
      return [{ title: chart.title, option: residualOption(d, t) }];
    default:
      return [];
  }
}
