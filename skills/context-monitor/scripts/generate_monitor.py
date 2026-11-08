#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Pulse — Core Telemetry Engine (generate_monitor.py v3.0)
Real-time token speed (TPS), TTFT & tool timing, cache hit & billing breakdown,
and 4-category context window radar (256K auto-compaction + 1M physical limit)
for Google Antigravity 2.0.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_SESSION_CACHE: dict[str, tuple[float, float, dict]] = {}
_LAST_DISCOVER_TS: float = 0.0

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
LS_ENV_CACHE = PLUGIN_ROOT / ".ls_env.json"

# ─── 2026 模型规格与等价 API 定价 (USD / 1M Tokens: Input, Output, CacheRead) ───
MODEL_SPECS = {
    "argon": ("Gemini 4 Argon", 1_048_576, 256_000, (2.00, 10.00, 0.10)),
    "flash": ("Gemini 3.8 Flash", 1_048_576, 256_000, (0.75, 3.75, 0.075)),
    "opus": ("Claude Opus 5.5", 1_000_000, 256_000, (4.00, 20.00, 0.20)),
    "sonnet": ("Claude Sonnet 5.5", 1_000_000, 256_000, (2.00, 10.00, 0.20)),
    "gpt": ("GPT-OSS 120B", 131_072, 80_000, (1.00, 4.00, 0.10)),
    "gemini": ("Gemini 3.1 Pro", 1_048_576, 256_000, (1.25, 5.00, 0.08)),
}
DEFAULT_SPEC = ("Gemini 4 Argon (Medium)", 1_048_576, 256_000, (2.00, 10.00, 0.10))

TOOL_TIME_PATTERN = re.compile(r"Created At:\s*([^\r\n]+)\r?\nCompleted At:\s*([^\r\n]+)")


def _save_creds_to_cache(addr: str, csrf: str):
    os.environ["ANTIGRAVITY_LS_ADDRESS"] = addr
    os.environ["ANTIGRAVITY_CSRF_TOKEN"] = csrf
    try:
        existing = {}
        if LS_ENV_CACHE.exists():
            try:
                existing = json.loads(LS_ENV_CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing["address"] = addr
        existing["csrf"] = csrf
        LS_ENV_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LS_ENV_CACHE.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def discover_live_ls_credentials() -> tuple[str, str]:
    """自动从本机运行中的 language_server 进程与 DevToolsActivePort 探测最新端口与 CSRF Token"""
    global _LAST_DISCOVER_TS
    now = time.time()
    if now - _LAST_DISCOVER_TS < 3.0:
        return "", ""
    _LAST_DISCOVER_TS = now

    cmdline = ""
    try:
        if sys.platform == "win32":
            cmd = [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'language_server*' } | Select-Object -ExpandProperty CommandLine",
            ]
            out = subprocess.check_output(
                cmd,
                timeout=8.0,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            cmdline = out.decode("utf-8", errors="ignore")
        else:
            out = subprocess.check_output(["ps", "-ef"], timeout=3.0, stderr=subprocess.DEVNULL)
            for line in out.decode("utf-8", errors="ignore").splitlines():
                if "language_server" in line and "--csrf_token" in line:
                    cmdline += line + "\n"
    except Exception:
        pass

    m_csrf = re.search(r"--csrf_token\s+([0-9a-fA-F-]{36})", cmdline)
    if not m_csrf:
        return "", ""
    csrf = m_csrf.group(1).strip()

    candidate_addrs = []
    m_bridge = re.search(r"--host_bridge_url=https?://127\.0\.0\.1:(\d+)", cmdline)
    if m_bridge:
        bp = int(m_bridge.group(1))
        candidate_addrs.extend([f"localhost:{bp + 2}", f"https://127.0.0.1:{bp + 1}", f"localhost:{bp + 1}"])

    dt_candidates = []
    if os.environ.get("AGY_BROWSER_ACTIVE_PORT_FILE"):
        dt_candidates.append(Path(os.environ["AGY_BROWSER_ACTIVE_PORT_FILE"]))
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        dt_candidates.append(Path(appdata) / "Antigravity" / "DevToolsActivePort")
    home = Path.home()
    dt_candidates.extend(
        [
            home / "Library" / "Application Support" / "Antigravity" / "DevToolsActivePort",
            home / ".config" / "Antigravity" / "DevToolsActivePort",
        ]
    )
    for dt_file in dt_candidates:
        if dt_file.exists():
            try:
                first_line = dt_file.read_text(encoding="utf-8", errors="ignore").splitlines()[0].strip()
                if first_line.isdigit():
                    cp = int(first_line)
                    for cand in (f"localhost:{cp + 3}", f"https://127.0.0.1:{cp + 2}"):
                        if cand not in candidate_addrs:
                            candidate_addrs.append(cand)
            except Exception:
                pass

    ctx = ssl._create_unverified_context()
    http_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    https_opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
    )
    for addr in candidate_addrs:
        url = (
            f"{addr}/exa.language_server_pb.LanguageServerService/GetUserStatus"
            if addr.startswith("http")
            else f"http://{addr}/exa.language_server_pb.LanguageServerService/GetUserStatus"
        )
        try:
            req = urllib.request.Request(
                url,
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Connect-Protocol-Version": "1",
                    "x-codeium-csrf-token": csrf,
                },
                method="POST",
            )
            op = https_opener if url.startswith("https://") else http_opener
            with op.open(req, timeout=1.5) as resp:
                if resp.status == 200:
                    _save_creds_to_cache(addr, csrf)
                    return addr, csrf
        except Exception:
            continue

    return "", ""


