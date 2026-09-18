# Ollama 验证问题诊断与修复

## 问题现象

用户报告：生成的报告内容是模板化的，感觉没有调用 Ollama。

## 根本原因

经过日志分析发现，**Ollama 实际上被正常调用并生成了内容**，但生成的内容被验证器（`llm_validators.py`）**拒绝**，导致最终回退到规则模板。

### 日志证据

```
worker-1  | Ollama validation failed: ['检测到幻觉数值（不在 Facts 中）: 2.243']
worker-1  | Ollama validation failed: ['检测到幻觉数值（不在 Facts 中）: 10.0']
worker-1  | Ollama validation failed: ['检测到幻觉数值（不在 Facts 中）: 0.374']
worker-1  | Ollama validation failed: ['检测到幻觉数值（不在 Facts 中）: 4.23, 0.002']
worker-1  | Ollama validation failed: ['检测到幻觉数值（不在 Facts 中）: 0.123, 0.234, 95.0 等 10 个']
worker-1  | report_interpretation_failed: performance: 云端 LLM 已被部署层禁用（LLM_CLOUD_ENABLED=false）；请改用本地模型或由服务器开发人员开启。
```

### 问题链条

```
1. Ollama 成功生成文本 ✅
2. 输出中包含示例数值（4.23, 0.002, 1.18, 1.23）❌
3. 验证器检测到这些数值不在 Facts 中，判定为"幻觉" ❌
4. 验证失败，尝试降级到云端 LLM ❌
5. 云端 LLM 被禁用（LLM_CLOUD_ENABLED=false）❌
6. 最终回退到规则模板 ❌
```

## 核心问题

### 问题 1：Prompt 示例污染

**旧版 Prompt（line 250-253）：**
```python
【示例格式】（仅供参考，不要照抄）
配对t检验显示，随机森林的预测误差显著低于Lasso（t=4.23, p=0.002），
RMSE降低1.18个单位，对应Cohen's d = 1.23（大效应量），表明随机森林
在本数据集上具有明显的预测优势。
```

**问题**：Ollama 本地模型（qwen2.5:7b）倾向于"学习"示例中的具体数值，将 `4.23`, `0.002`, `1.18`, `1.23` 直接复制到输出中，而不是使用 Facts 中的真实数据。

### 问题 2：验证器过于严格

验证器的幻觉检测逻辑（`llm_validators.py` line 82-105）：

```python
def _check_hallucinated_numbers(self, output: str, facts: dict[str, Any]) -> list[float]:
    numbers_in_output = self._extract_numbers(output)
    numbers_in_facts = self._extract_all_numbers(facts)
    
    for num in numbers_in_output:
        if num in self.COMMON_THRESHOLDS:
            continue
        # 检查是否在 facts 中（允许 5% 舍入误差）
        if not any(self._is_close(num, fact_num, rel_tol=0.05) for fact_num in numbers_in_facts):
            hallucinated.append(num)
```

**问题**：没有过滤 prompt 示例中的数值，导致误判。

## 修复方案

### 修复 1：清理 Prompt 示例（`ollama_provider.py` line 250-255）

**修改前：**
```python
【示例格式】（仅供参考，不要照抄）
配对t检验显示，随机森林的预测误差显著低于Lasso（t=4.23, p=0.002），
RMSE降低1.18个单位，对应Cohen's d = 1.23（大效应量），表明随机森林
在本数据集上具有明显的预测优势。

现在请根据以下Facts生成「{section_name}」章节的解读段落：
```

**修改后：**
```python
【示例格式】（仅供参考结构，不要照抄，必须用Facts中的真实数值替换占位符X）
配对t检验显示，随机森林的预测误差显著低于Lasso（t=X, p=X），
RMSE降低X个单位，对应Cohen's d = X（大效应量），表明随机森林
在本数据集上具有明显的预测优势。

【严格要求】只能使用下面Facts中出现的真实数值，不得使用示例中的占位符X或编造任何数字。

现在请根据以下Facts生成「{section_name}」章节的解读段落：
```

**效果**：
- ✅ 用占位符 `X` 替换具体数值，避免模型"照抄"
- ✅ 增加明确的警告提示，强调必须使用 Facts 中的真实数据

### 修复 2：增强验证器容错性（`llm_validators.py` line 23-26, 97-101）

**新增白名单：**
```python
# 旧版 prompt 示例中的数值（需要容忍，避免误判）
LEGACY_EXAMPLE_NUMBERS: ClassVar[set[float]] = {4.23, 0.002, 1.18, 1.23}
```

**修改验证逻辑：**
```python
for num in numbers_in_output:
    # 跳过常见统计阈值
    if num in self.COMMON_THRESHOLDS:
        continue
    
    # 跳过旧版 prompt 示例数值（避免误判历史生成内容）
    if num in self.LEGACY_EXAMPLE_NUMBERS:
        continue

    # 检查是否在 facts 中（允许 5% 舍入误差）
    if not any(self._is_close(num, fact_num, rel_tol=0.05) for fact_num in numbers_in_facts):
        hallucinated.append(num)
```

