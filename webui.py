# -*- coding: utf-8 -*-
"""WebUI：SSE 广播 + 静态服务 + 状态快照（纯标准库）"""
import json, threading, time, os, http.server

# ============ 全局状态 ============
_clients = []               # list of wfile objects
_clients_lock = threading.Lock()
_log_buffer = []            # 最近 500 条日志
_log_buffer_lock = threading.Lock()
_game_state = {             # 当前游戏状态快照
    "account": None,        # {"type":"registered","username":"..."}
    "playerId": "?",
    "roomId": None,
    "round": 0,
    "total": 0,
    "queue": None,          # "排队 #3 (已等 12s)"
    "stats": {"games": 0, "correct": 0, "actual_ai": 0, "actual_human": 0, "errors": 0},
    "game_start": None,     # 本局开始时间戳 (time.time())
    "connected": False,
    "phase": "idle",        # idle / queuing / chatting / ended
    "messages": [],         # 本局聊天记录 [{sender,text,sequence}]
}
_state_lock = threading.Lock()

# ============ 人工接管 ============
_llm_paused = False           # True=中断LLM，人工接管
_pause_lock = threading.Lock()
_manual_queue = []            # 人工操作队列 [{action:"send"|"guess", ...}]
_manual_lock = threading.Lock()

def is_llm_paused():
    with _pause_lock:
        return _llm_paused

def set_llm_paused(paused):
    global _llm_paused
    with _pause_lock:
        _llm_paused = paused
    emit({"type": "llm_state", "paused": paused})

def pop_manual_actions():
    """取出并清空人工操作队列（供 game.py 轮询）"""
    with _manual_lock:
        acts = _manual_queue[:]
        _manual_queue.clear()
    return acts

def push_manual_action(action):
    with _manual_lock:
        _manual_queue.append(action)

# ============ 广播 ============
def emit(event):
    """广播 JSON 事件给所有已连接 SSE 客户端，失败客户端自动移除"""
    data = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
    dead = []
    with _clients_lock:
        for client in _clients[:]:
            try:
                client.write(data)
                client.flush()
            except Exception:
                dead.append(client)
        for d in dead:
            try: _clients.remove(d)
            except ValueError: pass

def _append_log(entry):
    global _log_buffer
    with _log_buffer_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) > 500:
            _log_buffer = _log_buffer[-500:]

def update_state(**kwargs):
    """线程安全地更新游戏状态"""
    global _game_state
    with _state_lock:
        _game_state.update(kwargs)

def get_state_snapshot():
    """获取当前状态快照（给 /state 端点用）"""
    with _state_lock:
        state = dict(_game_state)
    with _log_buffer_lock:
        logs = list(_log_buffer)
    state["llm_paused"] = is_llm_paused()
    return {"state": state, "logs": logs}

# ============ HTTP Handler ============
_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "turing-chat.html")

class _SSEHandler(http.server.BaseHTTPRequestHandler):
    """三个端点：GET / 返回 HTML，GET /events SSE 流，GET /state JSON 快照"""

    def handle_one_request(self):
        """覆写以静默客户端突然断连错误（Windows ConnectionAbortedError）"""
        try:
            return super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError):
            pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._serve_file(_HTML_PATH, "text/html; charset=utf-8")
        elif path == "/events":
            self._serve_sse()
        elif path == "/state":
            self._serve_state()
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/action":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        action = body.get("action", "")
        ok = True
        phase = _game_state.get("phase", "idle")
        if phase != "chatting":
            ok = False  # 匹配/空闲阶段禁止人工操作
        elif action == "toggle_llm":
            set_llm_paused(not is_llm_paused())
        elif action == "send":
            push_manual_action({"action": "send", "text": body.get("text", "")})
        elif action == "guess":
            push_manual_action({"action": "guess", "value": body.get("value", "human")})
        else:
            ok = False
        resp = json.dumps({"ok": ok, "paused": is_llm_paused()}, ensure_ascii=False).encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(resp)

    def _serve_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_error(404, "turing-chat.html not found")

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        wfile = self.wfile
        with _clients_lock:
            _clients.append(wfile)
        try:
            # 发初始连接确认
            wfile.write(b": connected\n\n")
            wfile.flush()
            # 心跳保活
            while True:
                time.sleep(15)
                wfile.write(b": heartbeat\n\n")
                wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _clients_lock:
                try: _clients.remove(wfile)
                except ValueError: pass

    def _serve_state(self):
        snapshot = get_state_snapshot()
        body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # 静默 HTTP 访问日志

# ============ 服务启停 ============
def start_webui(port=8080):
    """启动 WebUI 服务 daemon 线程，返回 (实际端口, server 对象)"""
    server = None
    for offset in range(100):
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", port + offset), _SSEHandler)
            actual_port = port + offset
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError(f"无法绑定端口 {port}-{port+99}，全部被占用")

    t = threading.Thread(target=server.serve_forever, name="webui", daemon=True)
    t.start()
    return actual_port, server

def stop_webui(server):
    """优雅关闭 WebUI 服务"""
    if server:
        try:
            server.shutdown()
        except Exception:
            pass
