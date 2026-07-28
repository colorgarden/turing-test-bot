# -*- coding: utf-8 -*-
"""联网搜索——Bing Web Search API"""
import json, ssl, urllib.request, urllib.parse
from config import log, DEBUG

BING_KEY = None  # 通过环境变量 BING_API_KEY 或 --bing-key 设置

def web_search(query, max_results=3):
    if BING_KEY:
        r = _bing_search(query, max_results)
        if r: return r
    r = _searxng_search(query, max_results)
    if r: return r
    return _ddg_fallback(query, max_results)

def _bing_search(query, max_results):
    url = "https://api.bing.microsoft.com/v7.0/search"
    params = urllib.parse.urlencode({"q": query, "count": str(max_results), "mkt": "zh-CN"})
    r = urllib.request.Request(f"{url}?{params}", headers={
        "Ocp-Apim-Subscription-Key": BING_KEY,
        "User-Agent": "Mozilla/5.0"
    })
    try:
        ctx = ssl._create_unverified_context()
        resp = urllib.request.urlopen(r, timeout=5, context=ctx)
        data = json.loads(resp.read().decode())
        results = []
        for page in data.get("webPages", {}).get("value", [])[:max_results]:
            results.append(f"{page['name']}: {page.get('snippet', '')}")
        return results
    except Exception as e:
        if DEBUG:
            log("DEBUG", f"Bing 搜索失败: {e}")
        return []


def _searxng_search(query, max_results=3):
    """SearXNG 公共实例——中文搜索更好"""
    instances = [
        "https://search.sapti.me",
        "https://searx.be",
        "https://search.bus-hit.me",
    ]
    for base in instances:
        try:
            url = f"{base}/search?format=json&q={urllib.parse.quote(query)}"
            ctx = ssl._create_unverified_context()
            resp = urllib.request.urlopen(urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0"
            }), timeout=5, context=ctx)
            data = json.loads(resp.read().decode())
            results = []
            for r in data.get("results", [])[:max_results]:
                results.append(f"{r.get('title','')}: {r.get('content','')[:100]}")
            if results:
                return results
        except Exception:
            continue
    return []


def _ddg_fallback(query, max_results=3):
    """DuckDuckGo Lite 备用搜索"""
    import re
    url = "https://lite.duckduckgo.com/lite/?"
    params = urllib.parse.urlencode({"q": query})
    try:
        ctx = ssl._create_unverified_context()
        no_proxy = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(no_proxy)
        r = urllib.request.Request(url + params, headers={
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = opener.open(r, timeout=5)
        html = resp.read().decode("utf-8", errors="replace")
        results = []
        for pat in [
            r'<a[^>]*rel="nofollow"[^>]*href="([^"]*)"[^>]*>([^<]+)</a>\s*<span[^>]*class="[^"]*snippet[^"]*"[^>]*>([^<]+)',
            r'<a[^>]*class="result-link"[^>]*href="([^"]*)"[^>]*>([^<]+)</a>',
            r'<a[^>]*href="([^"]*)"[^>]*class="result-link"[^>]*>([^<]+)</a>',
            r'<td[^>]*>\s*<a[^>]*href="(https?://[^"]*)"[^>]*>([^<]+)</a>',
        ]:
            matches = re.findall(pat, html, re.DOTALL | re.IGNORECASE)
            if matches:
                for m in matches[:max_results]:
                    title = re.sub(r'<[^>]*>', '', m[1] if len(m) > 1 else m[0]).strip()
                    desc = re.sub(r'<[^>]*>', '', m[2] if len(m) > 2 else '').strip()
                    entry = title
                    if desc and desc != title:
                        entry += f": {desc}"
                    if entry and entry not in results:
                        results.append(entry)
                if results:
                    break
        return results[:max_results]
    except Exception:
        return []
