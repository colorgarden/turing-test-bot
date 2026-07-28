# -*- coding: utf-8 -*-
"""配置、日志、账号管理"""
import sys, json, os, uuid, datetime

def ts():
    """本地时间戳 HH:MM:SS"""
    return datetime.datetime.now().strftime("%H:%M:%S")

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime.log")
_log_initialized = False

def log(level, msg):
    """统一日志格式: [HH:MM:SS] [LEVEL] message，实时写文件"""
    global _log_initialized
    prefix = f"[{ts()}] [{level}] "
    if "\n" in msg:
        indent = " " * len(prefix)
        msg = msg.replace("\n", "\n" + indent)
    line = f"{prefix}{msg}"
    print(line, flush=True)
    try:
        mode = "w" if not _log_initialized else "a"
        _log_initialized = True
        with open(LOG_FILE, mode, encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

BASE = "https://www.anyanygame.com"
VISITOR_ID = str(uuid.uuid4())
CLIENT_VERSION = "1ad72dd475b4"
AUTH_TOKEN = None
DEBUG = False
ACCOUNT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account.json")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(key, value):
    cfg = load_config()
    cfg[key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)

def load_accounts():
    if os.path.exists(ACCOUNT_FILE):
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_account(username, password, token):
    accounts = load_accounts()
    accounts = [a for a in accounts if a.get("username") != username]
    accounts.append({"username": username, "password": password, "token": token})
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def select_account():
    accounts = load_accounts()
    if not accounts:
        print("暂无已保存的账号", flush=True)
        return None
    print("\n已保存的账号:")
    for i, a in enumerate(accounts):
        print(f"  [{i+1}] {a['username']}  ({a.get('password','?')})")
    try:
        choice = input("选择账号 (输入序号): ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(accounts):
            return accounts[idx]
    except (ValueError, KeyboardInterrupt):
        pass
    return None

# 启动时自动加载上一个账号
if "--account" not in sys.argv:
    cfg = load_config()
    active_user = cfg.get("active_account", "")
    accounts = load_accounts()
    if active_user:
        match = next((a for a in accounts if a["username"] == active_user), None)
    else:
        match = accounts[-1] if accounts else None
    if match:
        AUTH_TOKEN = match.get("token")
        log("INFO", f"已加载账号: {match.get('username','?')}")

# 代理
import urllib.request as _ur
_proxy_handler = None

def set_proxy(proxy_url):
    global _proxy_handler
    if proxy_url:
        _proxy_handler = _ur.ProxyHandler({"http": proxy_url, "https": proxy_url})
