# -*- coding: utf-8 -*-
"""联网搜索——Bing/Startpage/SearXNG/DDG"""
import json, ssl, urllib.request, urllib.parse
from config import log, DEBUG, _proxy_handler

BING_KEY = None

def _open(url, timeout=8):
    if _proxy_handler:
        return urllib.request.build_opener(_proxy_handler).open(url, timeout=timeout)
    return urllib.request.urlopen(url, timeout=timeout, context=ssl._create_unverified_context())

def web_search(query, max_results=3):
    if BING_KEY:
        r = _bing_search(query, max_results)
        if r: return r
    r = _startpage_search(query, max_results)
    if r: return r
    r = _searxng_search(query, max_results)
    if r: return r
    return _ddg_fallback(query, max_results)

def _startpage_search(query, max_results=3):
    """Startpage——Google 结果，免费，中文好"""
    import re
    url = "https://www.startpage.com/sp/search"
    params = urllib.parse.urlencode({"query": query, "num": str(max_results), "language": "zh-CN"})
    try:
        ctx = ssl._create_unverified_context()
        r = urllib.request.Request(f"{url}?{params}", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = _open(r, timeout=8, context=ctx)
        html = resp.read().decode("utf-8", errors="replace")
        results = []
        for m in re.finditer(r'<a[^>]*class="[^"]*result-link[^"]*"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html):
            results.append(m.group(2).strip())
            if len(results) >= max_results: break
        if not results:
            for m in re.finditer(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html):
                results.append(re.sub(r'<[^>]+>', '', m.group(2)).strip())
                if len(results) >= max_results: break
        return results[:max_results]
    except Exception:
        return []

def _bing_search(query, max_results):
    url = "https://api.bing.microsoft.com/v7.0/search"
    params = urllib.parse.urlencode({"q": query, "count": str(max_results), "mkt": "zh-CN"})
    r = urllib.request.Request(f"{url}?{params}", headers={
        "Ocp-Apim-Subscription-Key": BING_KEY,
        "User-Agent": "Mozilla/5.0"
    })
    try:
        ctx = ssl._create_unverified_context()
        resp = _open(r, timeout=5, context=ctx)
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
        r = urllib.request.Request(url + params, headers={
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = _open(r, timeout=5)
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
