"""save_anything 共享模块:配置、编码、笔记读写与解析。

纯标准库实现,兼容 Python 3.9+。
"""

import os
import sys
import time
from pathlib import Path

# ---- 目录与常量 ----

BASE_DIR = Path(__file__).resolve().parent
INBOX_DIR = BASE_DIR / "inbox"
NOTES_DIR = BASE_DIR / "notes"
ARCHIVE_DIR = BASE_DIR / "archive"
CONFIG_FILE = BASE_DIR / "config.env"

# DeepSeek API(Step 2 接入调用)
ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"  # 固定用稳定别名,不写具体版本名(版本路由由平台管理)
TIMEOUT = 30
MAX_RETRIES = 2
MAX_TOKENS = 300

# 内容参数
SUMMARY_MAX = 30      # 摘要字数上限(一个中文字符计 1)
API_MAX_CHARS = 6000  # 发给 API 的最大字符数,笔记正文不截断
TAG_MAX = 4
TAG_MIN = 2

# 笔记头部字段,顺序即输出顺序
HEADER_FIELDS = ("标题", "摘要", "标签", "理由", "保存时间", "上次回顾")


class DeepseekError(Exception):
    """DeepSeek API 调用失败(已按策略重试过)。"""


# ---- 控制台编码 ----

def setup_console():
    """把 stdin/stdout/stderr 统一为 UTF-8。

    Windows 中文环境:真控制台下 Python 3.6+ 走宽字符 API,中文没问题;
    但 Git Bash(mintty) 下 stdin/stdout 是管道,input() 收到的 UTF-8 字节
    会被按 GBK 解码,用户输入的中文会变乱码写进笔记——所以 stdin 必须一起改。
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # 极端环境下降级,不崩


# ---- 时间 ----

def now_str():
    """"%Y-%m-%d %H:%M",定长格式,字符串排序即时间排序。"""
    return time.strftime("%Y-%m-%d %H:%M")


def file_ts():
    """"%Y%m%d_%H%M%S",用于重名文件加后缀。"""
    return time.strftime("%Y%m%d_%H%M%S")


# ---- 目录与配置 ----

def ensure_dirs():
    for d in (INBOX_DIR, NOTES_DIR, ARCHIVE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_api_key():
    """API key:环境变量 DEEPSEEK_API_KEY 优先,其次读 config.env。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if CONFIG_FILE.exists():
        try:
            lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            if name.strip() == "DEEPSEEK_API_KEY" and value.strip():
                return value.strip()
    sys.exit("没有找到 DeepSeek API key。两种配置方式任选:\n"
             "  1. 设置环境变量 DEEPSEEK_API_KEY\n"
             "  2. 在项目根目录 config.env 里写一行 DEEPSEEK_API_KEY=sk-...")


# ---- 文件读写(编码) ----

def read_text_file(path):
    """读文本文件:先 utf-8-sig(兼容 BOM),再 gb18030(GBK 超集)兜底。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码(既不是 UTF-8 也不是 GBK):%s" % path.name)


def write_text_file(path, text):
    """写文本:显式 UTF-8 + newline="\\n"(Windows 下默认会转成 \\r\\n)。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---- 笔记读写与解析 ----

def build_note(meta, body):
    """按固定格式拼装笔记:--- 头部六字段 --- 原文全文。"""
    lines = ["---"]
    for field in HEADER_FIELDS:
        lines.append("%s: %s" % (field, str(meta.get(field, "")).strip()))
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.rstrip() + "\n"


def parse_note(text):
    """解析笔记为 {"meta": {字段: 值}, "body": 正文}。

    容错:仅首行是 --- 才认为有头部,边界 = 第二个独立 --- 行;否则
    整文件视为正文、元数据全缺省。字段按第一个冒号切分,同时容忍全角
    冒号;正文里的 --- 行不受影响。
    """
    meta = {}
    body = text
    if text.startswith("---"):
        lines = text.splitlines()
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            for line in lines[1:end]:
                if not line.strip():
                    continue
                for sep in (":", ":"):
                    if sep in line:
                        name, _, value = line.partition(sep)
                        name = name.strip()
                        if name in HEADER_FIELDS:
                            meta[name] = value.strip()
                        break
            body = "\n".join(lines[end + 1:]).lstrip("\n")
    return {"meta": meta, "body": body}


def read_note(path):
    return parse_note(read_text_file(path))


def list_notes():
    """遍历 notes/*.md,返回 [{"path", "meta", "body"}]。"""
    notes = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        try:
            parsed = read_note(path)
        except (OSError, ValueError) as e:
            print("警告:跳过无法读取的笔记 %s(%s)" % (path.name, e))
            continue
        parsed["path"] = path
        notes.append(parsed)
    return notes


# ---- 路径 ----

def unique_path(directory, stem, suffix):
    """目录内不冲突的路径:冲突则循环加时间戳后缀直至可用。"""
    path = directory / (stem + suffix)
    while path.exists():
        path = directory / ("%s_%s%s" % (stem, file_ts(), suffix))
    return path
