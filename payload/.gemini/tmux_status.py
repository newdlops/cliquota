import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime

GEMINI_HOME = os.path.expanduser("~/.gemini")
GEMINI_TMP_ROOT = os.path.join(GEMINI_HOME, "tmp")
GEMINI_LOG = os.path.join(GEMINI_HOME, "telemetry.log")
GEMINI_ACCOUNTS = os.path.join(GEMINI_HOME, "google_accounts.json")
GEMINI_QUOTA_BIN = os.path.join(GEMINI_HOME, "bin", "gemini-rate-limits.mjs")
TMUX_STATUS_STATE_DIR = os.path.join(GEMINI_HOME, "tmux-status-state")

CODEX_HOME = os.path.expanduser("~/.codex")
CODEX_RATELIMIT_BIN = os.path.join(CODEX_HOME, "bin", "codex-rate-limits")
CODEX_STATE_DB = os.path.join(CODEX_HOME, "state_5.sqlite")
CODEX_AUTH = os.path.join(CODEX_HOME, "auth.json")
CODEX_TUI_LOG = os.path.join(CODEX_HOME, "log", "codex-tui.log")

TELEMETRY_SESSION_RE = re.compile(r'"session\.id":\s*"(?P<session>[^"]+)"')
TELEMETRY_EVENT_TS_RE = re.compile(r'"event\.timestamp":\s*"(?P<timestamp>[^"]+)"')
TELEMETRY_START_TIME_RE = re.compile(r'"startTime":\s*\[\s*(?P<sec>\d+)\s*,\s*(?P<nano>\d+)\s*\]', re.S)
TELEMETRY_MODEL_RE = re.compile(
    r'"(?P<field>slash_command\.model\.model_name|gen_ai\.response\.model|gen_ai\.request\.model|model_name|model)"'
    r'\s*:\s*"(?P<model>gemini-[^"]+)"'
)
TELEMETRY_PROCESS_PID_RE = re.compile(r'"process\.pid"\s*,\s*(?P<pid>\d+)')
GEMINI_PID_SESSION_RE = re.compile(
    r'"process\.pid"\s*,\s*(?P<pid>\d+)\s*\].{0,2500}?"session\.id"\s*,\s*"(?P<session>[^"]+)"',
    re.S,
)
CODEX_THREAD_START_RE = re.compile(
    r'^(?P<timestamp>\S+)\s+INFO session_init:shell_snapshot\{thread_id=(?P<thread_id>[0-9a-f-]+)\}: .*?: new$'
)
CODEX_SESSION_NAME_RE = re.compile(r"^codex-(?P<epoch>\d+)-\d+$")
PROCESS_LINE_RE = re.compile(
    r"^\s*(?P<pid>\d+)\s+"
    r"(?P<lstart>[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s+"
    r"(?P<command>.+)$"
)
STATE_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pane-id")
    parser.add_argument("--pane-tty")
    parser.add_argument("--pane-pid")
    parser.add_argument("--pane-path")
    parser.add_argument("--pane-command")
    parser.add_argument("--pane-start-command")
    parser.add_argument("--session-name")
    return parser.parse_args()


def run_command(args):
    try:
        return subprocess.check_output(args, text=True).strip()
    except Exception:
        return ""


def tmux_value(fmt):
    return run_command(["tmux", "display-message", "-p", fmt])


def normalize_tty(tty):
    if not tty:
        return ""
    if tty.startswith("/dev/"):
        return tty[5:]
    return tty


def parse_pid(value):
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else None
    except Exception:
        return None


def get_pane_state_path(pane_id=None, tty=None, session_name=None):
    raw_key = pane_id or normalize_tty(tty) or session_name or "unknown"
    safe_key = STATE_KEY_SAFE_RE.sub("_", raw_key)
    return os.path.join(TMUX_STATUS_STATE_DIR, f"{safe_key}.json")


def load_pane_state(pane_id=None, tty=None, session_name=None):
    parsed = read_json(get_pane_state_path(pane_id, tty, session_name))
    return parsed if isinstance(parsed, dict) else {}


def same_process_identity(state, agent_name, process_pid=None, process_start_ts=None):
    if not state or state.get("agent") != agent_name:
        return False

    cached_pid = state.get("pid")
    if process_pid:
        if not isinstance(cached_pid, int) or cached_pid != int(process_pid):
            return False

    cached_start_ts = state.get("start_ts")
    if process_start_ts:
        if not isinstance(cached_start_ts, (int, float)):
            return False
        if abs(float(cached_start_ts) - float(process_start_ts)) > 2:
            return False

    return True