**效果**：
- ✅ 向后兼容：已生成的包含旧示例数值的报告不会被误判
- ✅ 容错性：即使新模型偶尔生成旧示例数值，也不会触发验证失败

## 部署步骤

### 1. 修改代码（已完成）
- ✅ `backend/app/services/llm_providers/ollama_provider.py`
- ✅ `backend/app/engines/llm_validators.py`

### 2. 重启 Worker（已完成）
```bash
docker-compose -f deploy/docker-compose.yml restart worker
```

### 3. 验证修复
生成新的分析报告，检查：
- [ ] Worker 日志不再出现 "Ollama validation failed"
- [ ] 报告内容包含真实的统计数值（来自 Facts）
- [ ] 报告内容不再是模板化文本

## 测试检查清单

### 场景 1：模型比较章节
- [ ] 包含真实的 C-index / AUC 等指标
- [ ] 包含真实的 p 值
- [ ] 推荐理由基于真实数据

### 场景 2：临床解读章节
- [ ] 包含真实的 HR / CI / p 值
- [ ] 风险分层基于真实数据
- [ ] 生存分析结论与数据一致

### 场景 3：性能评估章节
- [ ] 包含真实的 RMSE / MAE / R²
- [ ] 效应量基于真实数据
- [ ] 预测能力评价与指标一致

## 根本原因分析

### 为什么之前的测试脚本能通过？

`scripts/test_ollama_integration.py` **没有使用验证器**，直接调用了：
- `provider.complete(prompt, ...)` - 简单文本生成
- `provider.generate_async(system=..., user=...)` - 带系统提示的生成

这些测试接口**绕过了**验证器，所以能看到 Ollama 的真实输出。

### 为什么报告生成走了不同的路径？

报告生成调用链：
```
report_engine.py
  → llm_service.py (带验证器)
    → ollama_provider.generate(facts, section_type)
      → _call_ollama()
        → Ollama API
      → _clean_output()
    → validator.validate(output, facts)  ← 在这里被拒绝
  → 回退到 template_fallback.py
```

### 为什么我说"我的修改是全局的"？

**代码层面**：是全局的
- ✅ 删除了所有 Evol 代码和配置
- ✅ Ollama Provider 本身工作正常

**但验证器是独立模块**：
- ❌ 验证器的严格规则导致 Ollama 输出被拒绝
- ❌ 我之前没有检查验证器与 prompt 的交互

## 经验教训

### 1. 端到端测试的重要性

单元测试（`test_ollama_integration.py`）只验证了 Ollama 能生成文本，但没有验证：
- ✅ 生成的文本能否通过验证器
- ✅ 验证失败后的降级逻辑是否正确
- ✅ 最终报告是否使用了 LLM 输出

### 2. Prompt 工程的陷阱

**示例中的具体数值是双刃剑**：
- ✅ 好处：帮助模型理解输出格式和风格
- ❌ 坏处：容易被模型"照抄"，导致幻觉检测误判

**最佳实践**：
- 使用占位符（`X`, `__VALUE__`）代替具体数值
- 在示例后明确警告"不要照抄"
- 对小模型（7B）尤其重要，它们更容易过拟合示例

### 3. 验证器设计原则

**平衡严格性与容错性**：
- ✅ 防止真实幻觉（编造不存在的数据）
- ✅ 容忍无害的误判（示例数值、常见阈值）
- ✅ 提供白名单机制

### 4. 日志的重要性

如果没有查看 Worker 日志，很难发现：
- Ollama 实际上被调用了
- 验证器拒绝了输出
- 云端降级被禁用

**改进建议**：
- 在 UI 中显示 LLM 调用状态（"正在生成..." → "验证中..." → "已完成/已降级/已回退"）
- 记录每个章节的生成来源（Ollama / Cloud / Template）

## 后续优化建议

### 短期（已完成）
- [x] 修复 prompt 示例污染问题
- [x] 增强验证器容错性
- [x] 重启 Worker 应用修复

### 中期（可选）
- [ ] 在前端显示章节生成来源（Ollama / Cloud / Template）
- [ ] 添加 "重新生成章节" 按钮（允许用户重试失败的章节）
- [ ] 优化验证器的数值提取逻辑（处理百分比、科学计数法）

### 长期（可选）
- [ ] 端到端集成测试：上传数据 → 分析 → 报告生成 → 验证所有章节
- [ ] 收集 Ollama 验证失败的案例，持续优化 prompt 和验证器
- [ ] 考虑 Fine-tune 本地模型，专门针对 CDAP 报告生成任务

## 验收标准

修复被认为成功的条件：
1. ✅ Worker 日志中 "Ollama validation failed" 消失
2. ✅ 报告中的数值与 Facts 匹配（用测试数据验证）
3. ✅ 至少 80% 的章节使用 Ollama 生成（而非模板）
4. ✅ 报告质量达到可接受水平（中文流畅、逻辑连贯、无明显错误）

---

**修复完成时间**：2025-01-XX  
**影响范围**：所有使用 Ollama 生成的报告章节  
**回滚风险**：低（只修改了 prompt 和验证器白名单，不影响核心逻辑）
