---
name: context-monitor
description: Monitor conversation context window capacity, token usage, TPS speed, cache hit rate, and 256K auto-compaction watermark in Antigravity 2.0 (Antigravity Pulse). Use this skill whenever the user asks "查看上下文", "显示容量进度条", "token使用了多少", "会话容量状态", "context status", "check context", or wants to know if the session is nearing the compaction limit.
---

# Antigravity Pulse — Native Telemetry HUD & Context Monitor

Provides a real-time bottom-bar telemetry HUD inside Google Antigravity 2.0 (with `Minimal 极简模式` ⇄ `Pro 详细模式` dual-UI switching) and an on-demand CLI analyzer for chat reports.

## How to Run On-Demand CLI Report

Run `generate_monitor.py` and render its `markdown_report` field directly in your response:

```bash
python3 "$HOME/.gemini/config/plugins/context-monitor/skills/context-monitor/scripts/generate_monitor.py"
```
