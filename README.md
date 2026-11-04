# Antigravity Pulse (`antigravity-pulse`)

> **Native Bottom-Bar Telemetry HUD for Google Antigravity 2.0**  
> 专为 **Google Antigravity 2.0** 打造的原生底栏遥测仪表盘：实时监测 **Token 生成速率 (TPS)**、**Prompt 缓存命中率**、**4 维上下文构成拆解** 与 **256K 自动压缩雷达**，1:1 遵循 Antigravity 官方 `Model / View Usage` 弹窗设计规范，并支持 **Minimal 极简模式 ⇄ Pro 详细模式** 一键热切换。

---

## ✨ 核心特性 (Key Features)

1. **1:1 原生视觉基因与全主题自适应**
   - 直接读取 Antigravity 渲染层 CSS 变量（`--card`、`--card-border`、`--foreground`、`--muted-foreground`、`--secondary`、`--editor-font-family` 等），无需任何手动配置即可无缝跟随 **Light 浅色**、**Dark 深色** 及各类第三方主题切换。
   - 弹窗视觉严格对齐 Antigravity 2.0 官方左下角 `Model / View Usage` 菜单风格（顶部次级小标题 Eyebrow、圆角浅灰药丸标签 Tag、`14×14` 环形进度指示器 `◔`）。
   - **零冗余干扰**：鉴于 Antigravity 2.0 官方已内置 `View Usage` 模型额度面板，`antigravity-pulse` 专注于官方未展示的底层会话遥测与上下文水位指标。

2. **双 UI 模式自由切换（`Minimal 极简模式` ⇄ `Pro 详细模式`）**
   - **切换方式**：
     - **方式一**：在底部栏任意遥测胶囊上 **点击鼠标右键** 即可秒级切换；
     - **方式二**：悬停或点击展开任意浮窗，点击右上角的 **`[极简 | 详细]`** 药丸按钮；
     - 模式偏好自动持久化保存在 `localStorage`（`agy_pulse_mode`）中。
   - **`Minimal` 极简模式**：
     - 底栏采用无框幽灵胶囊：`[ ⏱ 143 tok/s ]  [ 🛢 缓存命中 94% ]  [ ◔ 23% ]`
     - 浮窗展示清爽的双栏键值列表与 4 色上下文构成进度条。
   - **`Pro` 详细模式**：
     - 底栏展示完整步数与总量：`[ ⏱ 8 轮 237 步 · 143 tok/s ]  [ 🛢 10.6M tok · 缓存命中 94% ]  [ ◔ ~240K · 23% ]`
     - **会话统计浮窗**：新增三段式耗时分布条（`思考等待 TTFT` / `流式输出` / `工具调用`）与本轮/均值 TPS 对比。
     - **Token 用量浮窗**：新增缓存命中占比条、思考 Token 细分及会话等价 API 成本估算（`USD`）。
     - **上下文容量浮窗**：新增 **256K 自动压缩水位雷达**（精确显示距离触发 `CHECKPOINT` 自动压缩还剩多少 Token、本会话已自动压缩次数及 `14×14` 状态环）。

3. **零感后台常驻（Headless Sidecar）**
   - 利用 Antigravity 原生 `sidecar.json`（`"has_web_ui": false, "restart_policy": "always"`）随 IDE 启动而在后台静默运行，**不会在右侧弹出任何多余的 Webview 标签页**。

---

## 💡 常见问题：为什么模型上限是 1M，而自动压缩水位是 256K？

在 Antigravity 2.0 中，虽然底层模型（如 `Gemini 4 Argon` / `Gemini 2.5 Pro`）物理支持 **1M (`1,048,576`) Tokens** 的最大上下文窗口，但 Antigravity 引擎内部设定了 **256K (`256,000`) Tokens 的软性自动检查点水位线（Auto-Compaction Threshold）**：
- 当单次会话活跃上下文越过 `256K` 时，系统会自动触发一次 `CHECKPOINT` 历史摘要压缩，将早期冗长的工具输出折叠为高密度摘要：
  1. **防止 "Lost-in-the-Middle" 注意力衰减**，保持长程推理的代码准确率；
  2. **维持首字响应速度 (TTFT)**，避免每次请求重算几十万 Token 带来的延迟；
  3. **优化额度消耗**，将单步上下文稳定控制在最佳甜点区。
- 在 `Pro 详细模式` 的第三个胶囊弹窗底部，你可以实时查看当前会话距离 `256K` 自动压缩线还剩多少余量，以及本会话已经触发过几次自动压缩。

---

## 🚀 安装指南 (Installation)

### 方式一：直接克隆到 Antigravity 插件目录（推荐）

**Windows (PowerShell):**
```powershell
git clone https://github.com/hhanmj/antigravity-pulse.git "$env:USERPROFILE\.gemini\config\plugins\context-monitor"
```

**macOS / Linux:**
```bash
git clone https://github.com/hhanmj/antigravity-pulse.git ~/.gemini/config/plugins/context-monitor
```

### 方式二：克隆到任意目录后运行一键安装脚本

```powershell
git clone https://github.com/hhanmj/antigravity-pulse.git
cd antigravity-pulse
# Windows:
.\install.bat
# macOS / Linux:
chmod +x install.sh && ./install.sh
```

安装完成后，重启 Antigravity 2.0（或等待数秒热加载），聊天输入框底栏右侧即会自动浮现三枚原生遥测胶囊。

---

## 🖱️ 交互说明 (Usage)

| 操作 | 效果 |
| :--- | :--- |
| **鼠标悬停 (Hover)** 底栏胶囊 | 丝滑弹出对应维度的原生卡片浮窗（会话统计 / Token 用量 / 上下文容量） |
| **鼠标左键点击 (Left Click)** 底栏胶囊 | 固定（Pin）当前浮窗；再次点击或点击空白处关闭 |
| **鼠标右键点击 (Right Click)** 底栏胶囊 | 一键在 **`Minimal 极简模式`** 与 **`Pro 详细模式`** 之间切换 |
| **点击浮窗右上角 `[极简 \| 详细]`** | 同样可实时切换两套 UI 模式并自动记忆 |

---

## 📂 目录结构 (Project Structure)

```text
antigravity-pulse/
├── plugin.json                                    # Antigravity 插件清单
├── sidecars/
│   └── context-monitor/
│       └── sidecar.json                           # 无头后台守护配置 (has_web_ui: false)
├── skills/
│   └── context-monitor/
│       ├── SKILL.md                               # 对话按需查询 Skill 定义
│       └── scripts/
│           ├── generate_monitor.py                # 遥测与 4 维上下文精确计算引擎
│           └── daemon_sync.py                     # 原生底栏 HUD 注入与双模式渲染守护进程
├── install.bat / install.sh / uninstall.bat       # 跨平台一键安装与卸载脚本
├── LICENSE                                        # MIT 开源协议
└── README.md                                      # 中英双语说明文档
```

---

## 📄 License

[MIT License](./LICENSE) © 2026 hhanmj
