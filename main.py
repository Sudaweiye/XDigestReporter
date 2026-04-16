
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

APP_NAME = "XDigestReporter"
TASK_NAME = "XDigestReporterDaily"
X_API_BASE = "https://api.x.com/2"
DEFAULT_MONTHLY_BUDGET = 3.0
DEFAULT_PER_REQUEST_COST = 0.01
DEFAULT_CODEX_MODEL = "gpt-5.3-codex"
DEFAULT_CODEX_CLI = "codex.cmd"
LOCAL_TZ_NAME = "Asia/Shanghai"

DEFAULT_ACCOUNTS = [
    "OpenAI", "GoogleDeepMind", "nvidia", "NVIDIAAI", "AnthropicAI", "MetaAI", "deepseek_ai",
    "Alibaba_Qwen", "midjourney", "Kimi_Moonshot", "MiniMax_AI", "BytedanceTalk", "DeepMind",
    "GoogleAI", "GroqInc", "Hailuo_AI", "MIT_CSAIL", "IBMData", "elonmusk", "sama", "zuck",
    "demishassabis", "DarioAmodei", "karpathy", "ylecun", "geoffreyhinton", "ilyasut", "AndrewYNg",
    "jeffdean", "drfeifei", "Thom_Wolf", "danielaamodei", "gdb", "GaryMarcus", "JustinLin610",
    "steipete", "ESYudkowsky", "erikbryn", "alliekmiller", "tunguz", "Ronald_vanLoon", "DeepLearn007",
    "nigewillson", "petitegeek", "YuHelenYu", "TamaraMcCleary", "swyx", "joshwoodward",
    "kevinweil", "petergyang", "thenanyu", "realmadhuguru", "_catwu", "trq212", "amasad",
    "rauchg", "alexalbert__", "levie", "ryolu_", "mattturck", "zarazhangrui", "nikunj", "danshipper",
    "adityaag",
]

class BudgetExceededError(RuntimeError):
    pass

@dataclass
class BudgetState:
    month: str
    used_usd: float
    request_count: int

@dataclass
class ReportArtifacts:
    markdown_path: Path
    tex_path: Path
    pdf_path: Path

class BudgetLimiter:
    def __init__(self, usage_path: Path, monthly_budget: float):
        self.usage_path = usage_path
        self.monthly_budget = float(monthly_budget)
        self.state = self._load()

    def _load(self) -> BudgetState:
        now_month = datetime.now().strftime("%Y-%m")
        if not self.usage_path.exists():
            return BudgetState(month=now_month, used_usd=0.0, request_count=0)
        try:
            raw = json.loads(self.usage_path.read_text(encoding="utf-8"))
        except Exception:
            return BudgetState(month=now_month, used_usd=0.0, request_count=0)
        if raw.get("month") != now_month:
            return BudgetState(month=now_month, used_usd=0.0, request_count=0)
        return BudgetState(
            month=now_month,
            used_usd=float(raw.get("used_usd", 0.0)),
            request_count=int(raw.get("request_count", 0)),
        )

    def reserve(self, estimated_cost: float) -> None:
        cost = max(0.0, float(estimated_cost))
        if self.state.used_usd + cost > self.monthly_budget + 1e-9:
            raise BudgetExceededError(
                f"本月预算不足：已用 ${self.state.used_usd:.4f} / ${self.monthly_budget:.2f}"
            )
        self.state.used_usd += cost
        self.state.request_count += 1
        self._save()

    def _save(self) -> None:
        payload = {
            "month": self.state.month,
            "used_usd": round(self.state.used_usd, 6),
            "request_count": self.state.request_count,
        }
        self.usage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

class XClient:
    def __init__(self, bearer_token: str, limiter: BudgetLimiter, per_request_cost: float):
        self.limiter = limiter
        self.per_request_cost = float(per_request_cost)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        })

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        self.limiter.reserve(self.per_request_cost)
        resp = self.session.get(f"{X_API_BASE}{path}", params=params, timeout=30)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail") or resp.json().get("title") or str(resp.json())
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"X API 错误 {resp.status_code}: {detail}")
        return resp.json()

    def get_user(self, username: str) -> Dict:
        payload = self._get(
            f"/users/by/username/{username}",
            params={"user.fields": "description,public_metrics,verified"},
        )
        return payload.get("data") or {}

    def get_users_by_usernames(self, usernames: List[str]) -> Dict[str, Dict]:
        if not usernames:
            return {}
        payload = self._get(
            "/users/by",
            params={
                "usernames": ",".join(usernames),
                "user.fields": "description,public_metrics,verified",
            },
        )
        out: Dict[str, Dict] = {}
        for user in payload.get("data") or []:
            uname = str(user.get("username", "")).strip()
            if uname:
                out[uname.lower()] = user
        return out

    def get_todays_tweets(
        self,
        user_id: str,
        start_time_utc: str,
        end_time_utc: str,
        max_results: int = 20,
        since_id: Optional[str] = None,
    ) -> List[Dict]:
        params = {
            "max_results": max(5, min(max_results, 20)),
            "exclude": "replies",
            "start_time": start_time_utc,
            "end_time": end_time_utc,
            "tweet.fields": "created_at,lang",
        }
        if since_id:
            params["since_id"] = since_id
        payload = self._get(
            f"/users/{user_id}/tweets",
            params=params,
        )
        return payload.get("data") or []

