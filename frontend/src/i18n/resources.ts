import adminEn from "./locales/en/admin.json";
import analysisEn from "./locales/en/analysis.json";
import authEn from "./locales/en/auth.json";
import chartsEn from "./locales/en/charts.json";
import commonEn from "./locales/en/common.json";
import comparisonEn from "./locales/en/comparison.json";
import datasetEn from "./locales/en/dataset.json";
import preparationEn from "./locales/en/preparation.json";
import projectsEn from "./locales/en/projects.json";
import reportsEn from "./locales/en/reports.json";
import runEn from "./locales/en/run.json";
import adminZhCN from "./locales/zh-CN/admin.json";
import analysisZhCN from "./locales/zh-CN/analysis.json";
import authZhCN from "./locales/zh-CN/auth.json";
import chartsZhCN from "./locales/zh-CN/charts.json";
import commonZhCN from "./locales/zh-CN/common.json";
import comparisonZhCN from "./locales/zh-CN/comparison.json";
import datasetZhCN from "./locales/zh-CN/dataset.json";
import preparationZhCN from "./locales/zh-CN/preparation.json";
import projectsZhCN from "./locales/zh-CN/projects.json";
import reportsZhCN from "./locales/zh-CN/reports.json";
import runZhCN from "./locales/zh-CN/run.json";

export const enResources = {
  common: commonEn,
  auth: authEn,
  projects: projectsEn,
  run: runEn,
  comparison: comparisonEn,
  reports: reportsEn,
  charts: chartsEn,
  admin: adminEn,
  dataset: datasetEn,
  preparation: preparationEn,
  analysis: analysisEn,
};
export const zhCNResources = {
  common: commonZhCN,
  auth: authZhCN,
  projects: projectsZhCN,
  run: runZhCN,
  comparison: comparisonZhCN,
  reports: reportsZhCN,
  charts: chartsZhCN,
  admin: adminZhCN,
  dataset: datasetZhCN,
  preparation: preparationZhCN,
  analysis: analysisZhCN,
};

export const resources = {
  "zh-CN": { translation: zhCNResources },
  en: { translation: enResources },
};
