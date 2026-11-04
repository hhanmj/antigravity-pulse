#!/usr/bin/env python3
"""
Antigravity Pulse — Native Telemetry HUD Daemon (v3.1)
- Zero redundant Quota UI (Antigravity 2.0 provides official 'View Usage')
- 1:1 Visual Alignment with Antigravity's Native 'Model / View Usage' Popover Style
- Dual-UI Mode Switcher: Minimal (极简模式) ⇄ Pro (详细模式)
  - Click the [极简 | 详细] toggle button in the top-right of any popover
  - OR right-click any bottom pill
  - Saved in localStorage ('agy_pulse_mode')
- Automatic Light / Dark / Custom Theme Adaptation via Antigravity CSS Tokens
"""

import os
import sys
import json
import time
import socket
import base64
import struct
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
import generate_monitor

# Single-instance lock on localhost:38291
LOCK_PORT = 38291
_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _lock_socket.bind(("127.0.0.1", LOCK_PORT))
except OSError:
    sys.exit(0)


def save_ls_env(status: str = "init", error: str = ""):
    """Persist live Antigravity Language Server address and CSRF token for standalone CLI queries."""
    addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "")
    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")
    env_file = PLUGIN_ROOT / ".ls_env.json"
    try:
        existing = {}
        if env_file.exists():
            try:
                existing = json.loads(env_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        payload = {
            "address": addr or existing.get("address", ""),
            "csrf": csrf or existing.get("csrf", ""),
            "pulse_version": "3.4",
            "status": status,
            "error": error,
            "updated_at": time.strftime("%H:%M:%S"),
        }
        env_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


class SimpleWebSocket:
    def __init__(self, ws_url: str):
        without_scheme = ws_url.replace("ws://", "")
        host_port, self.path = without_scheme.split("/", 1)
        self.path = "/" + self.path
        self.host, port_str = host_port.split(":")
        self.port = int(port_str)
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed early")
            resp += chunk

    def send_text(self, text: str):
        payload = text.encode("utf-8")
        length = len(payload)
        header = bytearray([0x81])
        mask_key = os.urandom(4)
        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))
        self.sock.sendall(header + masked)

    def recv_text(self) -> str:
        header = self.sock.recv(2)
        if len(header) < 2:
            raise ConnectionError("Short read on WS header")
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.sock.recv(8))[0]
        masked = (header[1] & 0x80) != 0
        mask_key = self.sock.recv(4) if masked else None
        payload = bytearray()
        while len(payload) < length:
            chunk = self.sock.recv(length - len(payload))
            if not chunk:
                raise ConnectionError("Short read on WS payload")
            payload.extend(chunk)
        if masked and mask_key:
            for i in range(length):
                payload[i] ^= mask_key[i % 4]
        return payload.decode("utf-8", errors="replace")

    def eval_js(self, expression: str, msg_id: int = 1, session_id: str = ""):
        req = {
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }
        if session_id:
            req["sessionId"] = session_id
        self.send_text(json.dumps(req))
        while True:
            resp = json.loads(self.recv_text())
            if resp.get("id") == msg_id:
                return resp

    def call_cdp(
        self, method: str, params: dict = None, msg_id: int = 1, session_id: str = ""
    ):
        req = {"id": msg_id, "method": method}
        if params:
            req["params"] = params
        if session_id:
            req["sessionId"] = session_id
        self.send_text(json.dumps(req))
        while True:
            resp = json.loads(self.recv_text())
            if resp.get("id") == msg_id:
                return resp

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