def get_ls_credentials() -> tuple[str, str]:
    """获取或从插件根目录缓存读取本地 Language Server 地址与 CSRF Token"""
    addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "").strip()
    if addr and csrf:
        _save_creds_to_cache(addr, csrf)
        return addr, csrf

    if LS_ENV_CACHE.exists():
        try:
            data = json.loads(LS_ENV_CACHE.read_text(encoding="utf-8"))
            c_addr = str(data.get("address", "")).strip()
            c_csrf = str(data.get("csrf", "")).strip()
            if c_addr and c_csrf:
                return c_addr, c_csrf
        except Exception:
            pass
    return discover_live_ls_credentials()


def _do_ls_request(addr: str, csrf: str, method: str, payload: dict, timeout: float) -> dict | None:
    if not addr.startswith("http://") and not addr.startswith("https://"):
        url = f"http://{addr}/exa.language_server_pb.LanguageServerService/{method}"
    else:
        url = f"{addr}/exa.language_server_pb.LanguageServerService/{method}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "x-codeium-csrf-token": csrf,
        },
        method="POST",
    )
    if url.startswith("https://"):
        ctx = ssl._create_unverified_context()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
        )
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        if resp.status != 200:
            return None
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def call_ls_rpc(method: str, payload: dict, timeout: float = 2.0) -> dict | None:
    """调用本地 Language Server Connect-RPC 接口，若缓存端口失效则自动重探测"""
    addr, csrf = get_ls_credentials()
    if addr and csrf:
        try:
            res = _do_ls_request(addr, csrf, method, payload, timeout)
            if res is not None:
                return res
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
        except Exception:
            pass

    new_addr, new_csrf = discover_live_ls_credentials()
    if new_addr and new_csrf and (new_addr != addr or new_csrf != csrf):
        try:
            return _do_ls_request(new_addr, new_csrf, method, payload, timeout)
        except Exception:
            pass
    return None


def parse_proto_duration(val) -> float:
    """解析 protobuf duration 字符串 (如 '10.399053100s') 为秒数"""
    if not val:
        return 0.0
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    if isinstance(val, str):
        s = val.strip()
        if s.endswith("s"):
            try:
                return max(0.0, float(s[:-1]))
            except Exception:
                return 0.0
    return 0.0