def parse_timestamp(value):
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def parse_lstart(value):
    if not value:
        return 0.0
    try:
        dt = datetime.strptime(value, "%a %b %d %H:%M:%S %Y")
        return time.mktime(dt.timetuple())
    except Exception:
        return 0.0


def parse_unix_timestamp(seconds, nanos=0):
    try:
        return float(seconds) + (float(nanos) / 1000000000.0)
    except Exception:
        return 0.0


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return None


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception:
        return ""


def read_head(path, max_bytes=8192):
    try:
        with open(path, "rb") as file:
            return file.read(max_bytes).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def read_tail(path, max_bytes=262144):
    try:
        with open(path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - max_bytes))
            return file.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def write_json_atomic(path, payload):
    directory = os.path.dirname(path)
    temp_path = f"{path}.{os.getpid()}.tmp"
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=True, separators=(",", ":"))
            file.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def save_pane_state(pane_context, agent_name, process_pid=None, process_start_ts=None, **extra):
    if not pane_context:
        return

    payload = {
        "agent": agent_name,
        "pane_id": pane_context.get("pane_id"),
        "tty": normalize_tty(pane_context.get("tty")),
        "session_name": pane_context.get("session_name"),
        "current_path": pane_context.get("current_path"),
        "pid": int(process_pid) if process_pid else None,
        "start_ts": float(process_start_ts) if process_start_ts else None,
        "updated_at": time.time(),
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    write_json_atomic(
        get_pane_state_path(
            pane_context.get("pane_id"),
            pane_context.get("tty"),
            pane_context.get("session_name"),
        ),
        payload,
    )


def format_compact(value):
    if not isinstance(value, (int, float)):
        return "?"
    if value >= 1000000:
        return f"{value / 1000000:.1f}m"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(int(value))


def shorten_email(email):
    if not email:
        return "unknown"
    return email.split("@", 1)[0]


def clean_model_name(model_name):
    if not model_name:
        return "unknown"
    if model_name.startswith("gemini-"):
        return model_name[len("gemini-") :]
    return model_name


def format_percent(value):
    if value is None:
        return "?"
    return f"{int(value)}%"


def format_fraction_percent(value):
    if not isinstance(value, (int, float)):
        return "?"
    rounded = round(float(value), 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{int(round(rounded))}%"
    return f"{rounded:.1f}%"


def format_context_usage(used, total):
    if isinstance(used, (int, float)) and isinstance(total, (int, float)):
        return f"{format_compact(used)}/{format_compact(total)}"
    if isinstance(used, (int, float)):
        return format_compact(used)
    if isinstance(total, (int, float)):
        return f"?/{format_compact(total)}"
    return "?"


def list_tty_processes(tty):
    tty_name = normalize_tty(tty)
    if not tty_name:
        return []

    output = run_command(["/bin/ps", "-t", tty_name, "-o", "pid=,lstart=,command="])
    processes = []
    for line in output.splitlines():
        match = PROCESS_LINE_RE.match(line)
        if not match:
            continue
        processes.append(
            {
                "pid": int(match.group("pid")),
                "start_ts": parse_lstart(match.group("lstart")),
                "command": match.group("command"),
                "command_lc": match.group("command").lower(),
            }
        )
    return processes


def get_process_lstart_by_pid(process_pid):
    parsed_pid = parse_pid(process_pid)
    if not parsed_pid:
        return 0.0
    return parse_lstart(run_command(["/bin/ps", "-p", str(parsed_pid), "-o", "lstart="]))


def get_process_command_by_pid(process_pid):
    parsed_pid = parse_pid(process_pid)
    if not parsed_pid:
        return ""
    return run_command(["/bin/ps", "-p", str(parsed_pid), "-o", "command="]).lower()


def infer_agent_name(session_name=None, pane_start_command=None, pane_command=None, process_command=None):
    for candidate in (process_command, pane_start_command, pane_command):
        command_lc = (candidate or "").lower()
        for agent_name in ("gemini", "codex"):
            if matches_agent_command(command_lc, agent_name):
                return agent_name

    session_name = session_name or ""
    if session_name == "gemini" or session_name.startswith("gemini-"):
        return "gemini"
    if session_name.startswith("codex-"):
        return "codex"
    return None


def matches_agent_command(command_lc, agent_name):
    if not command_lc:
        return False
    if agent_name == "gemini":
        return "/bin/gemini" in command_lc or re.search(r"(^|[ /])gemini([ /]|$)", command_lc) is not None
    if agent_name == "codex":
        return (
            "/bin/codex" in command_lc
            or "/codex/codex" in command_lc
            or re.search(r"(^|[ /])codex([ /]|$)", command_lc) is not None
        )
    return False


def detect_agent_process(tty):
    processes = list_tty_processes(tty)
    for agent_name in ("gemini", "codex"):
        candidates = [item for item in processes if matches_agent_command(item["command_lc"], agent_name)]
        if not candidates:
            continue
        candidates.sort(key=lambda item: (item["start_ts"] if item["start_ts"] > 0 else float("inf"), item["pid"]))
        selected = candidates[0]
        selected["agent"] = agent_name
        return selected
    return None


def get_pane_context(cli_args):
    pane_id = cli_args.pane_id or tmux_value("#{pane_id}")
    tty = cli_args.pane_tty or tmux_value("#{pane_tty}")
    pane_pid = parse_pid(cli_args.pane_pid or tmux_value("#{pane_pid}"))
    current_path = cli_args.pane_path or tmux_value("#{pane_current_path}") or os.getcwd()
    pane_command = cli_args.pane_command or tmux_value("#{pane_current_command}")
    pane_start_command = cli_args.pane_start_command or tmux_value("#{pane_start_command}")
    session_name = cli_args.session_name or tmux_value("#{session_name}")
    process_command = get_process_command_by_pid(pane_pid)
    inferred_agent = infer_agent_name(session_name, pane_start_command, pane_command, process_command)

    agent_process = None
    if pane_pid and inferred_agent:
        agent_process = {
            "pid": pane_pid,
            "start_ts": get_process_lstart_by_pid(pane_pid),
            "command": process_command or pane_start_command or pane_command or "",
            "command_lc": process_command or (pane_start_command or pane_command or "").lower(),
            "agent": inferred_agent,
        }
    else:
        agent_process = detect_agent_process(tty)

    proc_text = ""
    if agent_process:
        proc_text = agent_process["command_lc"]
    elif process_command:
        proc_text = process_command
    elif pane_start_command or pane_command:
        proc_text = f"{pane_start_command or ''} {pane_command or ''}".lower()
    elif tty:
        proc_text = run_command(["/bin/ps", "-t", normalize_tty(tty), "-o", "command="]).lower()
    return {
        "pane_id": pane_id,
        "tty": tty,
        "pane_pid": pane_pid,
        "current_path": current_path,
        "pane_command": pane_command,
        "pane_start_command": pane_start_command,
        "session_name": session_name,
        "proc_text": proc_text,
        "agent_process": agent_process,
    }


def path_match_score(current_path, candidate_path):
    if not current_path or not candidate_path:
        return -1
    if current_path == candidate_path or current_path.startswith(candidate_path + os.sep):
        return len(candidate_path)
    if candidate_path == current_path or candidate_path.startswith(current_path + os.sep):
        return len(current_path)
    return -1


def resolve_gemini_project_dir(current_path):
    best_dir = None
    best_key = None
    try:
        for entry in os.scandir(GEMINI_TMP_ROOT):
            if not entry.is_dir():
                continue
            project_root_file = os.path.join(entry.path, ".project_root")
            project_root = read_text(project_root_file).strip()
            if not project_root:
                continue
            if current_path == project_root:
                key = (3, len(project_root))
            elif current_path.startswith(project_root + os.sep):
                key = (2, len(project_root))
            else:
                continue
            if best_key is None or key > best_key:
                best_dir = entry.path
                best_key = key
    except Exception:
        return None
    return best_dir


def load_gemini_project_logs(project_dir):
    logs_path = os.path.join(project_dir, "logs.json")
    logs_data = read_json(logs_path)
    return logs_data if isinstance(logs_data, list) else []


def get_latest_gemini_session_id(project_dir):
    logs_data = load_gemini_project_logs(project_dir)
    latest_entry = None
    latest_ts = -1.0
    for entry in logs_data:
        if not isinstance(entry, dict):
            continue
        session_id = entry.get("sessionId")
        if not session_id:
            continue
        entry_ts = parse_timestamp(entry.get("timestamp"))
        if entry_ts >= latest_ts:
            latest_ts = entry_ts
            latest_entry = entry
    return latest_entry.get("sessionId") if latest_entry else None


def get_gemini_session_id_for_pid(process_pid):
    if not process_pid or not os.path.exists(GEMINI_LOG):
        return None

    content = read_tail(GEMINI_LOG, max_bytes=2097152)
    best_session_id = None
    best_index = -1
    for match in GEMINI_PID_SESSION_RE.finditer(content):
        if int(match.group("pid")) != int(process_pid):
            continue
        if match.start() >= best_index:
            best_index = match.start()
            best_session_id = match.group("session")
    return best_session_id


def get_gemini_session_entries(project_dir, session_id):
    if not session_id:
        return []
    return [
        entry
        for entry in load_gemini_project_logs(project_dir)
        if isinstance(entry, dict) and entry.get("sessionId") == session_id
    ]


def get_gemini_session_id_for_process(project_dir, process_start_ts=None, process_pid=None):
    session_id_from_pid = get_gemini_session_id_for_pid(process_pid)
    if session_id_from_pid:
        return session_id_from_pid

    logs_data = load_gemini_project_logs(project_dir)
    if not logs_data:
        return None

    sessions = {}
    for entry in logs_data:
        if not isinstance(entry, dict):
            continue
        session_id = entry.get("sessionId")
        if not session_id:
            continue
        entry_ts = parse_timestamp(entry.get("timestamp"))
        record = sessions.setdefault(
            session_id,
            {
                "first_ts": entry_ts if entry_ts > 0 else float("inf"),
                "last_ts": entry_ts,
            },
        )
        if entry_ts > 0:
            record["first_ts"] = min(record["first_ts"], entry_ts)
            record["last_ts"] = max(record["last_ts"], entry_ts)

    best_session_id = None
    best_key = None
    best_bucket = 0
    for session_id, record in sessions.items():
        first_ts = record.get("first_ts")
        last_ts = record.get("last_ts")
        bucket = 1
        if process_start_ts and isinstance(first_ts, (int, float)) and first_ts > 0:
            delta = abs(float(first_ts) - process_start_ts)
            if process_start_ts - 300 <= float(first_ts) <= process_start_ts + 1800:
                bucket = 3
            elif delta <= 7200:
                bucket = 2
            key = (
                bucket,
                -delta,
                float(last_ts) if isinstance(last_ts, (int, float)) else 0,
            )
        else:
            key = (
                1,
                0,
                float(last_ts) if isinstance(last_ts, (int, float)) else 0,
            )
        if best_key is None or key > best_key:
            best_session_id = session_id
            best_key = key
            best_bucket = bucket
    if process_start_ts:
        return best_session_id if best_bucket >= 2 else None
    return best_session_id


def load_gemini_telemetry_model_records():
    if not os.path.exists(GEMINI_LOG):
        return []

    content = read_tail(GEMINI_LOG, max_bytes=2097152)
    records = []
    seen = set()

    for match in TELEMETRY_MODEL_RE.finditer(content):
        center = match.start()
        window_start = max(0, center - 4096)
        window_end = min(len(content), match.end() + 4096)
        window = content[window_start:window_end]
        relative_center = center - window_start

        session_candidates = []
        for session_match in TELEMETRY_SESSION_RE.finditer(window):
            session_candidates.append((abs(session_match.start() - relative_center), session_match.group("session")))
        session_id = min(session_candidates, default=(float("inf"), None))[1]

        pid_candidates = []
        for pid_match in TELEMETRY_PROCESS_PID_RE.finditer(window):
            pid_candidates.append((abs(pid_match.start() - relative_center), int(pid_match.group("pid"))))
        process_pid = min(pid_candidates, default=(float("inf"), None))[1]

        timestamp_candidates = []
        for ts_match in TELEMETRY_EVENT_TS_RE.finditer(window):
            parsed = parse_timestamp(ts_match.group("timestamp"))
            if parsed > 0:
                timestamp_candidates.append((abs(ts_match.start() - relative_center), parsed))
        for start_match in TELEMETRY_START_TIME_RE.finditer(window):
            parsed = parse_unix_timestamp(start_match.group("sec"), start_match.group("nano"))
            if parsed > 0:
                timestamp_candidates.append((abs(start_match.start() - relative_center), parsed))
        timestamp = min(timestamp_candidates, default=(float("inf"), 0))[1]

        key = (session_id, process_pid, match.group("field"), match.group("model"), int(timestamp))
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "session_id": session_id,
                "process_pid": process_pid,
                "field": match.group("field"),
                "model": match.group("model"),
                "timestamp": timestamp,
            }
        )

    return records


