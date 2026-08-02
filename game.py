# -*- coding: utf-8 -*-
"""游戏逻辑：REST轮询 + SSE房间"""
import json, time, random, uuid, ssl, socket, select, os, base64, struct
import config as cfg
from config import BASE, log, ts, save_account
from api import req
from llm import chat_completion
from search import web_search

# WebUI 广播（惰性导入，无 webui 时 emit 为 no-op）
try:
    from webui import emit, update_state
except ImportError:
    def emit(*a, **kw): pass
    def update_state(*a, **kw): pass

# ---- 裸 WebSocket（仅排队用） ----
class RawWS:
    def __init__(self, timeout=10):
        host = "www.anyanygame.com"
        path = "/api/turing/socket"
        key = base64.b64encode(os.urandom(16)).decode()
        req_str = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                   f"Connection: Upgrade\r\nPragma: no-cache\r\nCache-Control: no-cache\r\n"
                   f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36\r\n"
                   f"Upgrade: websocket\r\nOrigin: https://www.anyanygame.com\r\n"
                   f"Sec-WebSocket-Version: 13\r\n"
                   f"Accept-Encoding: gzip, deflate, br, zstd\r\n"
                   f"Accept-Language: zh-CN,zh;q=0.9\r\n"
                   f"Sec-WebSocket-Key: {key}\r\n"
                   f"Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits\r\n\r\n")
        sock = socket.create_connection((host, 443), timeout=timeout)
        ctx = ssl._create_unverified_context()
        self.ssock = ctx.wrap_socket(sock, server_hostname=host)
        self.ssock.send(req_str.encode())
        resp = b""
        while b"\r\n\r\n" not in resp: resp += self.ssock.recv(4096)
        if b"101" not in resp.split(b"\r\n")[0]:
            first = resp.split(b"\r\n")[0]
            raise Exception(f"WS handshake failed: {first}")
    def send(self, data):
        b = data.encode()
        mask_key = os.urandom(4)
        masked = bytes(b[i] ^ mask_key[i % 4] for i in range(len(b)))
        self.ssock.send(b"\x81" + self._lb(len(b), masked=True) + mask_key + masked)
    def recv(self, timeout=1):
        self.ssock.settimeout(timeout)
        try:
            h = self.ssock.recv(2)
            if len(h) < 2: raise Exception("WS EOF")
            op = h[0] & 0x0F; length = h[1] & 0x7F
            if length == 126: length = struct.unpack(">H", self.ssock.recv(2))[0]
            elif length == 127: length = struct.unpack(">Q", self.ssock.recv(8))[0]
            data = b""
            while len(data) < length: data += self.ssock.recv(length - len(data))
            if op == 0x08:
                code = "?"; reason = ""
                if length >= 2: code = str(struct.unpack(">H", data[:2])[0])
                if length > 2: reason = data[2:].decode(errors="replace")
                raise Exception(f"WS close code={code} reason={reason}")
            if op == 0x09:  # ping -> pong
                mk = os.urandom(4)
                masked = bytes(data[i] ^ mk[i % 4] for i in range(len(data)))
                self.ssock.send(b"\x8A" + self._lb(len(data), masked=True) + mk + masked)
                return self.recv(timeout)
            if op == 0x01: return data.decode()
            return None
        except socket.timeout: return None
    def close(self):
        try: self.ssock.close()
        except: pass
    @staticmethod
    def _lb(n, masked=False):
        if n < 126: return bytes([n | (0x80 if masked else 0)])
        if n < 65536: return bytes([126 | (0x80 if masked else 0)]) + struct.pack(">H", n)
        return bytes([127 | (0x80 if masked else 0)]) + struct.pack(">Q", n)

SYSTEM_PROMPT = """你是图灵测试里的真人玩家。目标：伪装真人 + 识破AI。
聊天像微信：5-20字 口语 用网络词 可错字不打句号
必须接对方的话题！对方说什么你就回应什么 不要自顾自说
对方说怪话回"?" 不要念诗/客服腔/大量emoji/结构化
聊2-3轮必须判定。AI信号：剧本独白 每句emoji 客服语气 念歌词。真人：口语 接茬 缩写 自然
判定时只回复两个字：真人 或 AI"""


def build_messages(chat_history):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in chat_history:
        if m["sender"] == "system": continue
        msgs.append({"role": "assistant" if m["sender"] == "self" else "user", "content": m["text"]})
    return msgs