SETUP_JS = r"""
(() => {
    window.__AGY_PULSE_VERSION = '3.7';

    // 1. Clean up and neutralize any legacy v1/v2 ('dsh-*' / 'antigravity-context-gauge-*') DOM elements, styles, and intervals
    const cleanupLegacy = () => {
        if (window.__agyGaugeObserver && typeof window.__agyGaugeObserver.disconnect === 'function') {
            try { window.__agyGaugeObserver.disconnect(); } catch (_) {}
        }
        document.querySelectorAll(
            '#antigravity-context-gauge-style, .dsh-stat-popover, [id^="dsh-"]'
        ).forEach(el => el.remove());
        const oldRoot = document.getElementById('antigravity-context-gauge-root');
        if (oldRoot) {
            oldRoot.className = '';
            oldRoot.innerHTML = '';
            oldRoot.style.cssText = 'display:none !important; width:0 !important; height:0 !important; overflow:hidden !important; position:absolute !important; pointer-events:none !important;';
        }
        document.querySelectorAll('style').forEach(st => {
            if (st.id !== 'agy-ctx-hud-style' && /dsh-dock-bar|antigravity-context-gauge|dsh-stat-popover/.test(st.textContent || '')) {
                st.remove();
            }
        });
    };
    cleanupLegacy();

    // 2. Always remove old v3 style AND old v3 DOM container so hot-reload cleanly re-binds all events
    const oldStyle = document.getElementById('agy-ctx-hud-style');
    if (oldStyle) oldStyle.remove();
    const oldGauge = document.getElementById('agy-ctx-gauge');
    if (oldGauge) oldGauge.remove();

    const style = document.createElement('style');
    style.id = 'agy-ctx-hud-style';
    style.textContent = `
        #agy-ctx-gauge {
            --hud-bg: color-mix(in srgb, var(--popover, var(--card, #18181b)) 96%, var(--background, #09090b));
            --hud-well: var(--secondary, var(--onyx-well, rgba(128, 128, 128, 0.12)));
            --hud-border: var(--card-border, var(--border, rgba(128, 128, 128, 0.22)));
            --hud-fg: var(--foreground, #f4f4f5);
            --hud-fg-sec: var(--secondary-foreground, #d4d4d8);
            --hud-muted: var(--muted-foreground, #a1a1aa);
            --hud-hover-bg: var(--secondary, rgba(128, 128, 128, 0.14));
            --hud-font: var(--editor-font-family, 'JetBrains Mono', Consolas, monospace);

            --c-blue: var(--chart-blue, #3b82f6);
            --c-purple: var(--chart-purple, #8b5cf6);
            --c-green: var(--chart-green, #10b981);
            --c-amber: var(--chart-orange, #f59e0b);
            --c-rose: #ef4444;

            position: relative;
            display: inline-flex;
            align-items: center;
            flex-wrap: nowrap;
            flex-shrink: 0;
            gap: 2px;
            margin-left: auto;
            margin-right: 6px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            user-select: none;
            z-index: 999;
        }

        /* Bottom Bar Pills */
        .agy-hud-pill {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            height: 22px;
            padding: 0 6px;
            border-radius: 6px;
            border: 1px solid transparent;
            background: transparent;
            color: var(--hud-muted);
            font-size: 11.5px;
            font-weight: 500;
            line-height: 1;
            cursor: pointer;
            transition: all 0.14s ease;
            white-space: nowrap;
        }
        #agy-ctx-gauge[data-mode="pro"] .agy-hud-pill {
            background: color-mix(in srgb, var(--hud-well) 50%, transparent);
            padding: 0 5.5px;
        }
        .agy-hud-pill:hover,
        .agy-hud-pill.active {
            background: var(--hud-hover-bg) !important;
            border-color: var(--hud-border);
            color: var(--hud-fg);
        }
        .agy-hud-pill svg {
            flex-shrink: 0;
            opacity: 0.88;
        }
        .agy-hud-pill .sep {
            opacity: 0.45;
            margin: 0 0.5px;
        }
        .agy-hud-pill .mono-val {
            font-family: var(--hud-font);
            font-size: 11px;
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.02em;
        }

        /* Native Antigravity Menu Popover Card (1:1 aligned with 'Model / View Usage') */
        .agy-hud-popover {
            position: absolute;
            bottom: calc(100% + 8px);
            right: 0;
            width: 296px;
            padding: 12px 14px;
            border-radius: 10px;
            background-color: var(--background, #141416);
            background-image: linear-gradient(var(--hud-bg), var(--hud-bg));
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--hud-border);
            box-shadow: 0 12px 32px -4px rgba(0, 0, 0, 0.36), 0 4px 12px -2px rgba(0, 0, 0, 0.18);
            color: var(--hud-fg);
            opacity: 0;
            visibility: hidden;
            transform: translateY(4px) scale(0.985);
            transform-origin: bottom right;
            transition: opacity 0.14s ease, transform 0.14s ease, visibility 0.14s;
            pointer-events: none;
            z-index: 99999;
        }
        #agy-ctx-gauge.open .agy-hud-popover {
            opacity: 1;
            visibility: visible;
            transform: translateY(0) scale(1);
            pointer-events: auto;
        }

        .agy-hud-panel {
            display: none;
        }
        .agy-hud-panel.active {
            display: block;
        }

        /* Official Eyebrow Top Bar (like 'Model' / 'Usage') */
        .agy-eyebrow-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .agy-eyebrow-title {
            font-size: 11.5px;
            font-weight: 500;
            color: var(--hud-muted);
            letter-spacing: 0.01em;
            white-space: nowrap;
        }
        .agy-eyebrow-actions {
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        /* Official Rounded Muted Pill Badge (like 'New' / 'Fast' / 'Notice') */
        .agy-tag {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 1.5px 6.5px;
            border-radius: 999px;
            background: var(--hud-well);
            color: var(--hud-muted);
            font-size: 10.5px;
            font-weight: 500;
            line-height: 1.35;
            white-space: nowrap;
        }
        .agy-tag.mono {
            font-family: var(--hud-font);
            font-variant-numeric: tabular-nums;
        }
        .agy-mode-switch {
            cursor: pointer;
            border: 1px solid var(--hud-border);
            padding: 1.5px 7px;
            transition: all 0.12s ease;
            user-select: none;
        }
        .agy-mode-switch:hover {
            background: var(--hud-hover-bg);
            color: var(--hud-fg);
        }
        .agy-mode-switch .active-mode {
            color: var(--hud-fg);
            font-weight: 600;
        }

        /* Primary Section Heading (like 'Gemini Models' / 'Claude and GPT models') */
        .agy-sec-head {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .agy-sec-title {
            font-size: 13px;
            font-weight: 600;
            color: var(--hud-fg);
        }
        .agy-sec-sub {
            font-family: var(--hud-font);
            font-size: 11.5px;
            font-weight: 500;
            color: var(--hud-muted);
            font-variant-numeric: tabular-nums;
        }

        /* Segmented / Progress Track */
        .agy-bar-track {
            display: flex;
            width: 100%;
            height: 5px;
            border-radius: 999px;
            background: var(--hud-well);
            overflow: hidden;
            margin: 6px 0 10px 0;
            gap: 1.5px;
        }
        .agy-bar-seg {
            height: 100%;
            transition: width 0.25s ease;
            border-radius: 1px;
        }

        /* Official Two-Column Metric Row */
        .agy-hud-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .agy-hud-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 12.5px;
            line-height: 1.35;
        }
        .agy-hud-label {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            color: var(--hud-muted);
        }
        .agy-hud-dot {
            width: 6.5px;
            height: 6.5px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .agy-hud-sq {
            width: 7px;
            height: 7px;
            border-radius: 2px;
            flex-shrink: 0;
        }
        .agy-hud-val {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-family: var(--hud-font);
            font-size: 12px;
            color: var(--hud-fg);
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }
        .agy-hud-val .sub {
            color: var(--hud-muted);
            font-weight: 400;
            font-size: 11px;
        }

        /* Official Multi-line Sub-caption Row (like 'Weekly limit' + '92% left ◔ / Resets in 6d 12h') */
        .agy-usage-block {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            padding-top: 8px;
            margin-top: 8px;
            border-top: 1px solid var(--hud-border);
        }
        .agy-usage-left {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .agy-usage-title {
            font-size: 12.5px;
            color: var(--hud-muted);
            font-weight: 500;
        }
        .agy-usage-sub {
            font-size: 11px;
            color: var(--hud-muted);
            opacity: 0.85;
        }
        .agy-usage-right {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 2px;
        }
        .agy-usage-stat {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-family: var(--hud-font);
            font-size: 12px;
            font-weight: 600;
            color: var(--hud-fg);
            font-variant-numeric: tabular-nums;
        }

        .agy-hud-divider {
            height: 1px;
            background: var(--hud-border);
            margin: 8px 0;
        }

        /* Mode visibility helpers */
        #agy-ctx-gauge[data-mode="minimal"] .pro-only {
            display: none !important;
        }
        #agy-ctx-gauge[data-mode="pro"] .min-only {
            display: none !important;
        }
        #antigravity-context-gauge-root,
        .dsh-dock-bar,
        .dsh-stat-popover,
        [id^="dsh-"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }
    `;
    document.head.appendChild(style);

    window.__fmtTok = (n) => {
        if (n >= 1000000) return (n / 1000000).toFixed(n >= 10000000 ? 1 : 2).replace(/\.0$/, '') + 'M';
        if (n >= 1000) return (n / 1000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, '') + 'K';
        return String(n || 0);
    };

    window.__fmtDur = (sec) => {
        if (!sec || sec <= 0) return '0.0秒';
        if (sec < 60) return sec.toFixed(1) + '秒';
        const m = Math.floor(sec / 60);
        const s = Math.round(sec % 60);
        if (m < 60) return m + '分' + (s < 10 ? '0' : '') + s + '秒';
        const h = Math.floor(m / 60);
        const rm = m % 60;
        return h + '时' + rm + '分';
    };

    window.__mkRingSvg = (pct, colorVar, size = 14) => {
        const r = 5.2;
        const c = (2 * Math.PI * r).toFixed(2);
        const clamped = Math.min(100, Math.max(0, pct || 0));
        const offset = (c - (clamped / 100) * c).toFixed(2);
        return `<svg width="${size}" height="${size}" viewBox="0 0 14 14" style="transform:rotate(-90deg);flex-shrink:0">
            <circle cx="7" cy="7" r="${r}" fill="none" stroke="currentColor" stroke-width="1.75" style="opacity:0.2"/>
            <circle cx="7" cy="7" r="${r}" fill="none" stroke="${colorVar}" stroke-width="1.75"
                stroke-dasharray="${c}" stroke-dashoffset="${offset}" stroke-linecap="round"/>
        </svg>`;
    };

    window.__agyActiveTab = null;
    window.__agyPinned = false;
    window.__agyPulseMode = localStorage.getItem('agy_pulse_mode') || 'minimal';

    window.__toggleAgyPulseMode = (e) => {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        window.__agyPulseMode = window.__agyPulseMode === 'pro' ? 'minimal' : 'pro';
        try {
            localStorage.setItem('agy_pulse_mode', window.__agyPulseMode);
        } catch (_) {}
        if (window.__lastAgyPulseData) {
            window.__updateAntigravityGauge(window.__lastAgyPulseData);
        }
        return false;
    };

    if (!window.__agyDocClickBound) {
        window.__agyDocClickBound = true;
        document.addEventListener('click', (e) => {
            const g = document.getElementById('agy-ctx-gauge');
            if (g && !g.contains(e.target)) {
                window.__agyPinned = false;
                window.__agyActiveTab = null;
                g.classList.remove('open');
                g.querySelectorAll('.agy-hud-pill').forEach(b => b.classList.remove('active'));
            }
        });
    }

    window.__updateAntigravityGauge = (data) => {
        cleanupLegacy();
        window.__lastAgyPulseData = data;

        // Locate microphone / action button container on the right side of the chat input bar
        let micBtn = document.querySelector('button[data-tooltip-id="input-send-button-record-tooltip"]') ||
                     document.querySelector('button[data-tooltip-id="input-send-button-cancel-tooltip"]');
        if (!micBtn) {
            const candidates = Array.from(document.querySelectorAll('button')).filter(b => {
                if (b.closest('nav, aside, [class*="sidebar"]')) return false;
                const tip = b.getAttribute('data-tooltip-id') || '';
                const aria = b.getAttribute('aria-label') || '';
                return tip.includes('record') || aria.includes('录音') || aria.includes('Record');
            });
            if (candidates.length > 0) micBtn = candidates[candidates.length - 1];
        }
        if (!micBtn || micBtn.closest('nav, aside, [class*="sidebar"]')) return false;

        const micContainer = micBtn.closest('.flex.items-center');
        if (!micContainer || !micContainer.parentElement || micContainer.closest('nav, aside, [class*="sidebar"]')) return false;

        const hostBar = micContainer.parentElement;
        hostBar.style.position = 'relative';
        hostBar.style.zIndex = '100';
        const formBox = hostBar.closest('form') || hostBar.parentElement?.parentElement;
        if (formBox) {
            formBox.style.position = 'relative';
            formBox.style.zIndex = '100';
        }

        let g = document.getElementById('agy-ctx-gauge');
        if (!g || g.parentElement !== hostBar) {
            if (g) g.remove();
            g = document.createElement('div');
            g.id = 'agy-ctx-gauge';
            g.innerHTML = `
                <div class="agy-hud-pill" data-tab="activity" oncontextmenu="return window.__toggleAgyPulseMode(event)" title="左键固定 · 右键切换 [极简/详细] 模式"></div>
                <div class="agy-hud-pill" data-tab="usage" oncontextmenu="return window.__toggleAgyPulseMode(event)" title="左键固定 · 右键切换 [极简/详细] 模式"></div>
                <div class="agy-hud-pill" data-tab="context" oncontextmenu="return window.__toggleAgyPulseMode(event)" title="左键固定 · 右键切换 [极简/详细] 模式"></div>
                <div class="agy-hud-popover">
                    <div class="agy-hud-panel" data-panel="activity"></div>
                    <div class="agy-hud-panel" data-panel="usage"></div>
                    <div class="agy-hud-panel" data-panel="context"></div>
                </div>
            `;
            hostBar.insertBefore(g, micContainer);

            const switchTab = (tabName) => {
                window.__agyActiveTab = tabName;
                g.classList.add('open');
                g.querySelectorAll('.agy-hud-pill').forEach(p => {
                    p.classList.toggle('active', p.dataset.tab === tabName);
                });
                g.querySelectorAll('.agy-hud-panel').forEach(pan => {
                    pan.classList.toggle('active', pan.dataset.panel === tabName);
                });
            };

            g.querySelectorAll('.agy-hud-pill').forEach(pill => {
                pill.addEventListener('mouseenter', () => {
                    if (!window.__agyPinned) switchTab(pill.dataset.tab);
                });
                pill.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const tab = pill.dataset.tab;
                    if (window.__agyPinned && window.__agyActiveTab === tab) {
                        window.__agyPinned = false;
                        window.__agyActiveTab = null;
                        g.classList.remove('open');
                        g.querySelectorAll('.agy-hud-pill').forEach(p => p.classList.remove('active'));
                    } else {
                        window.__agyPinned = true;
                        switchTab(tab);
                    }
                });
            });

            g.addEventListener('mouseleave', () => {
                if (!window.__agyPinned) {
                    window.__agyActiveTab = null;
                    g.classList.remove('open');
                    g.querySelectorAll('.agy-hud-pill').forEach(p => p.classList.remove('active'));
                }
            });
        }

        const mode = window.__agyPulseMode || 'minimal';
        g.dataset.mode = mode;

        const act = data.activity || {};
        const usg = data.usage || {};
        const ctx = data.context_meter || {};

        const modeBadgeHtml = `
            <span class="agy-tag agy-mode-switch" onclick="return window.__toggleAgyPulseMode(event)" title="点击切换 [极简 / 详细] 模式">
                <span class="${mode === 'minimal' ? 'active-mode' : ''}">极简</span>
                <span style="opacity:0.35">|</span>
                <span class="${mode === 'pro' ? 'active-mode' : ''}">详细</span>
            </span>
        `;

        // 1. Pill 1: Activity / Speed
        const pillAct = g.querySelector('[data-tab="activity"]');
        const tpsVal = Math.round(act.decode_tps || act.e2e_tps || 0);
        const gaugeSvg = `<svg width="12.5" height="12.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 14l4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>`;
        if (mode === 'minimal') {
            pillAct.innerHTML = `${gaugeSvg}<span class="mono-val">${tpsVal} tok/s</span>`;
        } else {
            pillAct.innerHTML = `${gaugeSvg}<span>${act.turns || 0}轮 ${act.steps || 0}步</span><span class="sep">·</span><span class="mono-val">${tpsVal} tok/s</span>`;
        }

        // 2. Pill 2: Cache & Token Usage
        const pillUsg = g.querySelector('[data-tab="usage"]');
        const hitVal = Math.round(usg.cache_hit_pct || 0);
        const dbSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/></svg>`;
        if (mode === 'minimal') {
            pillUsg.innerHTML = `${dbSvg}<span>缓存命中 <span class="mono-val">${hitVal}%</span></span>`;
        } else {
            pillUsg.innerHTML = `${dbSvg}<span class="mono-val">${window.__fmtTok(usg.total_tokens || 0)}</span><span class="sep">·</span><span>缓存 <span class="mono-val">${hitVal}%</span></span>`;
        }

        // 3. Pill 3: Context Window Ring
        const pillCtx = g.querySelector('[data-tab="context"]');
        const usedPct = ctx.used_pct || 0;
        const pctRound = Math.round(usedPct);
        const ringColor = usedPct >= 24.4 ? 'var(--c-amber)' : (usedPct >= 18 ? 'var(--c-blue)' : 'var(--c-green)');
        const pillRing = window.__mkRingSvg(Math.max(4, usedPct), ringColor, 14);
        if (mode === 'minimal') {
            pillCtx.innerHTML = `${pillRing}<span class="mono-val">${pctRound}%</span>`;
        } else {
            pillCtx.innerHTML = `${pillRing}<span class="mono-val">~${window.__fmtTok(ctx.used_tokens || 0)}</span><span class="sep">·</span><span class="mono-val">${pctRound}%</span>`;
        }

        // Panel 1: Activity
        const panAct = g.querySelector('[data-panel="activity"]');
        const totalDur = Math.max(0.1, (act.llm_time_sec || 0) + (act.tool_time_sec || 0));
        const thinkW = Math.min(100, ((act.ttft_total_sec || 0) / totalDur) * 100).toFixed(1);
        const streamW = Math.min(100, ((act.stream_total_sec || 0) / totalDur) * 100).toFixed(1);
        const toolW = Math.min(100, ((act.tool_time_sec || 0) / totalDur) * 100).toFixed(1);

        panAct.innerHTML = `
            <div class="agy-eyebrow-row">
                <span class="agy-eyebrow-title">会话统计 · Telemetry</span>
                <div class="agy-eyebrow-actions">
                    <span class="agy-tag mono">${act.turns || 0} 轮 · ${act.steps || 0} 步</span>
                    ${modeBadgeHtml}
                </div>
            </div>
            <div class="pro-only">
                <div class="agy-bar-track" title="耗时分布：思考等待 ${window.__fmtDur(act.ttft_total_sec)} / 流式输出 ${window.__fmtDur(act.stream_total_sec)} / 工具执行 ${window.__fmtDur(act.tool_time_sec)}">
                    <div class="agy-bar-seg" style="width:${thinkW}%;background:var(--c-purple)"></div>
                    <div class="agy-bar-seg" style="width:${streamW}%;background:var(--c-blue)"></div>
                    <div class="agy-bar-seg" style="width:${toolW}%;background:var(--c-green)"></div>
                </div>
            </div>
            <div class="agy-hud-list">
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-dot pro-only" style="background:var(--c-purple)"></span>模型用时</span>
                    <span class="agy-hud-val">${window.__fmtDur(act.llm_time_sec)}</span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-dot pro-only" style="background:var(--c-green)"></span>工具调用用时</span>
                    <span class="agy-hud-val">${window.__fmtDur(act.tool_time_sec)}</span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label">首 token 平均 (TTFT)</span>
                    <span class="agy-hud-val">${(act.avg_ttft_sec || 0).toFixed(1)}秒</span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label">输出速度 (TPS)</span>
                    <span class="agy-hud-val">${tpsVal} tok/s <span class="sub pro-only">(均值 ${Math.round(act.e2e_tps || 0)})</span></span>
                </div>
            </div>
        `;

        // Panel 2: Usage
        const panUsg = g.querySelector('[data-panel="usage"]');
        const cacheRatioW = Math.min(100, Math.max(0, usg.cache_hit_pct || 0)).toFixed(1);
        panUsg.innerHTML = `
            <div class="agy-eyebrow-row">
                <span class="agy-eyebrow-title">Token 用量 · Usage</span>
                <div class="agy-eyebrow-actions">
                    <span class="agy-tag mono">${window.__fmtTok(usg.total_tokens || 0)}</span>
                    ${modeBadgeHtml}
                </div>
            </div>
            <div class="pro-only">
                <div class="agy-bar-track" title="缓存读取占比 ${cacheRatioW}%">
                    <div class="agy-bar-seg" style="width:${cacheRatioW}%;background:var(--c-purple)"></div>
                    <div class="agy-bar-seg" style="width:${(100 - parseFloat(cacheRatioW)).toFixed(1)}%;background:var(--c-blue)"></div>
                </div>
            </div>
            <div class="agy-hud-list">
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-dot pro-only" style="background:var(--c-blue)"></span>输入 (未缓存)</span>
                    <span class="agy-hud-val">${window.__fmtTok(usg.uncached_input_tokens)}</span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-dot pro-only" style="background:var(--c-purple)"></span>缓存命中</span>
                    <span class="agy-hud-val">${window.__fmtTok(usg.cache_read_tokens)} <span class="sub">(${(usg.cache_hit_pct || 0).toFixed(1)}%)</span></span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-dot pro-only" style="background:var(--c-amber)"></span>输出总计</span>
                    <span class="agy-hud-val">${window.__fmtTok(usg.output_tokens)} <span class="sub pro-only">(思考 ${window.__fmtTok(usg.thinking_output_tokens)})</span></span>
                </div>
            </div>
            <div class="agy-usage-block pro-only">
                <div class="agy-usage-left">
                    <span class="agy-usage-title">会话等价 API 成本</span>
                    <span class="agy-usage-sub">按官方 Token 定价折算</span>
                </div>
                <div class="agy-usage-right">
                    <span class="agy-usage-stat">$${(usg.equivalent_cost_usd || 0).toFixed(2)} USD</span>
                    <span class="agy-usage-sub">本轮命中 ${(usg.last_cache_hit_pct || 0).toFixed(1)}%</span>
                </div>
            </div>
        `;

        // Panel 3: Context Window
        const panCtx = g.querySelector('[data-panel="context"]');
        const cats = ctx.categories || {};
        const sysC = cats.system || { tokens: 0, pct: 0 };
        const toolC = cats.tools || { tokens: 0, pct: 0 };
        const skillC = cats.skills || { tokens: 0, pct: 0 };
        const msgC = cats.messages || { tokens: 0, pct: 0 };

        const maxTok = Math.max(1, ctx.max_tokens || 1048576);
        const wSys = Math.max(0.4, ((sysC.tokens || 0) / maxTok) * 100).toFixed(2);
        const wTool = Math.max(0.3, ((toolC.tokens || 0) / maxTok) * 100).toFixed(2);
        const wSkill = Math.max(0.2, ((skillC.tokens || 0) / maxTok) * 100).toFixed(2);
        const wMsg = Math.max(0.8, ((msgC.tokens || 0) / maxTok) * 100).toFixed(2);

        const compressPct = Math.min(100, ctx.compress_pct || 0);
        const compRingColor = compressPct >= 85 ? 'var(--c-amber)' : 'var(--c-green)';
        const compRingSvg = window.__mkRingSvg(compressPct, compRingColor, 14);
        const remainToComp = Math.max(0, (ctx.compress_tokens || 256000) - (ctx.used_tokens || 0));

        panCtx.innerHTML = `
            <div class="agy-eyebrow-row">
                <span class="agy-eyebrow-title">上下文容量 · Context</span>
                <div class="agy-eyebrow-actions">
                    <span class="agy-tag">${(data.model || data.model_label || 'Model').replace(/\s*\(.*?\)/g, '')}</span>
                    ${modeBadgeHtml}
                </div>
            </div>
            <div class="agy-sec-head">
                <span class="agy-sec-title">已用 ${usedPct.toFixed(1)}%</span>
                <span class="agy-sec-sub">~${window.__fmtTok(ctx.used_tokens)} / ${window.__fmtTok(ctx.max_tokens)}</span>
            </div>
            <div class="agy-bar-track">
                <div class="agy-bar-seg" style="width:${wSys}%;background:var(--hud-muted)"></div>
                <div class="agy-bar-seg" style="width:${wTool}%;background:var(--c-purple)"></div>
                <div class="agy-bar-seg" style="width:${wSkill}%;background:var(--c-amber)"></div>
                <div class="agy-bar-seg" style="width:${wMsg}%;background:var(--c-blue)"></div>
            </div>
            <div class="agy-hud-list">
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-sq" style="background:var(--c-blue)"></span>对话消息</span>
                    <span class="agy-hud-val">~${window.__fmtTok(msgC.tokens)} <span class="sub">(${(msgC.pct || 0).toFixed(1)}%)</span></span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-sq" style="background:var(--c-purple)"></span>系统工具</span>
                    <span class="agy-hud-val">~${window.__fmtTok(toolC.tokens)} <span class="sub">(${(toolC.pct || 0).toFixed(1)}%)</span></span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-sq" style="background:var(--c-amber)"></span>技能 (Skills)</span>
                    <span class="agy-hud-val">~${window.__fmtTok(skillC.tokens)} <span class="sub">(${(skillC.pct || 0).toFixed(1)}%)</span></span>
                </div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label"><span class="agy-hud-sq" style="background:var(--hud-muted)"></span>系统提示词</span>
                    <span class="agy-hud-val">~${window.__fmtTok(sysC.tokens)} <span class="sub">(${(sysC.pct || 0).toFixed(1)}%)</span></span>
                </div>
            </div>
            <div class="min-only">
                <div class="agy-hud-divider"></div>
                <div class="agy-hud-row">
                    <span class="agy-hud-label">平均缓存命中率</span>
                    <span class="agy-hud-val">${(ctx.avg_cache_hit_pct || 0).toFixed(1)}%</span>
                </div>
            </div>
            <div class="agy-usage-block pro-only">
                <div class="agy-usage-left">
                    <span class="agy-usage-title">256K 自动压缩水位</span>
                    <span class="agy-usage-sub">距触发还剩 ~${window.__fmtTok(remainToComp)} · 已自动压缩 ${act.compaction_count || 0} 次</span>
                </div>
                <div class="agy-usage-right">
                    <span class="agy-usage-stat">${compressPct.toFixed(0)}% ${compRingSvg}</span>
                    <span class="agy-usage-sub">缓存命中 ${(ctx.avg_cache_hit_pct || 0).toFixed(1)}%</span>
                </div>
            </div>
        `;

        return true;
    };
    return 'READY_V3_1';
})()
"""