def extract_gemini_chat_header(path):
    header = read_head(path)
    if not header:
        return None

    session_match = re.search(r'"sessionId":\s*"([^"]+)"', header)
    start_match = re.search(r'"startTime":\s*"([^"]+)"', header)
    updated_match = re.search(r'"lastUpdated":\s*"([^"]+)"', header)

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0

    return {
        "path": path,
        "session_id": session_match.group(1) if session_match else None,
        "start_time": parse_timestamp(start_match.group(1) if start_match else None),
        "last_updated": parse_timestamp(updated_match.group(1) if updated_match else None),
        "mtime": mtime,
    }


def get_chat_file_for_process(project_dir, process_start_ts, session_id_hint=None):
    chats_dir = os.path.join(project_dir, "chats")
    if not os.path.isdir(chats_dir):
        return None

    candidates = []
    try:
        for name in os.listdir(chats_dir):
            if not name.endswith(".json"):
                continue
            header = extract_gemini_chat_header(os.path.join(chats_dir, name))
            if header:
                candidates.append(header)
    except Exception:
        return None

    if not candidates:
        return None

    preferred_session_id = session_id_hint or get_latest_gemini_session_id(project_dir)

    if session_id_hint:
        for candidate in candidates:
            if candidate["session_id"] == session_id_hint:
                return candidate["path"]
        return None

    if process_start_ts:
        best = None
        best_key = None
        for candidate in candidates:
            start_time = candidate["start_time"]
            delta = abs(start_time - process_start_ts) if start_time else float("inf")
            bucket = 1
            if start_time and process_start_ts - 300 <= start_time <= process_start_ts + 1800:
                bucket = 3
            elif start_time and delta <= 7200:
                bucket = 2
            hint_bonus = 1 if preferred_session_id and candidate["session_id"] == preferred_session_id else 0
            key = (
                bucket,
                hint_bonus,
                -delta,
                candidate["last_updated"],
                candidate["mtime"],
            )
            if best_key is None or key > best_key:
                best = candidate
                best_key = key

        if best and best_key and best_key[0] >= 2:
            return best["path"]

    if preferred_session_id:
        for candidate in candidates:
            if candidate["session_id"] == preferred_session_id:
                return candidate["path"]

    candidates.sort(key=lambda item: (item["last_updated"], item["mtime"]), reverse=True)
    return candidates[0]["path"]


