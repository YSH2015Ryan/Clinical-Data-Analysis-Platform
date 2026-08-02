# 性能压测报告（T8.3；docs/19 §6）

- 日期：2026-08-01 17:42:11
- 环境：Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.41；CPU 22 核；Python 3.11.15
- 数据：100000 行 × 50 列合成分类集（CSV 83.5MB，seed=42）
- 模型：logreg, rf, svm, xgboost, lightgbm, catboost；CV=3 折（eager 顺序执行 = 并行耗时上界）

## 阶段耗时

| 阶段 | 实测 | 目标 | 结论 |
|---|---|---|---|
| 数据校验 | 2.8s | ≤30s | PASS |
| 全链路（预处理+6 模型+比较） | 384.4s | ≤600s | PASS |
| PDF 报告生成 | 9.7s | ≤60s | PASS |
| Worker RSS | 1901MB | <2048MB | PASS |
| 上传落盘（84MB） | 0.46s | 异步不阻塞 | PASS |

## 每模型耗时

| 模型 | 状态 | 耗时 |
|---|---|---|
| logreg | SUCCESS | 5.8s |
| rf | SUCCESS | 25.0s |
| svm | SUCCESS | 251.4s |
| xgboost | SUCCESS | 83.4s |
| lightgbm | SUCCESS | 6.0s |
| catboost | SUCCESS | 9.5s |

运行状态：COMPLETED；报告状态：READY。
注：SVM 拟合/SHAP/permutation 已按 docs/07 §6.1 大样本保护子采样；指标在全量验证折计算。