def get_devtools_active_port_info():
    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Antigravity" / "DevToolsActivePort")
    home = Path.home()
    candidates.extend(
        [
            home / "AppData" / "Roaming" / "Antigravity" / "DevToolsActivePort",
            home
            / "Library"
            / "Application Support"
            / "Antigravity"
            / "DevToolsActivePort",
            home / ".config" / "Antigravity" / "DevToolsActivePort",
        ]
    )
    for p in candidates:
        try:
            if p.exists():
                lines = (
                    p.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                )
                if len(lines) >= 2 and lines[0].strip().isdigit():
                    return int(lines[0].strip()), lines[1].strip()
        except Exception:
            pass
    return None, None


def connect_workbench_cdp():
    """Return (ws, session_id, msg_id, debug_err) connected to the active workbench.html page."""
    msg_id = 1
    errs = []
    # 1. Try native Electron DevToolsActivePort browser websocket first
    port, browser_path = get_devtools_active_port_info()
    if port and browser_path:
        try:
            ws = SimpleWebSocket(f"ws://127.0.0.1:{port}{browser_path}")
            ws.connect()
            resp = ws.call_cdp("Target.getTargets", {}, msg_id)
            msg_id += 1
            targets = resp.get("result", {}).get("targetInfos", [])
            summary = [
                f"{t.get('type')}|{t.get('title','')[:18]}|{t.get('url','')[:40]}"
                for t in targets
            ]
            # Attach to all non-blank page targets
            sessions = []
            for t in targets:
                u = t.get("url", "")
                if t.get("type") == "page" and (
                    u
                    and not u.startswith("data:")
                    and not u.startswith("devtools:")
                    and not u.startswith("about:")
                ):
                    tid = t.get("targetId")
                    att = ws.call_cdp(
                        "Target.attachToTarget",
                        {"targetId": tid, "flatten": True},
                        msg_id,
                    )
                    msg_id += 1
                    sid = att.get("result", {}).get("sessionId", "")
                    if sid:
                        sessions.append((sid, u[:40]))
            if sessions:
                return ws, sessions, msg_id, f"targets={summary}"
            errs.append(f"targets={summary}")
            ws.close()
        except Exception as e:
            errs.append(f"ws({port}):{e}")
    else:
        errs.append(f"no_active_port({port},{browser_path})")

    # 2. Fallback to HTTP /json/list on candidate ports
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ports = [p for p in ([port] if port else []) + [9223, 9222] if p]
    for pt in ports:
        try:
            req = opener.open(f"http://127.0.0.1:{pt}/json/list", timeout=1.5)
            targets = json.loads(req.read().decode("utf-8"))
            for t in targets:
                if t.get("type") == "page" and "workbench.html" in t.get("url", ""):
                    ws_url = t.get("webSocketDebuggerUrl", "")
                    if ws_url:
                        ws = SimpleWebSocket(ws_url)
                        ws.connect()
                        return ws, [("", "http_ws")], msg_id, ""
        except Exception as e:
            errs.append(f"http({pt}):{e}")
            continue
    return None, [], msg_id, "; ".join(errs)


