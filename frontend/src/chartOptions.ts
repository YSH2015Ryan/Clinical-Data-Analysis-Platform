/** ChartAsset → ECharts option（docs/09 §3 单数据源；T6.4 前端渲染）。

每种 kind 输出一个或多个面板（混淆矩阵/HR 森林按模型拆分）。
CI 区间用「透明底条 + 误差条」堆叠实现（避免 custom renderItem）。
 */

import type { EChartsOption, SeriesOption } from "echarts";
import type { ChartAsset } from "./api";

export interface Panel {
  title: string;
  option: EChartsOption;
  height?: number;
}

const TOOLBOX = { feature: { saveAsImage: { title: "导出 PNG" } } };

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

function rocOption(data: Record<string, unknown>): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(
      `${s.model_key} (AUC=${s.auc != null ? num(s.auc).toFixed(3) : "—"})`,
      numArr(s.fpr),
      numArr(s.tpr),
    ),
  );
  series.push(lineSeries("随机猜测", [0, 1], [0, 1], { lineStyle: { type: "dashed" } }));
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: TOOLBOX,
    xAxis: { type: "value", name: "FPR", min: 0, max: 1 },
    yAxis: { type: "value", name: "TPR", min: 0, max: 1 },
    series,
  };
}

function prCurveOption(data: Record<string, unknown>): EChartsOption {
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
      lineSeries(`随机猜测 (π=${prevalence.toFixed(2)})`, [0, 1], [prevalence, prevalence], {
        lineStyle: { type: "dashed" },
      }),
    );
  }
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: TOOLBOX,
    xAxis: { type: "value", name: "召回率", min: 0, max: 1 },
    yAxis: { type: "value", name: "精确率", min: 0, max: 1 },
    series,
  };
}

function calibrationOption(data: Record<string, unknown>): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(
      `${s.model_key} (Brier=${s.brier != null ? num(s.brier).toFixed(3) : "—"})`,
      numArr(s.prob_pred),
      numArr(s.prob_true),
      { showSymbol: true },
    ),
  );
  series.push(lineSeries("理想校准", [0, 1], [0, 1], { lineStyle: { type: "dashed" } }));
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: TOOLBOX,
    xAxis: { type: "value", name: "预测概率", min: 0, max: 1 },
    yAxis: { type: "value", name: "实际频率", min: 0, max: 1 },
    series,
  };
}

function dcaOption(data: Record<string, unknown>): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(String(s.model_key), numArr(s.thresholds), numArr(s.net_benefit)),
  );
  const treatAll = (data.treat_all ?? {}) as Record<string, unknown>;
  series.push(
    lineSeries("全部干预", numArr(treatAll.thresholds), numArr(treatAll.net_benefit), {
      lineStyle: { type: "dashed" },
    }),
  );
  series.push(
    lineSeries("均不干预", [0, 1], [0, 0], { lineStyle: { type: "dotted" } }),
  );
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: TOOLBOX,
    xAxis: { type: "value", name: "阈值概率", min: 0, max: 1 },
    yAxis: { type: "value", name: "净获益" },
    series,
  };
}

function confusionPanels(data: Record<string, unknown>): Panel[] {
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
        toolbox: TOOLBOX,
        grid: { left: 80, bottom: 60 },
        xAxis: { type: "category", name: "预测", data: labels.map(String) },
        yAxis: { type: "category", name: "实际", data: labels.map(String), inverse: true },
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

function kmOption(data: Record<string, unknown>): EChartsOption {
  const series = seriesOf(data).map((s) =>
    lineSeries(`${s.model_key}/${s.group}`, numArr(s.times), numArr(s.survival), {
      step: "end",
    }),
  );
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: TOOLBOX,
    xAxis: { type: "value", name: "时间" },
    yAxis: { type: "value", name: "生存概率", min: 0, max: 1 },
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
): EChartsOption {
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }).dataIndex;
        return `${categories[i]}<br/>${xName}=${points[i].toFixed(4)}<br/>95% CI [${lows[i].toFixed(4)}, ${highs[i].toFixed(4)}]`;
      },
    },
    toolbox: TOOLBOX,
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

function cindexForestOption(data: Record<string, unknown>): EChartsOption {
  const rows = (Array.isArray(data.rows) ? data.rows : []) as Record<string, unknown>[];
  return forestOption(
    rows.map((r) => String(r.model_key)),
    rows.map((r) => num(r.ci_lower)),
    rows.map((r) => num(r.ci_upper)),
    rows.map((r) => num(r.c_index)),
    "C-index",
    false,
  );
}

function hrForestPanels(data: Record<string, unknown>): Panel[] {
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

function featureImportanceOption(data: Record<string, unknown>): EChartsOption {
  const features = (Array.isArray(data.features) ? data.features : []).map(String);
  const series = seriesOf(data).map((s) => ({
    name: s.model_key,
    type: "bar",
    data: numArr(s.values),
  }));
  return {
    tooltip: { trigger: "axis" },
    legend: {},
    toolbox: TOOLBOX,
    grid: { left: 120 },
    xAxis: { type: "value", name: "归一化重要性", max: 1 },
    yAxis: { type: "category", data: features, inverse: true },
    series: series as SeriesOption[],
  };
}

function scatterOption(data: Record<string, unknown>): EChartsOption {
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
    lineSeries("理想预测", [lo, hi], [lo, hi], { lineStyle: { type: "dashed" } }),
  );
  return {
    tooltip: { trigger: "item" },
    legend: {},
    toolbox: TOOLBOX,
    xAxis: { type: "value", name: "真实值", min: lo, max: hi },
    yAxis: { type: "value", name: "预测值", min: lo, max: hi },
    series: lines,
  };
}

/** ChartAsset → 面板列表（多数 kind 单面板；混淆矩阵/HR 森林按模型拆分）。 */
export function buildPanels(chart: ChartAsset): Panel[] {
  const d = chart.data;
  switch (chart.kind) {
    case "roc":
      return [{ title: chart.title, option: rocOption(d) }];
    case "pr_curve":
      return [{ title: chart.title, option: prCurveOption(d) }];
    case "calibration":
      return [{ title: chart.title, option: calibrationOption(d) }];
    case "dca":
      return [{ title: chart.title, option: dcaOption(d) }];
    case "confusion_matrix":
      return confusionPanels(d).map((p) => ({ ...p, title: `${chart.title} — ${p.title}` }));
    case "km":
      return [{ title: chart.title, option: kmOption(d), height: 420 }];
    case "cindex_forest":
      return [{ title: chart.title, option: cindexForestOption(d) }];
    case "hr_forest":
      return hrForestPanels(d).map((p) => ({ ...p, title: `${chart.title} — ${p.title}` }));
    case "feature_importance":
      return [{ title: chart.title, option: featureImportanceOption(d), height: 420 }];
    case "prediction_scatter":
      return [{ title: chart.title, option: scatterOption(d) }];
    default:
      return [];
  }
}
