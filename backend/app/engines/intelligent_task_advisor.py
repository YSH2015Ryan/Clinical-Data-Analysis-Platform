"""智能任务类型顾问（基于 LLM）

功能：
1. 分析数据集适合做什么类型的分析
2. 推荐合适的目标列
3. 解释为什么某些分析不适合
4. 支持探索性分析（EDA）模式

Usage:
    advisor = IntelligentTaskAdvisor(llm_service)
    recommendation = advisor.analyze_dataset(df, column_profiles)
"""

from dataclasses import dataclass
from typing import Any
import pandas as pd
import json


@dataclass
class TaskRecommendation:
    """任务类型推荐结果"""
    
    # 推荐的分析类型
    recommended_tasks: list[str]  # ["regression", "classification", "eda"]
    
    # 推荐的目标列（如果适合预测建模）
    recommended_targets: list[dict[str, Any]]  # [{"column": "age", "reason": "...", "task_type": "regression"}]
    
    # 不适合的分析类型及原因
    unsuitable_tasks: dict[str, str]  # {"time_series": "缺少时间戳列"}
    
    # 探索性分析建议
    eda_suggestions: list[str]  # ["相关性分析", "聚类分析"]
    
    # 整体评估
    overall_assessment: str
    
    # 是否可以直接开始建模
    can_start_modeling: bool


class IntelligentTaskAdvisor:
    """智能任务顾问"""
    
    def __init__(self, llm_service: Any):
        self.llm = llm_service
    
    def analyze_dataset(
        self, 
        df: pd.DataFrame, 
        column_profiles: list[dict[str, Any]]
    ) -> TaskRecommendation:
        """分析数据集并给出任务推荐"""
        
        # 1. 构建数据集摘要
        summary = self._build_dataset_summary(df, column_profiles)
        
        # 2. 调用 LLM 分析
        prompt = self._build_analysis_prompt(summary)
        
        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response)
            
            return TaskRecommendation(
                recommended_tasks=result.get("recommended_tasks", ["eda"]),
                recommended_targets=result.get("recommended_targets", []),
                unsuitable_tasks=result.get("unsuitable_tasks", {}),
                eda_suggestions=result.get("eda_suggestions", []),
                overall_assessment=result.get("overall_assessment", ""),
                can_start_modeling=result.get("can_start_modeling", False)
            )
            
        except Exception as e:
            # LLM 失败时的兜底逻辑
            return self._fallback_analysis(df, column_profiles)
    
    def _build_dataset_summary(
        self, 
        df: pd.DataFrame, 
        column_profiles: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """构建数据集摘要"""
        
        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": [
                {
                    "name": col["name"],
                    "data_type": col.get("data_type", "unknown"),
                    "semantic_type": col.get("semantic_type", "unknown"),
                    "missing_rate": col.get("missing_count", 0) / len(df) if len(df) > 0 else 0,
                    "unique_count": col.get("unique_count", 0),
                    "sample_values": df[col["name"]].dropna().head(3).tolist() if col["name"] in df.columns else []
                }
                for col in column_profiles
            ],
            "has_time_column": any(
                col.get("semantic_type") in ["Date", "DateTime"] 
                for col in column_profiles
            ),
            "has_event_column": any(
                col.get("semantic_type") == "Event" 
                for col in column_profiles
            ),
            "has_label_column": any(
                col.get("semantic_type") == "Label" 
                for col in column_profiles
            )
        }
    
    def _build_analysis_prompt(self, summary: dict[str, Any]) -> str:
        """构建 LLM 分析提示"""
        
        columns_desc = "\n".join([
            f"- {col['name']}: {col['data_type']}, 缺失率 {col['missing_rate']:.1%}, "
            f"唯一值数 {col['unique_count']}, 示例: {col['sample_values']}"
            for col in summary["columns"]
        ])
        
        return f"""你是一个临床数据分析专家。请分析以下数据集，给出任务类型推荐。

数据集信息：
- 行数：{summary['row_count']}
- 列数：{summary['column_count']}
- 是否有时间列：{summary['has_time_column']}
- 是否有事件列：{summary['has_event_column']}
- 是否有标签列：{summary['has_label_column']}

列详情：
{columns_desc}

请分析：
1. 这个数据集适合做什么类型的分析？（分类/回归/生存分析/时间序列/探索性分析）
2. 如果适合预测建模，推荐哪些列作为目标列？为什么？
3. 哪些分析类型不适合？原因是什么？
4. 如果不适合预测建模，建议做哪些探索性分析？
5. 整体评估：数据质量如何？是否可以直接开始建模？

返回 JSON 格式：
{{
    "recommended_tasks": ["regression", "classification", "eda"],
    "recommended_targets": [
        {{
            "column": "列名",
            "reason": "推荐原因",
            "task_type": "regression/classification"
        }}
    ],
    "unsuitable_tasks": {{
        "time_series": "不适合原因",
        "survival": "不适合原因"
    }},
    "eda_suggestions": ["相关性分析", "聚类分析", "描述性统计"],
    "overall_assessment": "整体评估说明",
    "can_start_modeling": true/false
}}

注意：
- 如果没有明显的目标列，recommended_targets 可以为空，推荐 EDA
- 如果列名是 Unnamed: 0, Unnamed: 1 这种，说明列名缺失，需要提示用户补充
- 临床数据常见目标：疾病评分、是否复发、生存时间、治疗效果等
"""
    
    def _fallback_analysis(
        self, 
        df: pd.DataFrame, 
        column_profiles: list[dict[str, Any]]
    ) -> TaskRecommendation:
        """LLM 失败时的兜底逻辑"""
        
        # 简单规则判断
        has_label = any(col.get("semantic_type") == "Label" for col in column_profiles)
        has_event = any(col.get("semantic_type") == "Event" for col in column_profiles)
        
        if has_label or has_event:
            return TaskRecommendation(
                recommended_tasks=["classification", "regression"],
                recommended_targets=[],
                unsuitable_tasks={},
                eda_suggestions=[],
                overall_assessment="检测到可能的目标列，可以尝试预测建模",
                can_start_modeling=True
            )
        else:
            return TaskRecommendation(
                recommended_tasks=["eda"],
                recommended_targets=[],
                unsuitable_tasks={
                    "classification": "未找到明确的分类目标列",
                    "regression": "未找到明确的回归目标列"
                },
                eda_suggestions=[
                    "描述性统计分析",
                    "相关性分析",
                    "数据分布可视化"
                ],
                overall_assessment="未找到明确的预测目标，建议先进行探索性分析",
                can_start_modeling=False
            )