def run_sync_loop():
    import importlib

    save_ls_env("starting")
    ws = None
    sessions = []
    msg_id = 1
    own_mtime = Path(__file__).stat().st_mtime
    gen_mtime = Path(generate_monitor.__file__).stat().st_mtime

    while True:
        try:
            cur_gen_mtime = Path(generate_monitor.__file__).stat().st_mtime
            if cur_gen_mtime != gen_mtime:
                gen_mtime = cur_gen_mtime
                importlib.reload(generate_monitor)
        except Exception:
            pass

        try:
            if ws is None:
                ws, sessions, msg_id, dbg_err = connect_workbench_cdp()
                if ws is None or not sessions:
                    save_ls_env("no_cdp_ws", dbg_err)
                    time.sleep(2.0)
                    continue
                for sid, _ in sessions:
                    ws.eval_js(SETUP_JS, msg_id, sid)
                    msg_id += 1

            data = generate_monitor.analyze_session()
            if data:
                payload = json.dumps(data, ensure_ascii=False)
                js_call = (
                    f"(window.__AGY_PULSE_VERSION === '3.7' && typeof window.__updateAntigravityGauge === 'function') "
                    f"? window.__updateAntigravityGauge({payload}) : 'NEED_SETUP'"
                )
                results = []
                for sid, uprefix in sessions:
                    resp = ws.eval_js(js_call, msg_id, sid)
                    msg_id += 1
                    val = resp.get("result", {}).get("result", {}).get("value")
                    if val == "NEED_SETUP" or val is None:
                        s_resp = ws.eval_js(SETUP_JS, msg_id, sid)
                        msg_id += 1
                        resp2 = ws.eval_js(
                            f"window.__updateAntigravityGauge({payload})",
                            msg_id,
                            sid,
                        )
                        msg_id += 1
                        val = resp2.get("result", {}).get("result", {}).get("value")
                        if val is None:
                            val = f"raw:{str(resp2)[:100]}"
                    results.append(f"{uprefix[-15:]}={val}")
                save_ls_env(f"injected:{','.join(results)}", dbg_err)
            else:
                save_ls_env("no_session_data")
        except Exception as e:
            save_ls_env("exception", str(e))
            if ws:
                ws.close()
                ws = None
                sessions = []

        time.sleep(1.5)


if __name__ == "__main__":
    run_sync_loop()
