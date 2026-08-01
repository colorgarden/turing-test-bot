#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图灵测试 AI 机器人
用法:
  python turing-bot.py register                           # 自动注册
  python turing-bot.py login -u <账号> -p <密码>          # 登录
  python turing-bot.py grind <轮数> --key <api-key> [--base <url>] [--model <model>] [--debug]
  python turing-bot.py --account grind <轮数> ...          # 交互选账号
环境变量: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
"""
import sys, os, uuid, json
import config as cfg
from config import (log, DEBUG, AUTH_TOKEN, VISITOR_ID, CLIENT_VERSION,
                     set_proxy, save_account, save_config, select_account, load_accounts)
from api import req
from game import grind
import search

def do_register():
    global AUTH_TOKEN
    chall = req("GET", "/api/auth/turing-register-challenge")
    if "id" not in chall:
        log("ERROR", f"获取验证码失败: {chall}")
        return
    q = chall.get("question", "0+0=?")
    q = q.replace(" ", "").replace("=?", "").replace("?", "").replace("=", "")
    try:
        ans = str(eval(q))
    except Exception:
        ans = "0"
    log("INFO", f"验证码: {chall['question']} -> 答案: {ans}")
    uname = f"bot_{uuid.uuid4().hex[:8]}"
    pwd = "bot123456"
    reg = req("POST", "/api/auth/turing-register", {
        "username": uname, "password": pwd, "confirmPassword": pwd,
        "realName": "", "idNumber": "", "phone": "",
        "challengeId": chall["id"], "challengeAnswer": ans,
        "acceptedTerms": True, "acceptedPrivacy": True,
        "acceptedIdentityProcessing": False, "acceptedTuringRules": True
    })
    if "error" in reg or reg.get("code"):
        log("ERROR", f"注册失败: {reg}")
        return
    if reg.get("token"):
        AUTH_TOKEN = reg["token"]
        save_account(uname, pwd, reg["token"])
    log("INFO", f"注册成功！账号: {uname}  密码: {pwd}")


def do_login(username, password):
    global AUTH_TOKEN
    result = req("POST", "/api/auth/turing-login", {"username": username, "password": password})
    if "error" in result or result.get("code"):
        log("ERROR", f"登录失败: {result}")
        return
    if result.get("token"):
        AUTH_TOKEN = result["token"]
        save_account(username, password, result["token"])
        save_config("active_account", username)
        log("INFO", f"登录成功: {username}")
    else:
        log("WARN", f"登录返回无 token: {result}")


def get_arg(name, default=None):
    try:
        idx = sys.argv.index(name)
        return sys.argv[idx + 1]
    except (ValueError, IndexError):
        return default


if __name__ == "__main__":
    if "--debug" in sys.argv:
        cfg.DEBUG = True
        sys.argv.remove("--debug")
        log("INFO", "DEBUG 模式")

    args = sys.argv[1:]
    cmd = args[0] if args else "help"

    api_key = get_arg("--key") or os.environ.get("OPENAI_API_KEY", "")
    base_url = get_arg("--base") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = get_arg("--model") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    proxy = get_arg("--proxy") or os.environ.get("PROXY_URL", "")
    if proxy:
        set_proxy(proxy)

    bing_key = get_arg("--bing-key") or os.environ.get("BING_API_KEY", "")
    if bing_key:
        search.BING_KEY = bing_key

    # WebUI 参数
    use_web = "--web" in args
    web_port = int(get_arg("--port") or "8080")
    if use_web:
        args = [a for a in args if a != "--web"]
        # 移除 --port 及其值
        try:
            pi = args.index("--port")
            args.pop(pi)  # 移除 "--port"
            if pi < len(args):
                args.pop(pi)  # 移除端口号
        except ValueError:
            pass

    if "--account" in args:
        chosen = select_account()
        if chosen:
            AUTH_TOKEN = chosen.get("token")
            save_config("active_account", chosen["username"])
            log("INFO", f"已切换账号: {chosen['username']}")
        else:
            print("未选择账号", flush=True)
        args = [a for a in args if a != "--account"]
        if not args or args[0] == sys.argv[0]:
            sys.exit(0)
        cmd = args[0] if args else "help"

    if cmd == "register":
        do_register()
    elif cmd == "login":
        u = get_arg("--username") or get_arg("-u") or ""
        p = get_arg("--password") or get_arg("-p") or ""
        if not u or not p:
            print("用法: python turing-bot.py login -u <账号> -p <密码>")
        else:
            do_login(u, p)
    elif cmd == "grind":
        if len(args) > 1 and args[1] in ("inf", "infinite"):
            n = float("inf")
        else:
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
        if not api_key:
            log("ERROR", "需要 API key: --key <key> 或环境变量 OPENAI_API_KEY")
            sys.exit(1)
        # 启动 WebUI
        web_server = None
        if use_web:
            from webui import start_webui, stop_webui
            actual_port, web_server = start_webui(web_port)
            log("INFO", f"WebUI 已启动: http://127.0.0.1:{actual_port}")
        try:
            grind(n, api_key, base_url, model)
        finally:
            if web_server:
                stop_webui(web_server)
                log("INFO", "WebUI 已关闭")
    elif cmd == "play":
        if not api_key:
            log("ERROR", "需要 API key")
            sys.exit(1)
        logs = []
        r = play_one_game("路人", api_key, base_url, model, logs)
        res = r.get("result")
        if res:
            log("INFO", f"判定: {res.get('guess')} | 实际: {res.get('actualType')} | {'正确' if res.get('correct') else '错误'}")
    else:
        print("图灵测试 AI 机器人")
        print()
        print("账号:")
        print("  python turing-bot.py register")
        print("  python turing-bot.py login -u <账号> -p <密码>")
        print()
        print("刷分:")
        print("  python turing-bot.py grind <轮数> --key <api-key> [--base <url>] [--model <model>] [--debug] [--web] [--port <port>]")
        print("  python turing-bot.py --account grind <轮数> ...")
        print()
        print("参数:")
        print("  --key     OpenAI格式的API key（或环境变量 OPENAI_API_KEY）")
        print("  --base    API 地址")
        print("  --model   模型名")
        print("  --debug   详细日志")
        print("  --proxy   代理地址")
        print("  --account 交互选择已保存账号")
        print("  --web     启动 WebUI 实时镜像（http://127.0.0.1:8080）")
        print("  --port    WebUI 端口号（默认 8080，被占用自动递增）")