def play_one_game(nickname, api_key, base_url, model, game_logs):
    # 0. 注册
    play_one_game.account_info = {"type": "guest"}
    if cfg.AUTH_TOKEN:
        last = cfg.load_accounts()
        uname = last[-1]["username"] if last else "已登录"
        play_one_game.account_info = {"type": "registered", "username": uname}
    else:
        try:
            import hashlib, base64 as _b64
            chall = req("GET", "/api/auth/turing-register-challenge?verificationClient=dual")
            altcha_raw = chall.get("altcha") or chall.get("challenge") or chall
            if isinstance(altcha_raw, str):
                altcha_raw = json.loads(_b64.b64decode(altcha_raw).decode())
            params = altcha_raw.get("challenge", altcha_raw).get("parameters", {})
            salt = _b64.b64decode(params.get("salt", ""))
            key_prefix = params.get("keyPrefix", "")
            cost = params.get("cost", 3000)
            counter = 0
            while True:
                dk = hashlib.pbkdf2_hmac("sha256", f"{counter}".encode(), salt, cost, dklen=32)
                derived = _b64.b64encode(dk).decode()
                if derived.startswith(key_prefix):
                    break
                counter += 1
            sol = _b64.b64encode(json.dumps({
                "challenge": altcha_raw.get("challenge", altcha_raw),
                "solution": {"counter": counter, "derivedKey": derived, "time": int(time.time())}
            }).encode()).decode()
            uname = f"bot_{uuid.uuid4().hex[:8]}"; pwd = "bot123456"
            reg = req("POST", "/api/auth/turing-register", {"username":uname,"password":pwd,"confirmPassword":pwd,"altcha":sol,"acceptedTerms":True,"acceptedPrivacy":True,"acceptedTuringRules":True})
            if "error" not in reg and not reg.get("code"):
                play_one_game.account_info = {"type":"registered","username":uname,"password":pwd}
                if reg.get("token"): cfg.AUTH_TOKEN = reg["token"]; save_account(uname,pwd,reg["token"])
                log("INFO", f"注册成功 账号:{uname} 密码:{pwd}")
            else: log("WARN", f"注册失败: {reg.get('error','?')}")
        except Exception as e:
            log("WARN", f"自动注册失败: {e}")

    acct = play_one_game.account_info
    log("GAME", f"[{acct.get('username', acct.get('type', '?'))}] 发起匹配 {nickname}")
    update_state(account=dict(acct), phase="queuing", playerId="?")

    # 1. start
    start_body = {"nickname": nickname, "protocolVersion": 3, "clientVersion": cfg.CLIENT_VERSION, "chatDurationSec": 600, "matchTimeoutSec": 30}
    retry = 0
    while True:
        s = req("POST", "/api/turing/start", start_body)
        code, err = s.get("code", ""), s.get("error", "")
        if code == "turing_client_outdated":
            v = s.get("serviceVersion", "")
            if v: cfg.CLIENT_VERSION = v; start_body["clientVersion"] = v; log("WARN", f"服务端版本更新，api可能变动，不保证脚本正常工作 ({v[:12]}...)"); continue
        if code == "turing_queue_full" or "503" in str(err): retry += 1; log("WAIT", f"排队满，重试 #{retry}..."); time.sleep(6); continue
        acc = s.get("player", {}).get("access", {})
        if acc.get("accountRequired") and acc.get("guestMatchesRemaining", 0) <= 0: cfg.VISITOR_ID = str(uuid.uuid4()); log("INFO", "额度用完，换游客 ID"); continue
        if "ticket" not in s: return {"error": "start 失败", "detail": s}
        break

    ticket = s.get("ticket")
    if not ticket: return {"error": "start 无 ticket", "detail": s}
    ticket_id, session_id = ticket["ticketId"], ticket["sessionId"]
    player_id = s.get("player", {}).get("playerId", "?")
    log("GAME", f"queue:排队中 #{ticket.get('queuePosition', '?')}")
    update_state(playerId=player_id, queue=f"#{ticket.get('queuePosition', '?')}")
    emit({"type": "status", "key": "queue", "value": f"#{ticket.get('queuePosition', '?')}"})

    # 2. WebSocket 排队
    try:
        ws = RawWS(timeout=10)
        ws.send(json.dumps({"type": "match.subscribe",
            "requestId": str(uuid.uuid4()), "ticketId": ticket_id, "sessionId": session_id}))
        if cfg.DEBUG: log("DEBUG", "ws: match subscribed")
    except Exception as e:
        log("WARN", f"ws connect failed ({e}), fallback REST")
        ws = None

    room_id = None
    if ws:
        try:
            while True:
                raw = ws.recv(timeout=120)
                if raw is None: continue
                if cfg.DEBUG:
                    try: log("DEBUG", f"ws <- {json.dumps(json.loads(raw), indent=2, ensure_ascii=False)[:500]}")
                    except: log("DEBUG", f"ws <- {raw[:200]}")
                try:
                    evt = json.loads(raw)
                    t = evt.get("type", "")
                    if t in ("match.subscribed", "match.update"):
                        st = evt.get("status", evt)
                        if st == "matched" or (isinstance(st, dict) and st.get("status") == "matched"):
                            room_id = evt.get("roomId") or (st.get("roomId") if isinstance(st, dict) else None)
                            if room_id: break
                        if isinstance(st, dict):
                            qp = st.get('queuePosition','?'); qd = st.get('queuedForMs',st.get('waitedMs',0))//1000
                            log("GAME", f"queue:排队 #{qp} (已等 {qd}s)")
                            update_state(queue=f"#{qp} (已等 {qd}s)")
                            emit({"type": "status", "key": "queue", "value": f"#{qp} (已等 {qd}s)"})
                        else:
                            log("GAME", f"queue:状态 {st}")
                    elif t == "match.fatal":
                        log("ERROR", f"match fatal: {evt}"); break
                except json.JSONDecodeError: pass
        except Exception as e:
            log("WARN", f"ws error: {e}")
        # 不关 WS，下面房间要用
    else:
        for _ in range(120):
            w = req("GET", f"/api/turing/match/{ticket_id}?sessionId={session_id}&wait=5000")
            st = w.get("status", "")
            if st == "matched": room_id = w["roomId"]; break
            elif st in ("queued", "waiting"):
                if st == "queued": log("GAME", f"queue:排队 #{w.get('queuePosition','?')} (已等 {w.get('queuedForMs', w.get('waitedMs', 0))//1000}s)")
            elif "error" in w: pass
            else: break
    if not room_id: req("POST", "/api/turing/leave", {"ticketId": ticket_id, "sessionId": session_id}); return {"error": "匹配超时"}

    log("GAME", f"conn:已连接 {room_id}")
    update_state(roomId=room_id, connected=True, phase="chatting")
    emit({"type": "status", "key": "connected", "value": room_id})

    # 3. 房间用 WS（有 WS 则订阅房间，否则 SSE 兜底）
    if ws:
        ws.send(json.dumps({"type":"match.unsubscribe","requestId":str(uuid.uuid4())}))
        ws.send(json.dumps({"type":"room.subscribe","requestId":str(uuid.uuid4()),
            "roomId":room_id,"sessionId":session_id,"after":0,"afterSequence":0}))
        if cfg.DEBUG: log("DEBUG", "ws: room subscribed")
    if not ws:
        import http.client as _hc
        path = f"/api/turing/rooms/{room_id}/events?sessionId={session_id}&after=0&afterSequence=0"
        conn = _hc.HTTPSConnection("www.anyanygame.com", context=ssl._create_unverified_context())
        conn.request("GET", path, headers={
            "accept": "text/event-stream", "x-visitor-id": cfg.VISITOR_ID,
            "referer": BASE + "/turing-test", "origin": BASE,
            "user-agent": "Mozilla/5.0", "cache-control": "no-cache",
        })
        resp = conn.getresponse(); sock = conn.sock; buffer = ""

    # 状态
    messages, seen_seq = [], set()
    guess_state, result = None, None
    last_llm_call, last_replied_seq, game_start = 0, 0, None
    we_locked, opp_guess_done, phase = False, False, "chatting"
    buffer, sock = "", None

    # WS 后台接收线程（不阻塞主循环和 LLM）
    ws_queue = []; ws_lock = __import__('threading').Lock(); ws_alive = [True]
    def ws_recv_thread():
        while ws_alive[0]:
            try:
                raw = ws.recv(timeout=5)
                if raw:
                    evt = json.loads(raw)
                    evt["_recv_at"] = time.time()
                    with ws_lock: ws_queue.append(evt)
            except Exception:
                ws_alive[0] = False; break
    if ws: __import__('threading').Thread(target=ws_recv_thread, daemon=True).start()

    try:
        first_loop = True
        while phase != "ended":
            if first_loop and random.random() < 0.5:
                g = random.choice(["嗨", "你好啊", "在吗", "有人吗", "来了来了"])
                req("POST", f"/api/turing/rooms/{room_id}/messages", {"sessionId": session_id, "text": g})
                log("CHAT", f"send:抢先: {g}")
                emit({"type": "chat", "sender": "self", "text": g, "sequence": 0})
            first_loop = False

            # 读事件（WS 优先）
            if ws:
                with ws_lock: evts = ws_queue[:]; ws_queue.clear()
                for evt in evts:
                    if cfg.DEBUG:
                        delay = time.time() - evt.pop("_recv_at", time.time())
                        log("DEBUG", f"ws <- (+{delay:.1f}s) {json.dumps(evt, indent=2, ensure_ascii=False)[:400]}")
                    t = evt.get("type", "")
                    if t in ("room.update", "room.subscribed"):
                        room = evt.get("room", evt)
                        for msg in room.get("messages", []):
                            if msg["sequence"] not in seen_seq:
                                seen_seq.add(msg["sequence"]); messages.append(msg)
                                if msg["sender"] != "self":
                                    log("CHAT", f"recv:{msg['sender']}: {msg['text'][:60]}")
                                    if msg["sender"] == "system":
                                        emit({"type": "status", "key": "system", "value": msg["text"]})
                                    else:
                                        emit({"type": "chat", "sender": "opponent", "text": msg["text"], "sequence": msg["sequence"]})
                        if "guessState" in room: guess_state = room["guessState"]
                        if "result" in room and room["result"]: result=room["result"]; phase="ended"; log("GAME","end:结果已出"); emit({"type":"result","result":room["result"]})
                        if room.get("state")=="ended": phase="ended"; log("GAME","end:游戏结束"); emit({"type":"result","result":room.get("result",{})})
                    elif t in ("room.fatal","match.fatal"): log("ERROR",f"fatal: {evt}"); phase="ended"
                if not ws_alive[0]: log("ERROR","ws断线"); phase="ended"; break
            else:
                try:
                    ready, _, _ = select.select([sock], [], [], 0.5)
                    if ready:
                        chunk = sock.recv(4096)
                        if not chunk: log("ERROR", "sse关闭"); break
                        buffer += chunk.decode("utf-8", errors="replace")
                except (socket.timeout, OSError, TypeError): pass

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1); line = line.strip()
                    if line.startswith("data:"):
                        ds = line[5:].strip()
                        if not ds: continue
                        try:
                            evt = json.loads(ds)
                            for msg in evt.get("messages", []):
                                if msg["sequence"] not in seen_seq:
                                    seen_seq.add(msg["sequence"]); messages.append(msg)
                                    if msg["sender"] != "self":
                                        log("CHAT", f"recv:{msg['sender']}: {msg['text'][:60]}")
                                        if msg["sender"] == "system":
                                            emit({"type": "status", "key": "system", "value": msg["text"]})
                                        else:
                                            emit({"type": "chat", "sender": "opponent", "text": msg["text"], "sequence": msg["sequence"]})
                            if "guessState" in evt: guess_state = evt["guessState"]
                            if "result" in evt and evt["result"]: result=evt["result"]; phase="ended"; log("GAME","end:结果已出"); emit({"type":"result","result":evt["result"]})
                            if evt.get("state")=="ended": phase="ended"; log("GAME","end:游戏结束"); emit({"type":"result","result":evt.get("result",{})})
                        except json.JSONDecodeError: pass
                    elif line.startswith("event:"):
                        if line[6:].strip() in ("fatal","superseded"): phase="ended"

            if phase == "ended": break
            if guess_state and guess_state.get("selfLocked"): we_locked = True

            # 对手刚锁 → 立刻猜
            if guess_state and guess_state.get("opponentLocked") and not guess_state.get("selfLocked") and not we_locked and not opp_guess_done:
                opp_guess_done = True
                gms = [{"role": "system", "content": SYSTEM_PROMPT}]
                for m in messages:
                    if m["sender"] == "opponent": gms.append({"role": "user", "content": m["text"]})
                gms.append({"role": "system", "content": "判定："})
                raw = chat_completion(gms, api_key, base_url, model) or ""
                val = "ai" if any(w in (raw or "") for w in ["AI", "ai", "Ai", "机器", "不是人"]) else "human"
                log("GAME", f"guess:判定: {val}!")
                emit({"type": "guess", "value": val, "by": "self"})
                gr = req("POST", f"/api/turing/rooms/{room_id}/guess", {"sessionId": session_id, "guess": val})
                if gr and (gr.get("guessState") or gr.get("result")):
                    we_locked = True
                    if gr.get("guessState"): guess_state = gr["guessState"]
                    if gr.get("result"): result = gr["result"]; phase = "ended"
                else: log("ERROR", f"判定API失败: {gr}")

            now = time.time()
            opp_msgs = [m for m in messages if m["sender"] == "opponent"]
            self_msgs = [m for m in messages if m["sender"] == "self"]
            new_opp_msgs = [m for m in opp_msgs if m["sequence"] > last_replied_seq]
            elapsed = now - game_start if game_start else 0

            if game_start is None and opp_msgs: game_start = time.time(); elapsed = 0; log("GAME", "timer:开始计时"); update_state(game_start=game_start); emit({"type": "status", "key": "game_start", "value": game_start})
            if not opp_msgs and not self_msgs and not (guess_state and guess_state.get("opponentLocked")): continue

            ol = guess_state and guess_state.get("opponentLocked")
            if not game_start and not opp_msgs and elapsed > 15 and not self_msgs and not ol:
                t = random.choice(["你好啊", "在吗", "嗨", "有人吗"]); game_start = time.time()
                req("POST", f"/api/turing/rooms/{room_id}/messages", {"sessionId": session_id, "text": t})
                log("CHAT", f"send:{t}"); emit({"type": "chat", "sender": "self", "text": t, "sequence": 0}); continue

            sa = False
            if not we_locked:
                if new_opp_msgs and now - last_llm_call > 0.3: sa = True
            elif new_opp_msgs and now - last_llm_call > 0.3: sa = True
            if not sa: continue
            if cfg.DEBUG and we_locked: log("DEBUG", f"post-lock: new_opp={len(new_opp_msgs)}")

            last_llm_call = now
            llm_msgs = build_messages(messages)
            if new_opp_msgs:
                txt = new_opp_msgs[-1]["text"]
                sr = []
                should_search = len(txt) > 10 or any(c in txt for c in "/链接代称梗典传说语录")
                if should_search:
                    sr = web_search(txt, max_results=3)
                    if sr:
                        if cfg.DEBUG: log("DEBUG", f"搜索到 {len(sr)} 条")
                        llm_msgs.insert(1, {"role": "system", "content": "[搜索结果]\n" + "\n".join(f"- {r}" for r in sr)})
                    elif cfg.DEBUG:
                        log("DEBUG", f"搜索无结果: {txt[:40]}")

            raw = chat_completion(llm_msgs, api_key, base_url, model)
            if raw.startswith("__ERROR__"): log("ERROR", f"LLM错误: {raw[:100]}"); continue

            rc = raw.strip(); action = None
            if rc.startswith("{") and rc.endswith("}"):
                try: action = json.loads(rc)
                except json.JSONDecodeError: pass
            if action is None:
                # 纯文本"真人"/"AI"→判定，不发聊天
                if rc in ("真人", "人", "AI", "ai", "Ai"):
                    action = {"action": "guess", "value": "human" if rc in ("真人", "人") else "ai"}
                else:
                    action = {"action": "chat", "text": rc[:80]}

            a, t = action.get("action", "?"), action.get("text", "") or action.get("value", "")
            log("LLM", f"{a}: {t[:80]}")

            if action.get("action") == "chat":
                text = action.get("text", "").strip()
                if not text: log("WARN", "跳过空消息"); continue
                req("POST", f"/api/turing/rooms/{room_id}/messages", {"sessionId": session_id, "text": text})
                if new_opp_msgs: last_replied_seq = new_opp_msgs[-1]["sequence"]
                log("CHAT", f"send:{text}")
                emit({"type": "chat", "sender": "self", "text": text, "sequence": 0})
            elif action.get("action") == "guess":
                if we_locked: log("WARN", "已锁定跳过")
                else:
                    val = action.get("value", "human")
                    if val in ("human", "ai"):
                        log("GAME", f"guess:判定: {val}!")
                        emit({"type": "guess", "value": val, "by": "self"})
                        gr = req("POST", f"/api/turing/rooms/{room_id}/guess", {"sessionId": session_id, "guess": val})
                        if gr and (gr.get("guessState") or gr.get("result")):
                            we_locked = True
                            if gr.get("guessState"): guess_state = gr["guessState"]
                            if gr.get("result"): result = gr["result"]; phase = "ended"
                        else: log("ERROR", f"判定API失败: {gr}")
                if new_opp_msgs: last_replied_seq = new_opp_msgs[-1]["sequence"]

    except KeyboardInterrupt: pass
    finally:
        if ws: ws.close()
        try: conn.close()
        except: pass

    game_result = {"nickname": nickname, "playerId": player_id, "roomId": room_id,
                   "messages": messages, "result": result, "guessState": guess_state,
                   "account": getattr(play_one_game, "account_info", {"type": "guest"})}
    game_logs.append(game_result)
    return game_result


