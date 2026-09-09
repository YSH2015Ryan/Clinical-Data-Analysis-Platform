# Ollama 服务器交接包（T6.15④）

> 面向服务器端开发人员。边界：**你只动部署层**（compose、.env、Ollama 服务本身）；
> 运行层的模型策略与开关由管理员在「AI 设置」界面调整，不要改代码硬编码。

## 1. 背景（为什么要部署）

2026-09-09 对线上报告 report-434b9064.html 的逐章解剖发现：正文 llm-paragraph
元素 0 个——Ollama 未部署，LLM 一次未调用成功，静默回退模板句式。
T6.15①-③ 已把模板加厚到「无 LLM 也可读」的底线（nan 守卫/红旗警示/指标
三段式），Ollama 部署后 LLM 在其上做数据特定的临床叙事增强（保上限）。

红线不变：绝不向云端发送行级患者数据，只发聚合统计 facts；LLM 输出经
幻觉数值校验（`app/services/llm_validators.py`），不合格自动回退模板。

## 2. 部署命令

```bash
cd deploy
# 1) 启动 Ollama（compose 已有 profile，无需改 yaml）
docker compose --profile llm up -d ollama

# 2) 拉取模型（默认 qwen2.5:7b，约 4.7GB）
docker compose exec ollama ollama pull qwen2.5:7b

# 3) 确认后端拿到的地址（.env 可不配，默认即 compose 内网地址）
#    OLLAMA_BASE_URL=http://ollama:11434   # compose 内服务名
#    OLLAMA_MODEL=qwen2.5:7b

# 4) 重启后端使配置生效
docker compose up -d api worker
```

内存水位：7b Q4 模型常驻约需 5–6GB。Ollama 与 worker 同机时注意 worker
容器内存配额（T6.5 采样保护阈值在 `config.py` 集中管理，可调）。
机器可用内存 <6GB 时不要部署，改用更小的 3b 模型并在「AI 设置」切换模型名。

## 3. 冒烟脚本（部署后必跑）

```bash
# 在服务器宿主机执行（仅需 Python 3.8+ 标准库）
python deploy/smoke_ollama.py --base-url http://localhost:11434 --model qwen2.5:7b
```

覆盖四项：连通性（/api/tags + 模型在册）、最小生成延迟、内存水位、
幻觉拦截演示指引。脚本输出 JSON 行并以退出码报告总结果（0=全过）。

容器内幻觉拦截与降级回退的自动化验证（在 deploy/ 目录执行）：

```bash
# 幻觉拦截：编造数值必须被拒（57 例联动套件）
docker compose exec api python -m pytest tests/test_llm_service.py \
  tests/test_llm_wiring.py tests/test_llm_settings.py -q

# 降级回退：停掉 Ollama 后报告仍应生成（模板+三段式兜底）
docker compose stop ollama
# → 触发一次报告生成，确认正文无 llm-paragraph 但三段式 .guide 块齐全
docker compose start ollama
```

## 4. 结果回传格式

把冒烟脚本输出原样贴回给本地开发侧（JSON 行即可），另附：

1. `docker compose exec api python -m pytest tests/test_llm_* -q` 的末行计数；
2. 一次真实 run 重出报告后，正文中 llm-paragraph 段落数（整改前为 0）；
3. `docker stats ollama --no-stream` 一行（内存水位实录）。

## 5. 验收标准（与路线图 T6.15 终验对齐）

- 同一 run 重出报告：llm-paragraph > 0，且无幻觉数值被拦截日志之外的
  编造数字进入正文；
- 停 Ollama 重出报告：报告仍完整生成（兜底链不断）；
- 临床读者盲读整改前后两份报告，能复述「能得出什么、不能得出什么」。
