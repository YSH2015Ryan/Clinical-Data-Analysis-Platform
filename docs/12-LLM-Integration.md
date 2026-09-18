# 12.5 LLM 集成（LLM Integration）

## 1. 架构概览

CDAP 采用三层降级策略为用户提供智能增强功能：

```
本地 Ollama → 云端 LLM (OpenAI/Anthropic) → 规则模板兜底
```

- **本地优先**：免费、低延迟、数据不出网
- **云端降级**：本地不可用时自动切换到云端 API
- **规则兜底**：LLM 完全失败时使用内置模板，保证主流程不阻塞

## 2. 支持的提供商

### 2.1 本地提供商

#### Ollama
- **默认模型**：`qwen2.5:7b`
- **配置**：`OLLAMA_BASE_URL`（默认 `http://localhost:11434`）
- **优点**：完全免费、数据本地、低延迟
- **限制**：需单独安装 Ollama 服务

### 2.2 云端提供商

#### OpenAI
- **默认模型**：`gpt-4o-mini`
- **配置**：`OPENAI_API_KEY` + `CLOUD_PROVIDER=openai`
- **适用场景**：通用任务、稳定输出

#### Anthropic Claude
- **默认模型**：`claude-3-5-sonnet-20241022`
- **配置**：`ANTHROPIC_API_KEY` + `CLOUD_PROVIDER=anthropic`
- **适用场景**：复杂推理、长文本分析

## 3. 配置层级

### 3.1 部署层（环境变量）

```bash
# .env 或容器环境变量
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
CLOUD_PROVIDER=openai

# Anthropic（独立部署时）
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
CLOUD_PROVIDER=anthropic
```

### 3.2 运行层（数据库 admin_settings）

管理员可通过 Web UI（`/admin/settings/llm`）实时调整：

- **模型策略**：`local` / `cloud` / `auto`（本地优先）
- **云端提供商**：`openai` / `anthropic`
- **分功能开关**：每个 LLM 功能可独立配置：
  - `research_profile`：研究画像与设计建议
  - `report_interpretation`：报告解读段落
  - `validation_explain`：校验报错人话解释
  - `iteration`：对话式迭代建议
- **温度参数**：`0.0-1.0`（默认 `0.3`）

运行层配置优先级高于部署层，修改立即生效无需重启。

### 3.3 安全性

- API Key 使用 Fernet 对称加密存储在 `admin_settings` 表
- Web API 只接受写入（更新 key），读取时返回掩码 `sk-...****`
- 解密密钥来自环境变量 `ADMIN_SETTINGS_KEY`（部署时生成）

## 4. 功能开关

每个 LLM 功能支持 4 档配置：

| 值 | 含义 | 行为 |
|---|---|---|
| `off` | 关闭 | 不调用 LLM，直接使用规则模板 |
| `local` | 仅本地 | 只调用 Ollama，失败则回退模板 |
| `local_first` | 本地优先 | 先调 Ollama，失败则降级云端，云端也失败才回退模板 |
| `cloud` | 仅云端 | 只调用云端 API（OpenAI/Anthropic），失败则回退模板 |

## 5. 代码架构

### 5.1 目录结构

```
backend/app/services/
├── llm.py                      # LLMService 统一入口
├── llm_providers/
│   ├── base.py                 # LLMProvider 协议
│   ├── ollama_provider.py      # Ollama 本地实现
│   ├── openai_provider.py      # OpenAI 云端实现
│   └── anthropic_provider.py   # Anthropic 云端实现
└── settings.py                 # 运行层配置管理
```

### 5.2 降级逻辑

```python
# backend/app/services/llm.py
def generate_interpretation(self, run: AnalysisRun) -> str:
    switch = self.feature_switches.get("report_interpretation", "off")
    
    # 1. 检查功能开关
    if switch == "off":
        return self._fallback_template(run)
    
    # 2. 本地提供商
    if switch in ("local", "local_first"):
        if self.ollama and self.ollama.is_available():
            result = self.ollama.generate(...)
            if self._validate_output(result):
                return result
    
    # 3. 云端提供商（local_first 降级或 cloud 模式）
    if switch in ("local_first", "cloud"):
        cloud = self._get_cloud_provider()  # 根据 cloud_provider 返回 OpenAI/Anthropic
        if cloud and cloud.is_available():
            result = cloud.generate(...)
            if self._validate_output(result):
                return result
    
    # 4. 规则模板兜底
    return self._fallback_template(run)
```

### 5.3 幻觉校验

所有 LLM 输出经过质量校验（`backend/app/services/llm_validators.py`）：

- **中文占比**：≥70%（业务要求中文报告）
- **禁止编造数值**：通过 facts 白名单注入，提示词明确禁止生成未提供的数字
- **不合格回退**：校验失败自动回退规则模板

## 6. API 端点

### 6.1 查询配置状态
```http
GET /api/v1/admin/settings/llm
Authorization: Bearer {admin_token}
```