def match_model_spec(raw_model_name: str | None):
    if not raw_model_name:
        return DEFAULT_SPEC
    low = raw_model_name.lower()
    for key, (disp, max_ctx, comp_lim, pricing) in MODEL_SPECS.items():
        if key in low:
            final_disp = raw_model_name.strip() if len(raw_model_name.strip()) > 3 else disp
            return final_disp, max_ctx, comp_lim, pricing
    return raw_model_name.strip(), DEFAULT_SPEC[1], DEFAULT_SPEC[2], DEFAULT_SPEC[3]


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = len(text) - cn_chars
    return int(cn_chars / 1.5 + other_chars / 3.8)


def extract_model_from_settings(content: str) -> str | None:
    block = re.search(r"<USER_SETTINGS_CHANGE>([\s\S]*?)</USER_SETTINGS_CHANGE>", content)
    if not block:
        return None
    inner = block.group(1)
    m = re.search(
        r"changed setting\s+`?Model Selection`?\s+from\s+[\s\S]+?\s+to\s+([\s\S]+?)\.(?:\s|$)",
        inner,
        re.IGNORECASE,
    )
    if m and m.group(1).strip().lower() != "none":
        return m.group(1).strip()
    m2 = re.search(r"(?:^|[\n,;])\s*model\s*:\s*([^\n,;<]+)", inner, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


def format_duration_zh(seconds: float) -> str:
    if seconds <= 0:
        return "0.0秒"
    if seconds < 60:
        return f"{seconds:.1f}秒"
    whole = int(round(seconds))
    mins = whole // 60
    secs = whole % 60
    if mins < 60:
        return f"{mins}分{secs}秒"
    hours = mins // 60
    rem_mins = mins % 60
    return f"{hours}小时{rem_mins}分"


def format_compact_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M".replace(".00M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


def find_target_conversation(explicit_id: str | None = None) -> tuple[str, Path | None]:
    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    if explicit_id:
        if explicit_id == "new":
            return "new", None
        tp = brain_dir / explicit_id / ".system_generated" / "logs" / "transcript.jsonl"
        return explicit_id, (tp if tp.exists() else None)

    if not brain_dir.exists():
        return "new", None

    candidates = []
    for conv_dir in brain_dir.iterdir():
        if not conv_dir.is_dir():
            continue
        tp = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
        if tp.exists():
            try:
                head = tp.read_text(encoding="utf-8", errors="ignore")
                has_user = '"USER_INPUT"' in head
            except Exception:
                has_user = False
            candidates.append((1 if has_user else 0, tp.stat().st_mtime, conv_dir.name, tp))

    if not candidates:
        return "new", None
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][2], candidates[0][3]