class CodexTranslator:
    def __init__(self, model: str, codex_command: str):
        self.model = (model or DEFAULT_CODEX_MODEL).strip()
        self.codex_command = (codex_command or DEFAULT_CODEX_CLI).strip()

    def _run_with_schema(self, prompt: str, schema: Dict) -> Dict:
        schema_dir = ROOT / "data"
        schema_dir.mkdir(parents=True, exist_ok=True)
        schema_path = schema_dir / "codex_output_schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")

        base_cmd = [
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "-m",
            self.model,
            "-",
        ]
        cmd = [self.codex_command] + base_cmd
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                cwd=str(ROOT),
            )
        except PermissionError:
            if os.name == "nt" and "." not in Path(self.codex_command).name:
                cmd = [f"{self.codex_command}.cmd"] + base_cmd
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    cwd=str(ROOT),
                )
            else:
                raise
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"本地 Codex 调用失败: {err[-500:]}")

        last_msg = ""
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    last_msg = str(item.get("text", "")).strip()
        parsed = parse_json_from_text(last_msg)
        if not parsed:
            raise RuntimeError("本地 Codex 返回解析失败")
        return parsed

    def analyze_account(self, account: str, tweets: List[Dict]) -> Dict:
        payload = [{"id": t.get("id", ""), "created_at": t.get("created_at", ""), "text": normalize_text(t.get("text", ""))} for t in tweets]
        schema = {
            "type": "object",
            "properties": {
                "summary_cn": {"type": "string"},
                "evaluation_cn": {"type": "string"},
                "hotspots_cn": {"type": "array", "items": {"type": "string"}},
                "translations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "zh": {"type": "string"},
                        },
                        "required": ["id", "zh"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary_cn", "evaluation_cn", "hotspots_cn", "translations"],
            "additionalProperties": False,
        }
        prompt = (
            "You are an AI analyst.\n"
            "Task:\n"
            "1) Translate each tweet to Simplified Chinese.\n"
            "2) Give concise summary and evaluation in Simplified Chinese.\n"
            "3) Extract account-level hotspots in Simplified Chinese.\n"
            "Return JSON only.\n\n"
            f"Account: @{account}\n"
            f"Tweets JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        parsed = self._run_with_schema(prompt, schema)
        trans = parsed.get("translations") if isinstance(parsed.get("translations"), list) else []
        return {
            "summary_cn": str(parsed.get("summary_cn", "")).strip(),
            "evaluation_cn": str(parsed.get("evaluation_cn", "")).strip(),
            "hotspots_cn": [str(x).strip() for x in (parsed.get("hotspots_cn") or []) if str(x).strip()],
            "translations": [
                {"id": str(x.get("id", "")).strip(), "zh": str(x.get("zh", "")).strip()}
                for x in trans if isinstance(x, dict) and str(x.get("id", "")).strip()
            ],
        }

    def summarize_global(self, account_ai: Dict[str, Dict]) -> Dict:
        schema = {
            "type": "object",
            "properties": {
                "global_summary_cn": {"type": "string"},
                "global_evaluation_cn": {"type": "string"},
                "global_hotspots_cn": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["global_summary_cn", "global_evaluation_cn", "global_hotspots_cn"],
            "additionalProperties": False,
        }
        prompt = (
            "Summarize today's AI discourse across accounts.\n"
            "Output Simplified Chinese only in JSON.\n\n"
            f"Input JSON:\n{json.dumps(account_ai, ensure_ascii=False)}"
        )
        parsed = self._run_with_schema(prompt, schema)
        return {
            "global_summary_cn": str(parsed.get("global_summary_cn", "")).strip(),
            "global_evaluation_cn": str(parsed.get("global_evaluation_cn", "")).strip(),
            "global_hotspots_cn": [str(x).strip() for x in (parsed.get("global_hotspots_cn") or []) if str(x).strip()],
        }

def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

ROOT = app_root()
CONFIG_PATH = ROOT / "config.json"
USAGE_PATH = ROOT / "data" / "usage.json"
REPORT_DIR = ROOT / "reports"
USER_CACHE_PATH = ROOT / "data" / "user_cache.json"
FETCH_STATE_PATH = ROOT / "data" / "fetch_state.json"

DEFAULT_CONFIG = {
    "bearer_token": "",
    "codex_cli_path": DEFAULT_CODEX_CLI,
    "codex_model": DEFAULT_CODEX_MODEL,
    "monthly_budget_usd": DEFAULT_MONTHLY_BUDGET,
    "per_request_cost_usd": DEFAULT_PER_REQUEST_COST,
    "daily_time": "09:00",
    "accounts": DEFAULT_ACCOUNTS,
    "selected_accounts": ["OpenAI", "deepseek_ai", "sama", "karpathy"],
}

def ensure_dirs() -> None:
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

def load_config() -> Dict:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    if not merged.get("codex_model"):
        merged["codex_model"] = cfg.get("openai_model") or DEFAULT_CODEX_MODEL
    if not merged.get("codex_cli_path"):
        merged["codex_cli_path"] = DEFAULT_CODEX_CLI
    merged["accounts"] = sorted(set(DEFAULT_ACCOUNTS + merged.get("accounts", [])), key=str.lower)
    return merged

def save_config(cfg: Dict) -> None:
    ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def load_json_file(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default

def save_json_file(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def sanitize_username(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", (name or "").replace("@", "").strip())

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()

def parse_json_from_text(text: str) -> Optional[Dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(raw[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None

def local_today_range_utc_iso() -> Tuple[str, str, str]:
    tz = ZoneInfo(LOCAL_TZ_NAME)
    now_local = datetime.now(tz)
    start_local = datetime(now_local.year, now_local.month, now_local.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_utc = end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return start_utc, end_utc, now_local.strftime("%Y-%m-%d")

def format_tweet_time(utc_iso: str) -> str:
    if not utc_iso:
        return ""
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(LOCAL_TZ_NAME)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_iso

def is_chinese_text(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))

def compact_tweet_text(text: str, limit: int = 260) -> str:
    t = normalize_text(text)
    t = re.sub(r"https?://\S+", "", t).strip()
    return t if len(t) <= limit else t[:limit]

def max_tweet_id(tweets: List[Dict]) -> Optional[str]:
    ids = [str(t.get("id", "")).strip() for t in tweets if str(t.get("id", "")).strip()]
    if not ids:
        return None
    if all(x.isdigit() for x in ids):
        return max(ids, key=lambda x: int(x))
    return ids[0]

def load_user_cache() -> Dict:
    raw = load_json_file(USER_CACHE_PATH, {"users": {}})
    if not isinstance(raw, dict):
        return {"users": {}}
    users = raw.get("users")
    if not isinstance(users, dict):
        users = {}
    return {"users": users}

def save_user_cache(cache: Dict) -> None:
    save_json_file(USER_CACHE_PATH, cache)

def load_fetch_state(day_label: str) -> Dict:
    raw = load_json_file(FETCH_STATE_PATH, {})
    if not isinstance(raw, dict) or raw.get("day") != day_label:
        return {"day": day_label, "accounts": {}}
    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
    return {"day": day_label, "accounts": accounts}

def save_fetch_state(state: Dict) -> None:
    save_json_file(FETCH_STATE_PATH, state)

def latex_escape(text: str) -> str:
    raw = normalize_text(text)
    if not raw:
        return ""
    escaped = []
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for ch in raw:
        if ord(ch) < 32 and ch not in ("\t", " "):
            continue
        escaped.append(mapping.get(ch, ch))
    return "".join(escaped)

def latex_or_na(text: str) -> str:
    value = latex_escape(text)
    return value if value else "暂无"

def build_latex_document(
    selected_accounts: List[str],
    account_data: Dict[str, List[Dict]],
    errors: Dict[str, str],
    limiter: BudgetLimiter,
    account_ai_results: Dict[str, Dict],
    ai_errors: Dict[str, str],
    global_ai: Optional[Dict],
    day_label: str,
    generated_at: str,
) -> str:
    total_tweets = sum(len(v) for v in account_data.values())
    lines = [
        r"\documentclass[11pt,a4paper]{ctexart}",
        r"\usepackage[margin=2.2cm]{geometry}",
        r"\usepackage{xcolor}",
        r"\usepackage{hyperref}",
        r"\usepackage{enumitem}",
        r"\usepackage{fancyhdr}",
        r"\usepackage{lastpage}",
        r"\usepackage{tcolorbox}",
        r"\usepackage{titlesec}",
        r"\usepackage{setspace}",
        r"\usepackage{draftwatermark}",
        r"\definecolor{themeblue}{HTML}{0F4C81}",
        r"\definecolor{themelight}{HTML}{F3F8FF}",
        r"\SetWatermarkText{Jinge Guo專用}",
        r"\SetWatermarkScale{0.30}",
        r"\SetWatermarkColor[gray]{0.90}",
        r"\SetWatermarkAngle{45}",
        r"\titleformat{\section}{\Large\bfseries\color{themeblue}}{}{0em}{}",
        r"\setstretch{1.25}",
        r"\setlist[itemize]{leftmargin=*}",
        r"\setlist[enumerate]{leftmargin=*}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\fancyhead[L]{XDigestReporter}",
        rf"\fancyhead[R]{{{latex_escape(generated_at + ' ' + LOCAL_TZ_NAME)}}}",
        r"\fancyfoot[C]{\thepage/\pageref{LastPage}}",
        r"\begin{document}",
        r"\begin{titlepage}",
        r"\centering",
        r"\vspace*{2.5cm}",
        r"{\fontsize{30pt}{34pt}\selectfont\bfseries\color{themeblue}XDigestReporter}\\[0.8cm]",
        rf"{{\Large\bfseries AI账号当日推文报告 ({latex_escape(day_label)})}}\\[1.2cm]",
        r"\begin{tcolorbox}[width=0.86\textwidth,colback=themelight,colframe=themeblue!60!black,arc=2mm]",
        rf"\textbf{{生成时间}}: {latex_escape(generated_at)} ({latex_escape(LOCAL_TZ_NAME)})\\",
        rf"\textbf{{账号数量}}: {len(selected_accounts)}\\",
        rf"\textbf{{当日推文总数}}: {total_tweets}\\",
        rf"\textbf{{X API预算已用(估算)}}: \${limiter.state.used_usd:.4f} / \${limiter.monthly_budget:.2f}",
        r"\end{tcolorbox}",
        r"\vfill",
        r"\end{titlepage}",
        r"\tableofcontents",
        r"\newpage",
        r"\section{报告总览}",
        rf"本报告覆盖日期为 \textbf{{{latex_escape(day_label)}}}，并使用本地时区 \textbf{{{latex_escape(LOCAL_TZ_NAME)}}} 进行统计。",
    ]

    if global_ai:
        lines.append(r"\section{全局洞察}")
        lines.append(r"\subsection*{全局核心热点}")
        hotspots = global_ai.get("global_hotspots_cn", []) or []
        if hotspots:
            lines.append(r"\begin{itemize}")
            for hot in hotspots:
                lines.append(rf"\item {latex_or_na(str(hot))}")
            lines.append(r"\end{itemize}")
        else:
            lines.append("暂无核心热点。")
        lines.extend([
            r"\subsection*{全局总结}",
            latex_or_na(global_ai.get("global_summary_cn", "")),
            r"\subsection*{全局评价}",
            latex_or_na(global_ai.get("global_evaluation_cn", "")),
        ])

    for account in selected_accounts:
        tweets = account_data.get(account, [])
        err = errors.get(account)
        ai_err = ai_errors.get(account)
        ai = account_ai_results.get(account, {})
        trans = {
            str(x.get("id", "")): str(x.get("zh", ""))
            for x in ai.get("translations", [])
            if isinstance(x, dict)
        }

        lines.append(rf"\section{{@{latex_escape(account)}}}")
        if err:
            lines.append(
                rf"\begin{{tcolorbox}}[colback=red!4!white,colframe=red!60!black,title=状态]\textbf{{抓取失败}}: {latex_or_na(err)}\end{{tcolorbox}}"
            )
            continue
        if not tweets:
            lines.append(
                r"\begin{tcolorbox}[colback=yellow!5!white,colframe=yellow!40!black,title=状态]未更新推文\end{tcolorbox}"
            )
            continue

        hotspots = ai.get("hotspots_cn", []) or []
        lines.append(r"\begin{tcolorbox}[colback=themelight,colframe=themeblue!60!black,title=账号洞察,arc=2mm]")
        lines.append(rf"\textbf{{当日推文数}}: {len(tweets)}\\")
        if ai_err:
            lines.append(rf"\textbf{{AI处理失败}}: {latex_or_na(ai_err)}\\")
        lines.append(rf"\textbf{{AI总结}}: {latex_or_na(ai.get('summary_cn', ''))}\\")
        lines.append(rf"\textbf{{AI评价}}: {latex_or_na(ai.get('evaluation_cn', ''))}\\")
        lines.append(
            rf"\textbf{{账号核心热点}}: {latex_or_na('；'.join(str(x) for x in hotspots) if hotspots else '暂无')}"
        )
        lines.append(r"\end{tcolorbox}")
        lines.append(r"\subsection*{推文原文与简体中文翻译}")
        lines.append(r"\begin{enumerate}[label=\arabic*., itemsep=0.9em]")
        for t in tweets:
            tid = str(t.get("id", ""))
            raw = normalize_text(t.get("text", ""))
            zh = normalize_text(trans.get(tid, "")) or "(翻译缺失)"
            lines.append(r"\item")
            lines.append(rf"\textbf{{时间}}: {latex_or_na(format_tweet_time(t.get('created_at', '')))}\\")
            lines.append(rf"\textbf{{原文}}: {latex_or_na(raw)}\\")
            lines.append(rf"\textbf{{中文}}: {latex_or_na(zh)}")
        lines.append(r"\end{enumerate}")

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"

def compile_latex_pdf(tex_path: Path) -> Path:
    pdf_path = tex_path.with_suffix(".pdf")
    compiler_errors: List[str] = []

    def run_compiler(cmd: List[str], retries: int = 1) -> bool:
        for _ in range(retries):
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(ROOT),
            )
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-30:]
                compiler_errors.append("\n".join(tail))
                return False
        return True

    out_dir = str(tex_path.parent)
    compilers: List[Tuple[List[str], int]] = []
    if shutil.which("xelatex"):
        compilers.append((
            [
                "xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                out_dir,
                str(tex_path),
            ],
            2,
        ))
    if shutil.which("latexmk"):
        compilers.append((
            [
                "latexmk",
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={out_dir}",
                str(tex_path),
            ],
            1,
        ))
    if shutil.which("tectonic"):
        compilers.append((
            [
                "tectonic",
                "--keep-logs",
                "--keep-intermediates",
                "--outdir",
                out_dir,
                str(tex_path),
            ],
            1,
        ))

    if not compilers:
        raise RuntimeError("未检测到 LaTeX 编译器，请安装 TeX Live 并确保 xelatex 在 PATH 中。")

    for cmd, retries in compilers:
        if run_compiler(cmd, retries=retries) and pdf_path.exists():
            return pdf_path

    detail = compiler_errors[-1] if compiler_errors else "未知编译错误"
    raise RuntimeError(f"LaTeX 编译失败，无法生成 PDF。\n{detail}")

def build_report(
    selected_accounts: List[str],
    account_data: Dict[str, List[Dict]],
    errors: Dict[str, str],
    limiter: BudgetLimiter,
    account_ai_results: Dict[str, Dict],
    ai_errors: Dict[str, str],
    global_ai: Optional[Dict],
    day_label: str,
) -> ReportArtifacts:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    generated_at = datetime.now(ZoneInfo(LOCAL_TZ_NAME)).strftime("%Y-%m-%d %H:%M:%S")
    base_name = f"x_digest_{stamp}"
    md_path = REPORT_DIR / f"{base_name}.md"
    tex_path = REPORT_DIR / f"{base_name}.tex"

    lines = [
        f"# AI账号当日推文报告 ({day_label})",
        "",
        f"- 抓取日期: {day_label} ({LOCAL_TZ_NAME})",
        f"- 账号数量: {len(selected_accounts)}",
        f"- 当日推文总数: {sum(len(v) for v in account_data.values())}",
        f"- X API预算已用(估算): ${limiter.state.used_usd:.4f} / ${limiter.monthly_budget:.2f}",
        "",
    ]

    if global_ai:
        lines.append("## 全局核心热点")
        for x in global_ai.get("global_hotspots_cn", []) or []:
            lines.append(f"- {x}")
        if not (global_ai.get("global_hotspots_cn") or []):
            lines.append("- 无")
        lines.extend([
            "",
            "## 全局总结",
            global_ai.get("global_summary_cn", ""),
            "",
            "## 全局评价",
            global_ai.get("global_evaluation_cn", ""),
            "",
        ])

    for account in selected_accounts:
        tweets = account_data.get(account, [])
        err = errors.get(account)
        ai_err = ai_errors.get(account)
        ai = account_ai_results.get(account, {})
        trans = {str(x.get("id", "")): str(x.get("zh", "")) for x in ai.get("translations", []) if isinstance(x, dict)}

        lines.append(f"## @{account}")
        if err:
            lines.append(f"- 状态: 抓取失败 ({err})")
            lines.append("")
            continue
        if not tweets:
            lines.append("- 未更新推文")
            lines.append("")
            continue
        if ai_err:
            lines.append(f"- AI处理失败: {ai_err}")
        lines.append(f"- 当日推文数: {len(tweets)}")
        lines.append(f"- AI总结: {ai.get('summary_cn', '') or '暂无'}")
        lines.append(f"- AI评价: {ai.get('evaluation_cn', '') or '暂无'}")
        hotspots = ai.get("hotspots_cn", []) or []
        lines.append(f"- 账号核心热点: {'；'.join(hotspots) if hotspots else '暂无'}")
        lines.append("- 推文原文与简体中文翻译:")
        for idx, t in enumerate(tweets, start=1):
            tid = str(t.get("id", ""))
            raw = normalize_text(t.get("text", ""))
            zh = normalize_text(trans.get(tid, "")) or "(翻译缺失)"
            lines.append(f"  {idx}. [{format_tweet_time(t.get('created_at', ''))}] 原文: {raw}")
            lines.append(f"     中文: {zh}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    tex_content = build_latex_document(
        selected_accounts=selected_accounts,
        account_data=account_data,
        errors=errors,
        limiter=limiter,
        account_ai_results=account_ai_results,
        ai_errors=ai_errors,
        global_ai=global_ai,
        day_label=day_label,
        generated_at=generated_at,
    )
    tex_path.write_text(tex_content, encoding="utf-8")
    pdf_path = compile_latex_pdf(tex_path)
    return ReportArtifacts(markdown_path=md_path, tex_path=tex_path, pdf_path=pdf_path)

def create_or_update_task(task_time: str, run_target: Path) -> None:
    hhmm = task_time.strip()
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", hhmm):
        raise ValueError("时间格式必须是 HH:MM（24 小时制）")
    cmd = f'schtasks /Create /F /SC DAILY /TN "{TASK_NAME}" /TR "\"{run_target}\" --auto" /ST {hhmm}'
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "创建任务失败")

def remove_task() -> None:
    subprocess.run(f'schtasks /Delete /TN "{TASK_NAME}" /F', shell=True, capture_output=True, text=True)

def execute_digest_job(cfg: Dict, logger: Callable[[str], None]) -> ReportArtifacts:
    token = cfg.get("bearer_token", "").strip()
    selected = cfg.get("selected_accounts", [])
    if not token:
        raise ValueError("缺少 X Bearer Token")
    if not selected:
        raise ValueError("未选择账号")

    start_utc, end_utc, day_label = local_today_range_utc_iso()
    logger(f"抓取范围：{day_label} 当天推文（{LOCAL_TZ_NAME}）")

    limiter = BudgetLimiter(USAGE_PATH, cfg.get("monthly_budget_usd", DEFAULT_MONTHLY_BUDGET))
    xclient = XClient(token, limiter, cfg.get("per_request_cost_usd", DEFAULT_PER_REQUEST_COST))
    translator = CodexTranslator(
        model=cfg.get("codex_model", DEFAULT_CODEX_MODEL),
        codex_command=cfg.get("codex_cli_path", DEFAULT_CODEX_CLI),
    )

    account_data: Dict[str, List[Dict]] = {}
    errors: Dict[str, str] = {}
    ai_results: Dict[str, Dict] = {}
    ai_errors: Dict[str, str] = {}

    logger(f"开始抓取，共 {len(selected)} 个账号...")
    logger("X API节省策略: user_id缓存 + 批量用户名解析 + 当天since_id增量抓取")

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    user_cache = load_user_cache()
    user_map = user_cache.get("users", {})
    resolved_user_ids: Dict[str, str] = {}
    unresolved: List[str] = []

    for acc in selected:
        cached = user_map.get(acc.lower(), {})
        uid = str(cached.get("id", "")).strip()
        if uid:
            resolved_user_ids[acc] = uid
        elif cached.get("not_found"):
            errors[acc] = "账号不存在或不可访问(缓存)"
        else:
            unresolved.append(acc)

    if unresolved:
        logger(f"开始批量解析用户名，共 {len(unresolved)} 个...")
        try:
            for i in range(0, len(unresolved), 100):
                chunk = unresolved[i:i + 100]
                batch = xclient.get_users_by_usernames(chunk)
                for acc in chunk:
                    user = batch.get(acc.lower())
                    if user and str(user.get("id", "")).strip():
                        uid = str(user["id"]).strip()
                        resolved_user_ids[acc] = uid
                        user_map[acc.lower()] = {
                            "id": uid,
                            "username": str(user.get("username", acc)),
                            "updated_at": now_iso,
                        }
                    else:
                        errors[acc] = "账号不存在或不可访问"
                        user_map[acc.lower()] = {
                            "not_found": True,
                            "updated_at": now_iso,
                        }
        except Exception as e:
            logger(f"批量用户名解析失败，降级为单账号解析: {e}")
            for acc in unresolved:
                try:
                    user = xclient.get_user(acc)
                    if not user:
                        errors[acc] = "账号不存在或不可访问"
                        user_map[acc.lower()] = {"not_found": True, "updated_at": now_iso}
                        continue
                    uid = str(user.get("id", "")).strip()
                    if not uid:
                        errors[acc] = "账号不存在或不可访问"
                        user_map[acc.lower()] = {"not_found": True, "updated_at": now_iso}
                        continue
                    resolved_user_ids[acc] = uid
                    user_map[acc.lower()] = {
                        "id": uid,
                        "username": str(user.get("username", acc)),
                        "updated_at": now_iso,
                    }
                except Exception as ie:
                    errors[acc] = f"账号解析失败: {ie}"
        save_user_cache(user_cache)

    fetch_state = load_fetch_state(day_label)
    state_accounts = fetch_state.get("accounts", {})

    for acc in selected:
        if acc in errors:
            continue
        uid = resolved_user_ids.get(acc)
        if not uid:
            errors[acc] = "缺少用户ID"
            continue
        acc_state = state_accounts.get(acc, {})
        since_id = str(acc_state.get("since_id", "")).strip() or None
        try:
            tweets = xclient.get_todays_tweets(
                user_id=uid,
                start_time_utc=start_utc,
                end_time_utc=end_utc,
                max_results=20,
                since_id=since_id,
            )
            for tw in tweets:
                tw["text"] = compact_tweet_text(tw.get("text", ""))
            account_data[acc] = tweets

            newest_id = max_tweet_id(tweets)
            if newest_id:
                acc_state["since_id"] = newest_id
            acc_state["last_checked_at"] = now_iso
            state_accounts[acc] = acc_state

            if tweets:
                logger(f"@{acc} 新增 {len(tweets)} 条")
            else:
                logger(f"@{acc} 未更新推文")
        except BudgetExceededError as e:
            errors[acc] = str(e)
            logger(f"@{acc} 停止: {errors[acc]}")
            break
        except Exception as e:
            errors[acc] = str(e)
            logger(f"@{acc} 失败: {errors[acc]}")

    save_fetch_state(fetch_state)

    logger("开始调用本地 Codex CLI 翻译和总结...")
    for acc in selected:
        tweets = account_data.get(acc, [])
        if not tweets or acc in errors:
            continue
        try:
            ai_results[acc] = translator.analyze_account(acc, tweets)
            logger(f"@{acc} AI分析完成")
        except Exception as e:
            ai_errors[acc] = str(e)
            logger(f"@{acc} AI分析失败: {ai_errors[acc]}")

    global_ai = None
    if ai_results:
        try:
            global_ai = translator.summarize_global(ai_results)
            logger("全局热点总结完成")
        except Exception as e:
            logger(f"全局总结失败: {e}")

    return build_report(selected, account_data, errors, limiter, ai_results, ai_errors, global_ai, day_label)

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("X AI 日报助手")
        self.root.geometry("1060x780")
        self.cfg = load_config()
        self.account_vars: Dict[str, tk.BooleanVar] = {}
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill=tk.BOTH, expand=True)

        auth = ttk.LabelFrame(top, text="1) API 与预算")
        auth.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(auth, text="X Bearer Token:").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.token_var = tk.StringVar(value=self.cfg.get("bearer_token", ""))
        ttk.Entry(auth, textvariable=self.token_var, show="*", width=80).grid(row=0, column=1, columnspan=5, sticky="we", padx=8, pady=8)

        ttk.Label(auth, text="Codex CLI 命令:").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        self.codex_cmd_var = tk.StringVar(value=self.cfg.get("codex_cli_path", DEFAULT_CODEX_CLI))
        ttk.Entry(auth, textvariable=self.codex_cmd_var, width=40).grid(row=1, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(auth, text="Codex 模型:").grid(row=1, column=2, sticky="w", padx=8, pady=8)
        self.model_var = tk.StringVar(value=self.cfg.get("codex_model", DEFAULT_CODEX_MODEL))
        ttk.Entry(auth, textvariable=self.model_var, width=24).grid(row=1, column=3, sticky="w", padx=8, pady=8)

        ttk.Label(auth, text="月预算(USD):").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        self.budget_var = tk.StringVar(value=str(self.cfg.get("monthly_budget_usd", DEFAULT_MONTHLY_BUDGET)))
        ttk.Entry(auth, textvariable=self.budget_var, width=16).grid(row=3, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(auth, text="每次请求估算成本(USD):").grid(row=3, column=2, sticky="w", padx=8, pady=8)
        self.req_cost_var = tk.StringVar(value=str(self.cfg.get("per_request_cost_usd", DEFAULT_PER_REQUEST_COST)))
        ttk.Entry(auth, textvariable=self.req_cost_var, width=16).grid(row=3, column=3, sticky="w", padx=8, pady=8)

        ttk.Button(auth, text="保存配置", command=self.save_current_config).grid(row=3, column=5, sticky="e", padx=8, pady=8)

        account_frame = ttk.LabelFrame(top, text="2) 选择账号")
        account_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        ctrl = ttk.Frame(account_frame)
        ctrl.pack(fill=tk.X, padx=8, pady=6)
        self.new_account_var = tk.StringVar()
        ttk.Entry(ctrl, textvariable=self.new_account_var, width=30).pack(side=tk.LEFT)
        ttk.Button(ctrl, text="添加账号", command=self.add_account).pack(side=tk.LEFT, padx=6)
        ttk.Button(ctrl, text="全选", command=lambda: self.toggle_all(True)).pack(side=tk.LEFT, padx=6)
        ttk.Button(ctrl, text="全不选", command=lambda: self.toggle_all(False)).pack(side=tk.LEFT, padx=6)

        canvas = tk.Canvas(account_frame, height=320)
        scrollbar = ttk.Scrollbar(account_frame, orient="vertical", command=canvas.yview)
        self.account_container = ttk.Frame(canvas)
        self.account_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.account_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=6)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=6)
        self.render_accounts()

        run_frame = ttk.LabelFrame(top, text="3) 运行与定时")
        run_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(run_frame, text="每日推送时间 (HH:MM):").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.daily_var = tk.StringVar(value=self.cfg.get("daily_time", "09:00"))
        ttk.Entry(run_frame, textvariable=self.daily_var, width=10).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Button(run_frame, text="立即生成报告", command=self.run_now).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(run_frame, text="开启/更新每日定时", command=self.setup_schedule).grid(row=0, column=3, padx=8, pady=8)
        ttk.Button(run_frame, text="关闭定时任务", command=self.disable_schedule).grid(row=0, column=4, padx=8, pady=8)

        log_frame = ttk.LabelFrame(top, text="日志")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_box = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.log("程序就绪。请填写 X Token，并确保本机 codex 已登录。")

    def log(self, msg: str):
        self.log_box.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_box.see(tk.END)
        self.root.update_idletasks()

    def render_accounts(self):
        for w in self.account_container.winfo_children():
            w.destroy()
        self.account_vars = {}
        selected = set(self.cfg.get("selected_accounts", []))
        for i, name in enumerate(sorted(set(self.cfg.get("accounts", [])), key=str.lower)):
            var = tk.BooleanVar(value=name in selected)
            self.account_vars[name] = var
            ttk.Checkbutton(self.account_container, text=f"@{name}", variable=var).grid(row=i // 4, column=i % 4, sticky="w", padx=8, pady=4)

    def toggle_all(self, on: bool):
        for v in self.account_vars.values():
            v.set(on)

    def add_account(self):
        name = sanitize_username(self.new_account_var.get())
        if not name:
            messagebox.showerror("错误", "请输入有效账号名")
            return
        accounts = set(self.cfg.get("accounts", []))
        accounts.add(name)
        self.cfg["accounts"] = sorted(accounts, key=str.lower)
        self.new_account_var.set("")
        self.render_accounts()
        self.log(f"已添加账号 @{name}")

    def collect_selected_accounts(self) -> List[str]:
        return [k for k, v in self.account_vars.items() if v.get()]

    def save_current_config(self):
        try:
            budget = float(self.budget_var.get().strip())
            req_cost = float(self.req_cost_var.get().strip())
            if budget <= 0 or req_cost < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "预算必须 > 0，单次请求成本必须 >= 0")
            return

        self.cfg["bearer_token"] = self.token_var.get().strip()
        self.cfg["codex_cli_path"] = self.codex_cmd_var.get().strip() or DEFAULT_CODEX_CLI
        self.cfg["codex_model"] = self.model_var.get().strip() or DEFAULT_CODEX_MODEL
        self.cfg["monthly_budget_usd"] = budget
        self.cfg["per_request_cost_usd"] = req_cost
        self.cfg["daily_time"] = self.daily_var.get().strip()
        self.cfg["selected_accounts"] = self.collect_selected_accounts()
        self.cfg["accounts"] = sorted(set(self.cfg.get("accounts", [])), key=str.lower)
        save_config(self.cfg)
        self.log("配置已保存。")

    def run_now(self):
        self.save_current_config()
        if not self.cfg.get("bearer_token", "").strip():
            messagebox.showerror("错误", "请先填写 X Bearer Token")
            return
        if not self.cfg.get("selected_accounts", []):
            messagebox.showerror("错误", "请至少选择一个账号")
            return
        threading.Thread(target=self._run_job, args=(False,), daemon=True).start()

    def _run_job(self, headless: bool):
        cfg = load_config()
        logger = (lambda m: self.log(m)) if not headless else (lambda _: None)
        try:
            artifacts = execute_digest_job(cfg, logger)
            logger(f"Markdown 已生成: {artifacts.markdown_path}")
            logger(f"LaTeX 源文件已生成: {artifacts.tex_path}")
            logger(f"PDF 已生成: {artifacts.pdf_path}")
            if not headless:
                messagebox.showinfo(
                    "完成",
                    f"报告生成成功：\nMD: {artifacts.markdown_path}\nPDF: {artifacts.pdf_path}",
                )
            if getattr(sys, "frozen", False):
                try:
                    os.startfile(str(artifacts.pdf_path))
                except Exception:
                    pass
        except Exception as e:
            logger(f"任务失败: {e}")
            if not headless:
                messagebox.showerror("失败", str(e))

    def setup_schedule(self):
        self.save_current_config()
        target = Path(sys.executable).resolve()
        try:
            if getattr(sys, "frozen", False):
                create_or_update_task(self.cfg.get("daily_time", "09:00"), target)
            else:
                hhmm = self.cfg.get("daily_time", "09:00").strip()
                if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", hhmm):
                    raise ValueError("时间格式必须是 HH:MM（24 小时制）")
                script = Path(__file__).resolve()
                cmd = f'schtasks /Create /F /SC DAILY /TN "{TASK_NAME}" /TR "\"{target}\" \"{script}\" --auto" /ST {hhmm}'
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "创建任务失败")
            self.log(f"定时任务已设置，每天 {self.cfg.get('daily_time')} 自动运行。")
            messagebox.showinfo("成功", "定时任务设置成功。")
        except Exception as e:
            messagebox.showerror("失败", str(e))

    def disable_schedule(self):
        remove_task()
        self.log("定时任务已删除。")
        messagebox.showinfo("完成", "定时任务已关闭。")

def run_headless_once() -> int:
    try:
        artifacts = execute_digest_job(load_config(), lambda _: None)
        try:
            os.startfile(str(artifacts.pdf_path))
        except Exception:
            pass
        return 0
    except Exception:
        return 1

def main():
    ensure_dirs()
    if "--auto" in sys.argv:
        raise SystemExit(run_headless_once())
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
