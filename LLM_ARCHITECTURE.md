# CDAP LLM 架构说明

## 问题解答

### Q: 本地 Ollama 没有配置模型，系统如何生成报告解读？

**A: 系统采用多层降级策略，Ollama 不可用时会自动回退到规则模板，不会阻塞主流程。**

---

## 架构设计

### 1. 三层降级策略（docs/10 §2 + T6.7）

```
┌─────────────────────────────────────────────────┐
│ Layer 1: 本地 Ollama（优先）                     │
│  - 快速、免费、数据不出域                        │
│  - 失败 → Layer 2                               │
└─────────────────────────────────────────────────┘
                    ↓ 降级
┌─────────────────────────────────────────────────┐
│ Layer 2: 云端 OpenAI（可选）                     │
│  - 高质量输出                                    │
│  - 仅发送聚合统计（隐私守卫）                    │
│  - 失败 → Layer 3                               │
└─────────────────────────────────────────────────┘
                    ↓ 降级
┌─────────────────────────────────────────────────┐
│ Layer 3: 规则模板（兜底）                        │
│  - 统计学固定知识 + 真实计算指标                 │
│  - 100% 可用，不依赖 LLM                        │
└─────────────────────────────────────────────────┘
```

### 2. 当前部署状态

**检查结果**：
- ❌ **Ollama 容器未启动**（docker-compose.yml 中 `profiles: ["llm"]` 需显式启用）
- ✅ **OpenAI API Key 已配置**（可用云端降级）
- ✅ **规则模板引擎已就绪**（最终兜底）

**实际运行逻辑**：
```
1. 系统尝试连接 Ollama (http://host.docker.internal:11434)
2. 连接失败 → 记录警告日志
3. 尝试 OpenAI API (如果 LLM_CLOUD_ENABLED=true)
4. OpenAI 成功 → 生成 LLM 增强段落
5. OpenAI 失败 → 回退规则模板
```

---

## 核心代码路径

### 1. 降级控制器
**文件**: `backend/app/services/llm.py`

```python
class LLMService:
    def generate_interpretation(self, facts, section_type):
        # 优先本地
        if self.ollama:
            try:
                output = self.ollama.generate(...)
                if validate(output):
                    return output  # 成功
            except:
                pass  # 降级
        
        # 降级云端
        if self.openai:
            try:
                output = self.openai.generate(...)
                return output
            except:
                pass  # 继续降级
        
        # 最终回退：抛出异常，由调用方使用规则模板
        raise RuntimeError("All LLM providers failed")
```

### 2. 规则模板引擎
**文件**: `backend/app/engines/reporting/narratives.py`

**核心特性**：
- 统计学固定知识（AUC/C-index/RMSE 等指标含义）
- 通用判读规则（0.7/0.8/0.9 分档）
- 只引用真实计算指标（禁止幻觉数值）

**示例输出**：
```
AUC（ROC 曲线下面积）
含义：衡量模型区分阴性与阳性的能力。0.5 相当于随机猜测，1.0 为完美区分。
判读规则：≥0.9 优秀，0.8–0.9 良好，0.7–0.8 尚可，<0.7 欠佳。
本数据：模型 A 的 AUC 为 0.856（良好），模型 B 为 0.792（尚可）。
```

### 3. 报告生成流程
**文件**: `backend/app/workers/report_tasks.py`

```python
# L519-559: 报告解读段落生成
def generate_report_task(run_id):
    # 1. 收集真实指标
    facts = {
        "best_model": "lightgbm",
        "auc": 0.856,
        "c_index": 0.842,
        ...
    }
    
    # 2. 尝试 LLM 增强（T6.7）
    try:
        paragraphs = generate_report_interpretations(
            llm_service, facts, switch="local_first"
        )
    except:
        paragraphs = {}  # 降级
    
    # 3. 渲染报告（模板拼接）
    context = build_report_context(
        facts=facts,
        llm_paragraphs=paragraphs or {}  # 空 dict → 模板兜底
    )
    
    html = render_html(context)  # Jinja2 模板
```

---

## 功能开关（T6.7）

### 分功能策略（存储在数据库 `admin_settings` 表）

| 开关值 | 说明 | 行为 |
|--------|------|------|
| `off` | 关闭 LLM | 直接使用规则模板 |
| `local` | 仅本地 | Ollama 失败 → 报错（不降级） |
| `local_first` | 本地优先 | Ollama → OpenAI → 规则模板 |
| `cloud` | 仅云端 | 直接 OpenAI → 规则模板 |

### 三处业务应用

1. **研究画像增强** (`research_profile` 开关)
   - 规则引擎识别数据类型 → LLM 生成 2-3 个研究问题
   - 失败回退：只显示规则结论

2. **报告解读段落** (`report_interpretation` 开关)
   - 真实指标 → LLM 生成学术段落
   - 失败回退：使用 `narratives.py` 三段式模板

