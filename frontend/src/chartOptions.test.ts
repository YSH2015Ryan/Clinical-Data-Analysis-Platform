/** chartOptions 双语回归：中英文 t() 生成对应语言的图表标签（docs/19 图表要求）。 */

import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";
import i18n from "./i18n";
import type { ChartAsset } from "./api";
import { buildPanels } from "./chartOptions";

async function tFor(language: string): Promise<TFunction> {
  await i18n.changeLanguage(language);
  return i18n.t.bind(i18n);
}

const ROC_CHART: ChartAsset = {
  kind: "roc",
  title: "ROC",
  image_uri: null,
  data: {
    series: [{ model_key: "logistic", auc: 0.9, fpr: [0, 1], tpr: [0, 1] }],
  },
};

const KM_CHART: ChartAsset = {
  kind: "km",
  title: "KM",
  image_uri: null,
  data: {
    series: [{ model_key: "cox", group: "all", times: [0, 10], survival: [1, 0.5] }],
  },
};

const CONFUSION_CHART: ChartAsset = {
  kind: "confusion_matrix",
  title: "CM",
  image_uri: null,
  data: {
    models: [{ model_key: "rf", labels: [0, 1], matrix: [[8, 2], [1, 9]] }],
  },
};

interface AxisLike {
  name?: string;
}
interface SeriesLike {
  name?: string;
}

describe("buildPanels 双语标签", () => {
  it("中文模式生成中文标签", async () => {
    const t = await tFor("zh-CN");
    const roc = buildPanels(ROC_CHART, t)[0].option;
    const rocSeries = (roc.series ?? []) as SeriesLike[];
    expect(rocSeries.at(-1)?.name).toBe("随机猜测");
    expect((roc.toolbox as { feature: { saveAsImage: { title: string } } }).feature.saveAsImage.title).toBe(
      "导出 PNG",
    );

    const km = buildPanels(KM_CHART, t)[0].option;
    expect((km.xAxis as AxisLike).name).toBe("时间");
    expect((km.yAxis as AxisLike).name).toBe("生存概率");

    const cm = buildPanels(CONFUSION_CHART, t)[0].option;
    expect((cm.xAxis as AxisLike).name).toBe("预测");
    expect((cm.yAxis as AxisLike).name).toBe("实际");
  });

  it("英文模式生成英文标签", async () => {
    const t = await tFor("en");
    const roc = buildPanels(ROC_CHART, t)[0].option;
    const rocSeries = (roc.series ?? []) as SeriesLike[];
    expect(rocSeries.at(-1)?.name).toBe("Random guess");
    expect((roc.toolbox as { feature: { saveAsImage: { title: string } } }).feature.saveAsImage.title).toBe(
      "Export PNG",
    );

    const km = buildPanels(KM_CHART, t)[0].option;
    expect((km.xAxis as AxisLike).name).toBe("Time");
    expect((km.yAxis as AxisLike).name).toBe("Survival probability");

    const cm = buildPanels(CONFUSION_CHART, t)[0].option;
    expect((cm.xAxis as AxisLike).name).toBe("Predicted");
    expect((cm.yAxis as AxisLike).name).toBe("Actual");
  });

  it("后端 chart.title 与业务值不做翻译", async () => {
    const t = await tFor("en");
    const panels = buildPanels(ROC_CHART, t);
    const rocSeries = (panels[0].option.series ?? []) as SeriesLike[];
    expect(rocSeries[0]?.name).toContain("logistic");
    expect(rocSeries[0]?.name).toContain("AUC=0.900");
  });
});
