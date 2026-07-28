# -*- coding: utf-8 -*-
"""图灵测试 API 请求"""
import json, ssl, urllib.request, urllib.error
import config as cfg
from config import BASE, VISITOR_ID, AUTH_TOKEN, log

def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    if cfg.DEBUG:
        b_str = json.dumps(body, indent=2, ensure_ascii=False) if body else "{}"
        log("DEBUG", f"{method} {path}\n{b_str}")
    headers = {
        "x-visitor-id": VISITOR_ID, "content-type": "application/json",
        "origin": BASE, "referer": BASE + "/turing-test",
        "accept": "*/*", "accept-language": "zh-CN,zh;q=0.9",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if AUTH_TOKEN:
        headers["authorization"] = f"Bearer {AUTH_TOKEN}"
    if data:
        headers["content-length"] = str(len(data))
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        ctx = ssl._create_unverified_context()
        if cfg._proxy_handler:
            opener = urllib.request.build_opener(cfg._proxy_handler)
            resp = opener.open(r, timeout=15)
        else:
            resp = urllib.request.urlopen(r, timeout=15, context=ctx)
        result = json.loads(resp.read().decode())
        if cfg.DEBUG:
            log("DEBUG", f"<- {json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
        return result
    except urllib.error.HTTPError as e:
        try:
            result = json.loads(e.read().decode())
            if cfg.DEBUG:
                log("DEBUG", f"<- HTTP{e.code}\n{json.dumps(result, indent=2, ensure_ascii=False)[:500]}")
            return result
        except Exception:
            return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}