def analyze_session(explicit_conv_id: str | None = None) -> dict:
    conv_id, transcript_path = find_target_conversation(explicit_conv_id)
    now_ts = time.time()
    tp_mtime = 0.0
    if transcript_path and transcript_path.exists():
        try:
            tp_mtime = transcript_path.stat().st_mtime
        except Exception:
            tp_mtime = 0.0
    if conv_id and conv_id != "new":
        conv_db_dir = Path.home() / ".gemini" / "antigravity" / "conversations"
        for suffix in (".db-wal", ".db"):
            dbp = conv_db_dir / f"{conv_id}{suffix}"
            if dbp.exists():
                try:
                    tp_mtime = max(tp_mtime, dbp.stat().st_mtime)
                except Exception:
                    pass

    cached = _SESSION_CACHE.get(conv_id)
    if cached and (now_ts - cached[0] < 1.5) and cached[1] == tp_mtime:
        return cached[2]

    # 1. 解析本地 transcript.jsonl（获取步数、轮次、工具调用耗时、压缩点及基础 Token）
    lines = []
    if transcript_path and transcript_path.exists():
        try:
            with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [json.loads(line) for line in f if line.strip()]
        except Exception:
            lines = []

    total_steps = len(lines)
    latest_cp_idx = -1
    compaction_count = 0
    detected_model = None
    user_turns = 0
    sys_turns = 0
    planner_turns = 0
    tool_calls_count = 0
    tool_time_sec = 0.0

    cum_input = 0
    cum_cache_read = 0
    cum_output = 0

    for i, step in enumerate(lines):
        stype = step.get("type", "")
        if stype == "CHECKPOINT":
            latest_cp_idx = i
            compaction_count += 1
        elif stype == "USER_INPUT":
            user_turns += 1
            m_set = extract_model_from_settings(str(step.get("content", "")))
            if m_set:
                detected_model = m_set
        elif stype == "SYSTEM_MESSAGE":
            sys_turns += 1
        elif stype == "PLANNER_RESPONSE":
            planner_turns += 1
            tcs = step.get("tool_calls", [])
            if isinstance(tcs, list):
                tool_calls_count += len(tcs)
            inp = step.get("input_tokens")
            cr = step.get("cache_read_tokens")
            out = step.get("output_tokens")
            if isinstance(inp, int) and isinstance(cr, int) and isinstance(out, int):
                cum_input += inp
                cum_cache_read += cr
                cum_output += out
        elif stype == "GENERIC":
            content_str = str(step.get("content", ""))
            m_time = TOOL_TIME_PATTERN.search(content_str)
            if m_time:
                try:
                    t1 = datetime.fromisoformat(m_time.group(1).strip())
                    t2 = datetime.fromisoformat(m_time.group(2).strip())
                    tool_time_sec += max(0.0, (t2 - t1).total_seconds())
                except Exception:
                    pass

    if user_turns == 0 and total_steps > 0:
        user_turns = max(1, sys_turns)

    is_compacted = latest_cp_idx != -1
    active_start_idx = latest_cp_idx if is_compacted else 0
    active_steps = total_steps - active_start_idx

    # 从 transcript.jsonl 获取最新一次 PLANNER_RESPONSE 的活跃上下文
    last_pr_idx = -1
    for i in range(total_steps - 1, active_start_idx - 1, -1):
        s = lines[i]
        if s.get("type") == "PLANNER_RESPONSE" and isinstance(s.get("input_tokens"), int):
            last_pr_idx = i
            break

    last_input = 0
    last_cache_read = 0
    last_output = 0
    estimated_delta = 0

    if last_pr_idx != -1:
        pr = lines[last_pr_idx]
        last_input = int(pr.get("input_tokens", 0) or 0)
        last_cache_read = int(pr.get("cache_read_tokens", 0) or 0)
        last_output = int(pr.get("output_tokens", 0) or 0)
        for i in range(last_pr_idx + 1, total_steps):
            st = lines[i]
            estimated_delta += (
                estimate_tokens(str(st.get("content", "")))
                + estimate_tokens(str(st.get("thinking", "")))
                + estimate_tokens(str(st.get("tool_calls", "")))
            )
        total_active_context = last_input + last_cache_read + last_output + estimated_delta
    else:
        for i in range(active_start_idx, total_steps):
            st = lines[i]
            estimated_delta += (
                estimate_tokens(str(st.get("content", "")))
                + estimate_tokens(str(st.get("thinking", "")))
                + estimate_tokens(str(st.get("tool_calls", "")))
            )
        total_active_context = (13800 + estimated_delta) if total_steps > 0 else 0

    # 2. 调用 GetCascadeTrajectoryGeneratorMetadata 获取精确四维分类明细、TTFT、流式耗时与思考 Token
    llm_time_sec = 0.0
    tot_ttft_sec = 0.0
    tot_stream_sec = 0.0
    avg_ttft_sec = 0.0
    decode_tps = 0.0
    e2e_tps = 0.0
    latest_tps = 0.0
    cum_thinking_output = 0
    cum_response_output = 0

    cat_system = 0
    cat_tools = 0
    cat_skills = 0
    cat_messages = 0
    has_exact_categories = False

    if conv_id and conv_id != "new":
        gm_resp = call_ls_rpc("GetCascadeTrajectoryGeneratorMetadata", {"cascadeId": conv_id}, timeout=2.5)
        gm_list = gm_resp.get("generatorMetadata", []) if isinstance(gm_resp, dict) else []
        if isinstance(gm_list, list) and gm_list:
            tot_ttft = 0.0
            ttft_cnt = 0
            tot_stream = 0.0
            stream_out_tokens = 0
            stream_resp_tokens = 0

            rpc_cum_in = 0
            rpc_cum_cr = 0
            rpc_cum_out = 0
            rpc_last_in = 0
            rpc_last_cr = 0
            rpc_last_out = 0

            for g in gm_list:
                cm = g.get("chatModel", {})
                if not isinstance(cm, dict):
                    continue
                md_name = cm.get("modelDisplayName")
                if md_name:
                    detected_model = str(md_name).strip()

                u = cm.get("usage", {}) or {}
                inp_t = int(u.get("inputTokens", 0) or 0)
                cr_t = int(u.get("cacheReadTokens", 0) or 0)
                out_t = int(u.get("outputTokens", 0) or 0)
                thk_t = int(u.get("thinkingOutputTokens", 0) or 0)
                rsp_t = int(u.get("responseOutputTokens", 0) or 0)

                rpc_cum_in += inp_t
                rpc_cum_cr += cr_t
                rpc_cum_out += out_t
                cum_thinking_output += thk_t
                cum_response_output += rsp_t
                if inp_t + cr_t > 0:
                    rpc_last_in = inp_t
                    rpc_last_cr = cr_t
                    rpc_last_out = out_t

                ttft_val = parse_proto_duration(cm.get("timeToFirstToken"))
                strm_val = parse_proto_duration(cm.get("streamingDuration"))
                step_dur = ttft_val + strm_val
                llm_time_sec += step_dur

                if ttft_val > 0:
                    tot_ttft += ttft_val
                    ttft_cnt += 1
                if strm_val > 0 and out_t > 0:
                    tot_stream += strm_val
                    stream_out_tokens += out_t
                    stream_resp_tokens += (rsp_t if rsp_t > 0 else out_t)
                    if strm_val >= 0.4:
                        latest_tps = (rsp_t if rsp_t > 0 else out_t) / strm_val
                    elif step_dur > 0:
                        latest_tps = out_t / step_dur

            tot_ttft_sec = tot_ttft
            tot_stream_sec = tot_stream

            if rpc_cum_in + rpc_cum_cr > 0:
                cum_input = rpc_cum_in
                cum_cache_read = rpc_cum_cr
                cum_output = rpc_cum_out

            if last_input + last_cache_read == 0 and rpc_last_in + rpc_last_cr > 0:
                last_input = rpc_last_in
                last_cache_read = rpc_last_cr
                last_output = rpc_last_out
                if last_pr_idx == -1:
                    total_active_context = last_input + last_cache_read + last_output + estimated_delta

            if total_steps == 0 and len(gm_list) > 0:
                total_steps = len(gm_list)
                active_steps = total_steps
                if user_turns == 0:
                    user_turns = 1

            if ttft_cnt > 0:
                avg_ttft_sec = tot_ttft / ttft_cnt
            if llm_time_sec > 0 and cum_output > 0:
                e2e_tps = cum_output / llm_time_sec
            if tot_stream > 0 and stream_resp_tokens > 0:
                decode_tps = stream_resp_tokens / tot_stream
            else:
                decode_tps = e2e_tps
            if latest_tps <= 0:
                latest_tps = decode_tps

            # 提取最新一轮的 contextWindowMetadata.tokenBreakdown
            for g in reversed(gm_list):
                cwm = g.get("chatModel", {}).get("chatStartMetadata", {}).get("contextWindowMetadata", {})
                groups = cwm.get("tokenBreakdown", {}).get("groups", [])
                if isinstance(groups, list) and groups:
                    for grp in groups:
                        gtype = str(grp.get("type", ""))
                        gname = str(grp.get("name", "")).lower()
                        gtokens = int(grp.get("numTokens", 0) or 0)
                        if "SYSTEM_PROMPT" in gtype or "system" in gname:
                            skills_sub = 0
                            for child in grp.get("children", []) or []:
                                cname = str(child.get("name", "")).lower()
                                if "skill" in cname or "plugin" in cname:
                                    skills_sub += int(child.get("numTokens", 0) or 0)
                            cat_skills += skills_sub
                            cat_system += max(0, gtokens - skills_sub)
                        elif "TOOLS" in gtype or "tool" in gname:
                            cat_tools += gtokens
                        elif "MESSAGES" in gtype or "message" in gname:
                            cat_messages += gtokens
                    has_exact_categories = True
                    break

    # 校准分类 Token 总和与当前活跃上下文一致
    if has_exact_categories and total_active_context > 0:
        fixed_overhead = cat_system + cat_tools + cat_skills
        if total_active_context >= fixed_overhead:
            cat_messages = total_active_context - fixed_overhead
        else:
            total_active_context = fixed_overhead + cat_messages
    elif total_active_context > 0:
        cat_system = min(4956, int(total_active_context * 0.15))
        cat_tools = min(5724, int(total_active_context * 0.18))
        cat_skills = min(3142, int(total_active_context * 0.10))
        cat_messages = max(0, total_active_context - cat_system - cat_tools - cat_skills)

    model_display, max_context, compress_limit, pricing = match_model_spec(detected_model)
    in_price, out_price, cache_price = pricing
    total_cost_usd = (
        (cum_input / 1_000_000) * in_price
        + (cum_output / 1_000_000) * out_price
        + (cum_cache_read / 1_000_000) * cache_price
    )

    compress_pct = min(100.0, round((total_active_context / compress_limit) * 100, 1)) if compress_limit else 0.0
    max_pct = min(100.0, round((total_active_context / max_context) * 100, 1)) if max_context else 0.0

    billed_input = cum_input + cum_cache_read
    cum_cache_hit_pct = round((cum_cache_read / billed_input) * 100, 1) if billed_input > 0 else 0.0

    last_prompt_total = last_input + last_cache_read
    last_cache_hit_pct = round((last_cache_read / last_prompt_total) * 100, 1) if last_prompt_total > 0 else cum_cache_hit_pct

    denom_ctx = max(1, total_active_context)
    categories_data = {
        "messages": {"label": "对话消息", "tokens": cat_messages, "pct": round(cat_messages / denom_ctx * 100, 1)},
        "tools": {"label": "工具定义", "tokens": cat_tools, "pct": round(cat_tools / denom_ctx * 100, 1)},
        "skills": {"label": "技能", "tokens": cat_skills, "pct": round(cat_skills / denom_ctx * 100, 1)},
        "system": {"label": "系统提示词", "tokens": cat_system, "pct": round(cat_system / denom_ctx * 100, 1)},
    }

    bar_len = 24
    filled = min(bar_len, max(1 if total_active_context > 0 else 0, int(round((compress_pct / 100.0) * bar_len))))
    bar_str = "█" * filled + "░" * (bar_len - filled)

    status_badge = "🟢 充裕" if compress_pct < 60 else ("🟡 适中" if compress_pct < 85 else "🔴 逼近自动压缩")
    display_tps = decode_tps if decode_tps > 0 else e2e_tps
    tps_text = f"`{display_tps:.0f} tok/s` (全链路 `{e2e_tps:.1f} tok/s`)" if display_tps > 0 else "`-- tok/s`"
    total_tok_all = cum_input + cum_cache_read + cum_output
    compact_note = f" · 已自动压缩 `{compaction_count}` 次" if compaction_count > 0 else ""

    markdown_card = f"""\
> ### 🌌 Antigravity Pulse 遥测面板 · `{model_display}`
> `{bar_str}` **256K 压缩线水位 `{compress_pct}%`** ({status_badge}{compact_note}) ｜ **1M 物理容量 `{max_pct}%`** (`~{format_compact_tokens(total_active_context)} / {format_compact_tokens(max_context)}`)
>
> | 🔵 对话消息 | 🟣 工具定义 | 🩵 技能与插件 | ⚪ 系统提示词 | 🛢 平均缓存命中率 |
> | :--- | :--- | :--- | :--- | :--- |
> | **`~{format_compact_tokens(cat_messages)}`** (`{categories_data['messages']['pct']}%`) | **`~{format_compact_tokens(cat_tools)}`** (`{categories_data['tools']['pct']}%`) | **`~{format_compact_tokens(cat_skills)}`** (`{categories_data['skills']['pct']}%`) | **`~{format_compact_tokens(cat_system)}`** (`{categories_data['system']['pct']}%`) | **`{cum_cache_hit_pct}%`** |
>
> | ⏱ 输出速度 (TPS) | ⏳ 首 token 平均 (TTFT) | 🤖 模型总用时 | 🛠️ 工具调用用时 | 💰 累计用量与等价成本 |
> | :--- | :--- | :--- | :--- | :--- |
> | **{tps_text}** | **`{format_duration_zh(avg_ttft_sec)}`** | **`{format_duration_zh(llm_time_sec)}`** | **`{format_duration_zh(tool_time_sec)}`** (`{tool_calls_count} 次`) | **`{format_compact_tokens(total_tok_all)} tok`** (`\\${total_cost_usd:.4f}`) |"""

    res = {
        "status": "success",
        "conv_id": conv_id,
        "model": model_display,
        "context_used": total_active_context,
        "compress_limit": compress_limit,
        "max_context": max_context,
        "compress_percentage": compress_pct,
        "max_percentage": max_pct,
        "activity": {
            "turns": user_turns,
            "steps": total_steps,
            "active_steps": active_steps,
            "is_compacted": is_compacted,
            "compaction_count": compaction_count,
            "llm_time_sec": round(llm_time_sec, 1),
            "llm_time_str": format_duration_zh(llm_time_sec),
            "ttft_total_sec": round(tot_ttft_sec, 1),
            "stream_total_sec": round(tot_stream_sec, 1),
            "tool_time_sec": round(tool_time_sec, 1),
            "tool_time_str": format_duration_zh(tool_time_sec),
            "avg_ttft_sec": round(avg_ttft_sec, 1),
            "avg_ttft_str": format_duration_zh(avg_ttft_sec),
            "decode_tps": round(decode_tps, 1),
            "e2e_tps": round(e2e_tps, 1),
            "latest_tps": round(latest_tps, 1),
        },
        "usage": {
            "total_tokens": total_tok_all,
            "total_tokens_str": f"{format_compact_tokens(total_tok_all)} tok",
            "cache_hit_pct": cum_cache_hit_pct,
            "last_cache_hit_pct": last_cache_hit_pct,
            "uncached_input_tokens": cum_input,
            "cache_read_tokens": cum_cache_read,
            "output_tokens": cum_output,
            "thinking_output_tokens": cum_thinking_output,
            "response_output_tokens": cum_response_output,
            "equivalent_cost_usd": round(total_cost_usd, 4),
        },
        "context_meter": {
            "used_tokens": total_active_context,
            "used_tokens_str": f"~{format_compact_tokens(total_active_context)}",
            "max_tokens": max_context,
            "max_tokens_str": format_compact_tokens(max_context),
            "compress_tokens": compress_limit,
            "compress_tokens_str": format_compact_tokens(compress_limit),
            "used_pct": max_pct,
            "compress_pct": compress_pct,
            "avg_cache_hit_pct": cum_cache_hit_pct,
            "categories": categories_data,
        },
        "markdown_card": markdown_card,
    }
    _SESSION_CACHE[conv_id] = (now_ts, tp_mtime, res)
    return res


def main():
    explicit_id = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    result = analyze_session(explicit_id)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