3. **校验报错解释** (`validation_explain` 开关)
   - Issue + 修复指引 → LLM 生成人话版解释
   - 失败回退：只显示结构化修复指引

---

## 隐私红线（T6.6）

### 云端 LLM 隐私守卫

**文件**: `backend/app/services/llm_privacy.py`

```python
def assert_cloud_payload_safe(facts: dict):
    """云端只允许聚合统计与列元数据，禁止行级患者数据"""
    
    # 禁止字段
    FORBIDDEN = {
        "raw_data", "patient_records", "rows",
        "X_train", "y_train", "features"
    }
    
    # 检测到行级数据 → 抛出异常，阻止发送
    for key in facts:
        if key in FORBIDDEN:
            raise ValueError(f"禁止将 {key} 发送到云端")
```

**允许发送的内容**：
- ✅ 列名、列类型、缺失率
- ✅ 模型性能指标（AUC/RMSE/HR）
- ✅ 特征重要性排序
- ✅ 聚合统计（均值/标准差）

**禁止发送的内容**：
- ❌ 原始数据行
- ❌ 患者 ID
- ❌ 训练集/测试集特征矩阵

---

## 如何启用 Ollama

### 方式一：启动容器（推荐）

```bash
cd deploy

# 1. 启动 Ollama 服务
docker compose --profile llm up -d ollama

# 2. 拉取模型（首次需要，约 4.7GB）
docker compose exec ollama ollama pull qwen2.5:7b

# 3. 验证模型
docker compose exec ollama ollama list
```

### 方式二：使用宿主机 Ollama

```bash
# 1. 本机安装 Ollama
# Windows: https://ollama.com/download

# 2. 拉取模型
ollama pull qwen2.5:7b

# 3. 确保服务运行在 11434 端口
# .env 中配置：
# OLLAMA_BASE_URL=http://host.docker.internal:11434
```

---

## 验证 LLM 是否生效

### 1. 检查日志

```bash
# API 日志
docker compose logs api | grep -i ollama

# 预期输出（成功）：
# INFO: Ollama provider initialized: qwen2.5:7b

# 预期输出（降级）：
# WARNING: Failed to initialize Ollama provider: Cannot connect to Ollama
```

### 2. 查看报告内容

**规则模板输出**（Ollama 不可用）：
```
AUC（ROC 曲线下面积）
含义：衡量模型区分阴性与阳性的能力...
判读规则：≥0.9 优秀，0.8–0.9 良好...
本数据：模型 A 的 AUC 为 0.856（良好）。
```

**LLM 增强输出**（Ollama 可用）：
```
本次分析中，LightGBM 模型表现最优，AUC 达到 0.856（良好），
显著优于 Logistic Regression 的 0.792（尚可）。该模型在预测
[目标] 方面展现出较强的区分能力，可作为临床决策参考的候选模型。
建议结合特征重要性分析与临床实际情况综合评估...
```

### 3. 查看数据库设置

```sql
-- 查询当前 LLM 配置
SELECT key, value FROM admin_settings 
WHERE key LIKE 'llm%' OR key LIKE 'feature.%';
```

---

## 性能影响

| 场景 | Ollama (本地) | OpenAI (云端) | 规则模板 |
|------|---------------|---------------|----------|
| 延迟 | 1-3 秒 | 3-8 秒 | <0.1 秒 |
| 成本 | 免费 | 按 token 计费 | 免费 |
| 质量 | 中等 | 高 | 基础可用 |
| 数据隐私 | 不出域 | 仅聚合统计 | 不出域 |

---

## 总结

### ✅ 当前实际情况

1. **Ollama 未启动** → 系统尝试连接失败
2. **OpenAI 已配置** → 自动降级到云端（如果 `LLM_CLOUD_ENABLED=true`）
3. **规则模板兜底** → 最终保证报告生成成功

### ✅ 设计理念

> **"LLM 是增强，不是依赖"**

- 所有数字来自真实计算（禁止幻觉）
- LLM 只做表达优化，不做结论生成
- 分功能开关独立控制，失败不阻塞主流程
- 规则模板保证最低可读性底线

### 📋 推荐配置

**开发/测试环境**：
```env
LLM_DEFAULT_CHOICE=local_first
LLM_CLOUD_ENABLED=false
# 启动 Ollama 容器测试本地推理
```

**生产环境**：
```env
LLM_DEFAULT_CHOICE=auto
LLM_CLOUD_ENABLED=false  # 或 true（允许云端降级）
# 生产流量大时建议启用 Ollama 节省成本
```

---

## 相关文档

- `docs/10-Report-Generation.md` - 报告生成规范
- `docs/18-Task-Breakdown.md` - T6.7 LLM 集成任务
- `backend/app/services/llm_tasks.py` - 三处业务接线
- `backend/app/engines/reporting/narratives.py` - 规则模板引擎
- `backend/app/services/llm_privacy.py` - 云端隐私守卫