响应示例：
```json
{
  "config": {
    "model_choice": "auto",
    "ollama_model": "qwen2.5:7b",
    "cloud_provider": "anthropic",
    "openai_api_key_masked": "sk-...****",
    "anthropic_api_key_masked": "sk-ant-...****",
    "temperature": 0.3,
    "feature_switches": {
      "research_profile": "local_first",
      "report_interpretation": "local_first",
      "validation_explain": "off",
      "iteration": "cloud"
    }
  },
  "status": {
    "local": {
      "available": true,
      "model": "qwen2.5:7b"
    },
    "cloud": {
      "available": true,
      "provider": "anthropic",
      "model": "claude-3-5-sonnet-20241022"
    }
  }
}
```

### 6.2 更新配置
```http
PUT /api/v1/admin/settings/llm
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "cloud_provider": "anthropic",
  "anthropic_api_key": "sk-ant-api03-xxx",
  "temperature": 0.5,
  "feature_switches": {
    "report_interpretation": "cloud"
  }
}
```

### 6.3 连接测试
```http
POST /api/v1/admin/settings/llm/test
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "provider": "cloud"  // "local" 或 "cloud"
}
```

响应示例：
```json
{
  "ok": true,
  "provider": "anthropic",
  "model": "claude-3-5-sonnet-20241022",
  "latency_ms": 856
}
```

### 6.4 列出 Ollama 模型
```http
GET /api/v1/admin/settings/llm/ollama-models
Authorization: Bearer {admin_token}
```

响应示例：
```json
{
  "models": ["qwen2.5:7b", "llama3.1:8b"]
}
```

## 7. 部署建议

### 7.1 开发环境

```bash
# 1. 安装 Ollama（可选）
curl -fsSL https://ollama.com/install.sh | sh

# 2. 拉取模型
ollama pull qwen2.5:7b

# 3. 配置 .env
OLLAMA_BASE_URL=http://localhost:11434
ANTHROPIC_API_KEY=sk-ant-...  # 或使用 OpenAI
```

### 7.2 生产环境

**无 Ollama 部署**（仅云端）：
```bash
# docker-compose.yml 或 K8s ConfigMap
CLOUD_PROVIDER=anthropic
ANTHROPIC_API_KEY=${SECRET_ANTHROPIC_KEY}
```

**完整部署**（本地 + 云端）：
```bash
# 1. 单独部署 Ollama 服务器
# 2. 配置环境变量
OLLAMA_BASE_URL=http://ollama-server:11434
ANTHROPIC_API_KEY=${SECRET_ANTHROPIC_KEY}

# 3. 管理员登录 Web UI 调整运行层配置
```

## 8. 成本优化

| 场景 | 策略 | 月成本估算 |
|---|---|---|
| 纯本地 | `model_choice=local` | $0 |
| 混合（推荐） | `model_choice=auto` + `local_first` | $5-20（仅本地失败时用云端）|
| 纯云端 | `model_choice=cloud` + Anthropic | $50-200（中等使用量）|

**降本建议**：
- 开发/测试环境：纯本地
- 生产环境：混合模式（90% 请求走本地，10% 降级云端）
- 关闭不需要的功能开关（如 `validation_explain=off`）

## 9. 故障排查

### 9.1 本地 Ollama 不可用

**症状**：状态页显示"本地不可用"

**排查**：
```bash
# 1. 检查 Ollama 服务
curl http://localhost:11434/api/tags

# 2. 查看容器日志
docker compose logs api | grep -i ollama

# 3. 检查模型是否拉取
ollama list
```

### 9.2 云端 API 调用失败

**症状**：测试连接失败，显示 401/403

**排查**：
1. 确认 API Key 格式正确（OpenAI: `sk-...`, Anthropic: `sk-ant-...`）
2. 检查 Key 是否有效（登录提供商控制台验证）
3. 查看 admin_settings 表是否正确存储加密 Key
4. 检查网络连接（容器内能否访问 `api.openai.com` / `api.anthropic.com`）

### 9.3 LLM 输出校验失败

**症状**：频繁回退规则模板

**排查**：
```bash
# 查看校验日志
docker compose logs worker | grep "LLM validation failed"

# 常见原因：
# - 中文占比 <70%（调整温度或换模型）
# - 提示词质量问题（检查 prompts.py）
```

## 10. 未来扩展

- [ ] 支持更多云端提供商（Azure OpenAI、通义千问）
- [ ] Prompt 版本管理与 A/B 测试
- [ ] LLM 响应缓存（相同输入直接返回缓存结果）
- [ ] 成本监控与预算告警
- [ ] 用户级 LLM 配额管理

## 11. 相关文档

- [14-API-Specification.md §3.5](14-API-Specification.md) - LLM 配置 API 契约
- [10-Report-System.md §2](10-Report-System.md) - LLM 增强报告解读
- [08-Analysis-Workflow.md §3](08-Analysis-Workflow.md) - 对话式迭代
- [CLAUDE.md §8](../CLAUDE.md) - 红线 8：结果真实性要求
