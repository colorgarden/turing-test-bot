# -*- coding: utf-8 -*-
"""DeepSeek LLM 调用"""
import json, urllib.request
from config import log
import config as cfg

def chat_completion(messages, api_key, base_url=None, model=None):
    """纯文本 API——LLM 自由输出"""
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    if cfg.DEBUG:
        log("DEBUG", f"LLM call ({len(messages)} msgs):")
        for m in messages[-4:]:
            log("DEBUG", f"  [{m['role']}] {m['content'][:120]}")
    body = {
        "model": model or "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 200,
    }
    data = json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        t0 = __import__('time').time()
        resp = urllib.request.urlopen(r, timeout=60)
        elapsed = __import__('time').time() - t0
        result = json.loads(resp.read().decode())
        content = result["choices"][0]["message"]["content"]
        if cfg.DEBUG:
            log("DEBUG", f"LLM <- ({elapsed:.1f}s) {content[:300]}")
        return content
    except Exception as e:
        return f"__ERROR__:{e}"