def parse_gemini_chat_stats(chat_path):
    chat = read_json(chat_path)
    if not isinstance(chat, dict):
        return None

    messages = chat.get("messages") or []
    total_input = 0
    total_output = 0
    total_requests = 0
    latest_model = None
    latest_model_ts = -1.0

    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "gemini":
            continue
        tokens = message.get("tokens") or {}
        input_tokens = tokens.get("input")
        output_tokens = tokens.get("output")

        if isinstance(input_tokens, (int, float)):
            total_input += int(input_tokens)
        if isinstance(output_tokens, (int, float)):
            total_output += int(output_tokens)
        if tokens:
            total_requests += 1

        model_name = message.get("model")
        message_ts = parse_timestamp(message.get("timestamp"))
        if model_name and message_ts >= latest_model_ts:
            latest_model = model_name
            latest_model_ts = message_ts

    return {
        "session_id": chat.get("sessionId"),
        "last_updated": parse_timestamp(chat.get("lastUpdated")),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "requests": total_requests,
        "model": latest_model,
    }


def get_latest_gemini_model_override(session_id, project_dir=None, process_start_ts=None, process_pid=None):
    records = load_gemini_telemetry_model_records()
    if not records:
        return None

    field_priority = {
        "slash_command.model.model_name": 5,
        "model_name": 4,
        "gen_ai.response.model": 3,
        "gen_ai.request.model": 2,
        "model": 1,
    }
    session_entries = get_gemini_session_entries(project_dir, session_id) if project_dir else []
    model_command_ts = [
        parse_timestamp(entry.get("timestamp"))
        for entry in session_entries
        if isinstance(entry.get("message"), str) and entry.get("message", "").startswith("/model")
    ]
    model_command_ts = [item for item in model_command_ts if item > 0]

    latest_session_ts = max(
        [parse_timestamp(entry.get("timestamp")) for entry in session_entries if isinstance(entry, dict)] or [0]
    )
    reference_ts = max(model_command_ts or [0]) or latest_session_ts or process_start_ts or 0

    filtered_records = [record for record in records if process_pid and record.get("process_pid") == process_pid]
    if not filtered_records:
        filtered_records = [record for record in records if session_id and record.get("session_id") == session_id]
    if not filtered_records:
        filtered_records = records

    best = None
    best_key = None
    for record in filtered_records:
        record_ts = record.get("timestamp") or 0
        delta = abs(record_ts - reference_ts) if reference_ts > 0 and record_ts > 0 else float("inf")
        bucket = 1
        if process_pid and record.get("process_pid") == process_pid:
            bucket = 4
        elif session_id and record.get("session_id") == session_id:
            bucket = 3
        elif process_start_ts and record_ts > 0 and process_start_ts - 900 <= record_ts <= process_start_ts + 14400:
            bucket = 2

        if model_command_ts and record_ts > 0:
            latest_model_command_ts = max(model_command_ts)
            if latest_model_command_ts - 60 <= record_ts <= latest_model_command_ts + 900:
                bucket = max(bucket, 4)

        key = (
            bucket,
            field_priority.get(record.get("field"), 0),
            -delta,
            record_ts,
        )
        if best_key is None or key > best_key:
            best = record
            best_key = key

    return best.get("model") if best else None