def grind(n_rounds, api_key, base_url, model):
    nickname = "路人甲"
    logs, stats = [], {"games": 0, "correct": 0, "actual_ai": 0, "actual_human": 0, "errors": 0}
    inf = n_rounds == float("inf")
    label = "无限" if inf else str(int(n_rounds))
    log("INFO", f"=== 图灵测试刷分模式: {label} 轮 ==="); log("INFO", f"模型: {model}")
    total_n = n_rounds if not inf else 0
    update_state(total=total_n, round=0, stats=dict(stats), phase="idle")
    emit({"type": "stats", "stats": dict(stats)})
    i = 0
    while inf or i < n_rounds:
        try:
            log("INFO", f"--- 第 {i+1}/{label} 轮 ---")
            update_state(round=i+1, phase="queuing", roomId=None, playerId="?", queue=None, game_start=None, messages=[])
            emit({"type": "round", "round": i+1, "total": total_n})
            r = play_one_game(f"{nickname}{random.randint(1, 999)}", api_key, base_url, model, logs)
        except KeyboardInterrupt: print("\n用户中断", flush=True); break
        if "error" in r:
            stats["errors"] += 1
            d = r.get("detail", ""); log("ERROR", f"{r['error']} {d}" if d else r['error'])
            update_state(stats=dict(stats)); emit({"type": "stats", "stats": dict(stats)})
        else:
            stats["games"] += 1
            res = r.get("result") or {}
            correct, actual = res.get("correct", False), res.get("actualType", "unknown")
            if actual == "ai": stats["actual_ai"] += 1
            else: stats["actual_human"] += 1
            if correct: stats["correct"] += 1
            a = r.get("account", {}); s = "[OK]" if correct else "[XX]"
            log("INFO", f"{s} [{a.get('username', a.get('type', '?'))}] 猜 {res.get('guess', '?')} | 实际 {actual} | 对方猜 {res.get('opponentGuess', {}).get('guess', '?')} | 命中率 {stats['correct']}/{stats['games']}")
            emit({"type": "status", "key": "round_result", "value": f"猜 {res.get('guess', '?')} | 实际 {actual} | 对方猜 {res.get('opponentGuess', {}).get('guess', '?')}"})
            update_state(stats=dict(stats))
            emit({"type": "stats", "stats": dict(stats)})
        i += 1; time.sleep(2)
    try:
        lf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_logs.json")
        with open(lf, "w", encoding="utf-8") as f: json.dump(logs, f, ensure_ascii=False, indent=2)
        acc = stats["correct"] / stats["games"] * 100 if stats["games"] > 0 else 0
        log("INFO", f"总局数: {stats['games']} | 命中: {stats['correct']} | 命中率: {acc:.0f}%")
        log("INFO", f"真人对手: {stats['actual_human']} | AI 对手: {stats['actual_ai']}")
        log("INFO", f"错误/未匹配: {stats['errors']}"); log("INFO", f"日志已保存: {lf}")
        update_state(stats=dict(stats), phase="idle")
        emit({"type": "stats", "stats": dict(stats)})
    except KeyboardInterrupt: pass
