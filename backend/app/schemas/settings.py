"""LLM 设置 schema（docs/14 /admin/settings/llm*；T6.6）。"""

from typing import Literal

from pydantic import BaseModel, Field

FeatureSwitch = Literal["off", "local", "local_first", "cloud"]
ModelChoice = Literal["auto", "local", "cloud"]


class LlmFeatureSwitches(BaseModel):
    research_profile: FeatureSwitch = "off"
    report_interpretation: FeatureSwitch = "off"
    validation_explain: FeatureSwitch = "off"
    iteration: FeatureSwitch = "off"  # T6.13 对话式迭代（重跑建议）


class LlmProviderStatus(BaseModel):
    available: bool
    provider: str | None = None
    model: str | None = None
    enabled: bool | None = None  # 仅 cloud：部署层总闸


class LlmStatus(BaseModel):
    local: LlmProviderStatus
    cloud: LlmProviderStatus
    default_choice: ModelChoice


class LlmConfigOut(BaseModel):
    """运行层生效配置（云端 key 只回显掩码，永不回明文——T6.6 红线）。"""

    model_choice: ModelChoice
    temperature: float
    ollama_model: str
    cloud_enabled: bool
    cloud_has_key: bool
    cloud_key_preview: str = ""
    feature_switches: LlmFeatureSwitches


class LlmSettingsOut(BaseModel):
    status: LlmStatus
    config: LlmConfigOut


class LlmSettingsUpdate(BaseModel):
    model_choice: ModelChoice | None = None
    temperature: float | None = Field(default=None, ge=0, le=1)
    ollama_model: str | None = Field(default=None, min_length=1, max_length=100)
    openai_api_key: str | None = Field(
        default=None, max_length=200, description="只写不读；空串清除；不传保持原值"
    )
    feature_switches: LlmFeatureSwitches | None = None


class LlmTestRequest(BaseModel):
    provider: Literal["local", "cloud"]


class LlmTestResult(BaseModel):
    ok: bool
    provider: str
    latency_ms: int
    detail: str = ""


class OllamaModelList(BaseModel):
    available: bool
    models: list[str]