def cached_chat_matches_session(chat_path, session_id=None):
    if not chat_path or not os.path.exists(chat_path):
        return False
    if not session_id:
        return True
    header = extract_gemini_chat_header(chat_path)
    return bool(header and header.get("session_id") == session_id)


def get_active_google_email():
    accounts = read_json(GEMINI_ACCOUNTS)
    if isinstance(accounts, dict):
        active = accounts.get("active")
        if isinstance(active, str) and active:
            return active
    return None


def get_gemini_quota_snapshot(model_name, current_path):
    if not model_name or not os.path.exists(GEMINI_QUOTA_BIN):
        return None

    command = [GEMINI_QUOTA_BIN, "--json", "--model", model_name]
    if current_path:
        command.extend(["--cwd", current_path])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0 or not result.stdout:
        return None
    try:
        return json.loads(result.stdout)
    except Exception:
        return None


def get_gemini_stats(current_path, process_start_ts=None, process_pid=None, pane_context=None):
    project_dir = resolve_gemini_project_dir(current_path)
    if not project_dir:
        return "Gemini: Idle"

    pane_state = (
        load_pane_state(
            pane_context.get("pane_id"),
            pane_context.get("tty"),
            pane_context.get("session_name"),
        )
        if pane_context
        else {}
    )
    use_cached_state = same_process_identity(pane_state, "gemini", process_pid, process_start_ts)
    if use_cached_state and pane_state.get("project_dir") != project_dir:
        use_cached_state = False

    session_id = get_gemini_session_id_for_pid(process_pid)
    if not session_id and use_cached_state:
        cached_session_id = pane_state.get("gemini_session_id")
        cached_chat_path = pane_state.get("gemini_chat_path")
        if cached_session_id and cached_chat_matches_session(cached_chat_path, cached_session_id):
            session_id = cached_session_id
    if not session_id:
        session_id = get_gemini_session_id_for_process(project_dir, process_start_ts, process_pid)

    chat_path = None
    if use_cached_state:
        cached_chat_path = pane_state.get("gemini_chat_path")
        if cached_chat_matches_session(cached_chat_path, session_id):
            chat_path = cached_chat_path
    if not chat_path:
        chat_path = get_chat_file_for_process(project_dir, process_start_ts, session_id)
    chat_stats = parse_gemini_chat_stats(chat_path) if chat_path else None
    if not session_id and chat_stats:
        session_id = chat_stats.get("session_id")

    latest_model = (
        get_latest_gemini_model_override(session_id, project_dir, process_start_ts, process_pid)
        or (chat_stats or {}).get("model")
        or (pane_state.get("gemini_model") if use_cached_state else None)
    )
    user_email = get_active_google_email() or "unknown"
    quota_snapshot = get_gemini_quota_snapshot(latest_model, current_path) or {}

    if not latest_model:
        return "Gemini: Idle"

    save_pane_state(
        pane_context,
        "gemini",
        process_pid=process_pid,
        process_start_ts=process_start_ts,
        project_dir=project_dir,
        gemini_session_id=session_id,
        gemini_chat_path=chat_path,
        gemini_model=latest_model,
    )

    return (
        f"Gemini[{shorten_email(user_email)}] {clean_model_name(latest_model)}"
        f" | {format_fraction_percent(quota_snapshot.get('remainingPercent'))} left"
        f" | reset {quota_snapshot.get('resetIn') or '?'}"
    )


