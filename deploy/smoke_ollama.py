#!/usr/bin/env python3
"""Ollama 部署冒烟脚本（T6.15④；仅需 Python 3.8+ 标准库）。

用法：python deploy/smoke_ollama.py --base-url http://localhost:11434 --model qwen2.5:7b

四项检查，每项输出一行 JSON；任一失败退出码为 1：
1. connectivity —— /api/tags 可达且目标模型已拉取；
2. generation  —— 最小生成请求延迟（>30s 判失败，>10s 给 warn）；
3. memory      —— /proc/meminfo 可用内存水位（默认阈值 6GB，7b Q4 常驻约需 5-6GB）；
4. hallucination_guard —— 输出容器内幻觉拦截验证命令（拦截逻辑在后端，
   由 pytest 套件覆盖，本脚本不重复实现）。
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _emit(check: str, ok: bool, detail: str, **extra: object) -> bool:
    line = {"check": check, "ok": ok, "detail": detail, **extra}
    print(json.dumps(line, ensure_ascii=False))
    return ok


def check_connectivity(base_url: str, model: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return _emit("connectivity", False, f"连接失败：{type(exc).__name__}: {exc}")
    names = [str(m.get("name", "")) for m in payload.get("models", [])]
    if model in names:
        return _emit("connectivity", True, f"模型在册：{model}", models=names)
    return _emit(
        "connectivity",
        False,
        f"服务可达但模型未拉取：{model}（docker compose exec ollama ollama pull {model}）",
        models=names,
    )


def check_generation(base_url: str, model: str) -> bool:
    body = json.dumps(
        {"model": model, "prompt": "回复：ok", "stream": False, "options": {"num_predict": 4}}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ok_status = resp.status == 200
            resp.read()
    except (urllib.error.URLError, OSError) as exc:
        return _emit("generation", False, f"生成请求失败：{type(exc).__name__}: {exc}")
    latency_ms = int((time.monotonic() - started) * 1000)
    if not ok_status:
        return _emit("generation", False, "生成请求返回非 200", latency_ms=latency_ms)
    if latency_ms > 30000:
        return _emit("generation", False, "延迟超过 30s，不可用", latency_ms=latency_ms)
    level = "warn" if latency_ms > 10000 else "ok"
    return _emit(
        "generation",
        True,
        f"最小生成成功（{level}：延迟 {'偏高，注意并发' if level == 'warn' else '正常'}）",
        latency_ms=latency_ms,
    )


def check_memory(min_gb: float) -> bool:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    avail_gb = int(line.split()[1]) / 1024 / 1024
                    ok = avail_gb >= min_gb
                    return _emit(
                        "memory",
                        ok,
                        f"MemAvailable={avail_gb:.1f}GB（阈值 {min_gb}GB）"
                        + ("" if ok else "：不足，换更小模型或加内存"),
                        available_gb=round(avail_gb, 2),
                    )
    except OSError:
        pass
    return _emit("memory", True, "非 Linux 主机，跳过（请人工确认可用内存 ≥6GB）", skipped=True)


def check_hallucination_guard() -> bool:
    return _emit(
        "hallucination_guard",
        True,
        "幻觉拦截在后端实现（app/services/llm_validators.py），请在 deploy/ 目录执行："
        "docker compose exec api python -m pytest tests/test_llm_service.py "
        "tests/test_llm_wiring.py tests/test_llm_settings.py -q",
        manual_step=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ollama 部署冒烟（T6.15④）")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--min-mem-gb", type=float, default=6.0)
    args = parser.parse_args()

    results = [
        check_connectivity(args.base_url, args.model),
        check_generation(args.base_url, args.model),
        check_memory(args.min_mem_gb),
        check_hallucination_guard(),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