def get_codex_email():
    auth = read_json(CODEX_AUTH)
    if isinstance(auth, dict):
        profile = auth.get("user_profile") or {}
        if isinstance(profile, dict):
            email = profile.get("email")
            if isinstance(email, str) and email:
                return email
    return None


def load_codex_thread_rows():
    if not os.path.exists(CODEX_STATE_DB):
        return []

    try:
        conn = sqlite3.connect(CODEX_STATE_DB)
        rows = conn.execute(
            "select id, cwd, rollout_path, created_at, updated_at from threads order by updated_at desc limit 200"
        ).fetchall()
        conn.close()
    except Exception:
        return []

    return [
        {
            "thread_id": thread_id,
            "cwd": cwd,
            "rollout_path": rollout_path,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        for thread_id, cwd, rollout_path, created_at, updated_at in rows
    ]


def load_codex_thread_start_records():
    if not os.path.exists(CODEX_TUI_LOG):
        return {}

    content = read_tail(CODEX_TUI_LOG, max_bytes=2097152)
    records = {}
    for line in content.splitlines():
        match = CODEX_THREAD_START_RE.match(line)
        if not match:
            continue
        records[match.group("thread_id")] = parse_timestamp(match.group("timestamp"))
    return records


def parse_codex_session_epoch(session_name):
    if not session_name:
        return None
    match = CODEX_SESSION_NAME_RE.match(session_name)
    if not match:
        return None
    try:
        return float(match.group("epoch"))
    except Exception:
        return None


def get_codex_rollout_for_process(current_path, process_start_ts=None, session_name=None, preferred_rollout_path=None):
    rows = load_codex_thread_rows()
    if not rows:
        return preferred_rollout_path if preferred_rollout_path and os.path.exists(preferred_rollout_path) else None

    thread_start_records = load_codex_thread_start_records()
    session_epoch = parse_codex_session_epoch(session_name)

    best_row = None
    best_key = None
    best_process_bucket = 0
    best_session_bucket = 0
    for row in rows:
        cwd = row.get("cwd")
        rollout_path = row.get("rollout_path")
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        thread_id = row.get("thread_id")
        if not cwd or not rollout_path:
            continue

        score = path_match_score(current_path, cwd)
        if current_path and score < 0:
            continue

        process_bucket = 2
        process_delta = float("inf")
        startup_ts = thread_start_records.get(thread_id)
        reference_ts = startup_ts if isinstance(startup_ts, (int, float)) and startup_ts > 0 else created_at
        if process_start_ts and isinstance(reference_ts, (int, float)):
            process_delta = abs(float(reference_ts) - process_start_ts)
            if process_start_ts - 300 <= float(reference_ts) <= process_start_ts + 1800:
                process_bucket = 3
            elif process_delta <= 7200:
                process_bucket = 2
            else:
                process_bucket = 1

        session_bucket = 0
        session_delta = float("inf")
        if session_epoch and isinstance(created_at, (int, float)):
            session_delta = abs(float(created_at) - session_epoch)
            if session_epoch - 120 <= float(created_at) <= session_epoch + 300:
                session_bucket = 4
            elif session_delta <= 1800:
                session_bucket = 3
            elif session_delta <= 7200:
                session_bucket = 2
            else:
                session_bucket = 1

        preferred_bonus = 1 if preferred_rollout_path and rollout_path == preferred_rollout_path else 0

        key = (
            score,
            session_bucket,
            preferred_bonus,
            process_bucket,
            1 if isinstance(startup_ts, (int, float)) and startup_ts > 0 else 0,
            -session_delta,
            -process_delta,
            float(updated_at) if isinstance(updated_at, (int, float)) else 0,
        )
        if best_key is None or key > best_key:
            best_row = rollout_path
            best_key = key
            best_process_bucket = process_bucket
            best_session_bucket = session_bucket

    strong_session_match = session_epoch and best_session_bucket >= 2
    strong_process_match = process_start_ts and best_process_bucket >= 2
    if best_row and (strong_session_match or strong_process_match or (not session_epoch and not process_start_ts)):
        return best_row
    if preferred_rollout_path and os.path.exists(preferred_rollout_path):
        return preferred_rollout_path
    if not process_start_ts and rows:
        return rows[0].get("rollout_path")
    return None


def parse_codex_rollout_stats(rollout_path):
    latest_model = None
    latest_context_used = None
    latest_context_window = None
    latest_ts = -1.0

    try:
        with open(rollout_path, "r", encoding="utf-8") as file:
            for line in file:
                if '"type":"turn_context"' in line or '"type": "turn_context"' in line:
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    payload = parsed.get("payload") or {}
                    model = payload.get("model")
                    if isinstance(model, str) and model:
                        latest_model = model
                elif '"type":"token_count"' in line or '"type": "token_count"' in line:
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    payload = parsed.get("payload") or {}
                    info = payload.get("info") or {}
                    context_window = info.get("model_context_window")
                    last_usage = (info.get("last_token_usage") or {}).get("total_tokens")
                    total_usage = (info.get("total_token_usage") or {}).get("total_tokens")
                    used_tokens = last_usage if isinstance(last_usage, (int, float)) else total_usage
                    if isinstance(context_window, (int, float)):
                        latest_context_window = int(context_window)
                    if isinstance(used_tokens, (int, float)):
                        latest_context_used = int(used_tokens)
                    latest_ts = max(latest_ts, parse_timestamp(parsed.get("timestamp")))
    except Exception:
        return None

    return {
        "model": latest_model,
        "context_used": latest_context_used,
        "context_window": latest_context_window,
        "timestamp": latest_ts,
    }


def get_codex_rate_snapshot(current_path=None, process_start_ts=None):
    if not os.path.exists(CODEX_RATELIMIT_BIN):
        return None

    command = [CODEX_RATELIMIT_BIN, "--json"]
    if current_path:
        command.extend(["--cwd", current_path])
    if process_start_ts:
        command.extend(["--started-at", str(int(process_start_ts))])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0 or not result.stdout:
        return None
    try:
        return json.loads(result.stdout)
    except Exception:
        return None


def is_future_epoch(value):
    return isinstance(value, (int, float)) and value > time.time() + 60


def get_codex_stats(current_path, process_start_ts=None, process_pid=None, pane_context=None):
    pane_state = (
        load_pane_state(
            pane_context.get("pane_id"),
            pane_context.get("tty"),
            pane_context.get("session_name"),
        )
        if pane_context
        else {}
    )
    use_cached_state = same_process_identity(pane_state, "codex", process_pid, process_start_ts)

    rate_snapshot = get_codex_rate_snapshot(current_path, process_start_ts) or {}
    preferred_rollout_path = None
    if use_cached_state:
        cached_rollout_path = pane_state.get("codex_rollout_path")
        if cached_rollout_path and os.path.exists(cached_rollout_path):
            preferred_rollout_path = cached_rollout_path

    rollout_path = get_codex_rollout_for_process(
        current_path,
        process_start_ts,
        pane_context.get("session_name") if pane_context else None,
        preferred_rollout_path,
    )
    rollout_stats = parse_codex_rollout_stats(rollout_path) if rollout_path else {}

    email = (((rate_snapshot.get("account") or {}).get("email")) or get_codex_email() or "unknown")
    model_name = (
        (rollout_stats or {}).get("model")
        or (pane_state.get("codex_model") if use_cached_state else None)
        or rate_snapshot.get("modelName")
        or "unknown"
    )
    context_used = (rollout_stats or {}).get("context_used")
    if context_used is None:
        context_used = pane_state.get("codex_context_used") if use_cached_state else None
    context_window = (rollout_stats or {}).get("context_window")
    if context_window is None:
        context_window = pane_state.get("codex_context_window") if use_cached_state else None

    primary = rate_snapshot.get("primary") or {}
    secondary = rate_snapshot.get("secondary") or {}
    primary_left = primary.get("left") if is_future_epoch(primary.get("resetsAt")) else None
    secondary_left = secondary.get("left") if is_future_epoch(secondary.get("resetsAt")) else None

    save_pane_state(
        pane_context,
        "codex",
        process_pid=process_pid,
        process_start_ts=process_start_ts,
        codex_rollout_path=rollout_path,
        codex_model=model_name,
        codex_context_used=context_used,
        codex_context_window=context_window,
    )

    return (
        f"Codex[{shorten_email(email)}] {model_name}"
        f" | 5h {format_percent(primary_left)} left"
        f" | week {format_percent(secondary_left)} left"
        f" | ctx {format_context_usage(context_used, context_window)}"
    )


if __name__ == "__main__":
    cli_args = parse_args()
    pane_context = get_pane_context(cli_args)
    agent_process = pane_context.get("agent_process") or {}
    process_start_ts = agent_process.get("start_ts")
    process_pid = agent_process.get("pid")
    proc_text = pane_context.get("proc_text", "")
    current_path = pane_context.get("current_path") or os.getcwd()

    if agent_process.get("agent") == "gemini" or "gemini" in proc_text:
        print(get_gemini_stats(current_path, process_start_ts, process_pid, pane_context))
    elif agent_process.get("agent") == "codex" or "codex" in proc_text:
        print(get_codex_stats(current_path, process_start_ts, process_pid, pane_context))
    else:
        print("G | C (Idle)")
