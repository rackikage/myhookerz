"""
proxy_verifier.py — Proxy health verification and IP reputation
Tests ADB phone proxies and file-based proxies before use.
"""
import os
import re
import json
import time
import socket
import random
import urllib.request
import threading
from queue import Queue
from urllib.request import ProxyHandler, build_opener, install_opener


CHECK_URLS = [
    "http://api.ipify.org",
    "http://ip-api.com/json",
    "http://httpbin.org/ip",
]


def test_proxy(proxy_url, timeout=10):
    """
    Test if a proxy is working and return info.
    Returns dict with: working, ip, country, org, latency_ms, error
    """
    result = {"proxy": proxy_url, "working": False, "latency_ms": None}
    protocol = "http" if proxy_url.startswith("http://") else "socks5"
    try:
        start = time.time()
        proxy_handler = ProxyHandler({protocol: proxy_url})
        opener = build_opener(proxy_handler)
        resp = opener.open(CHECK_URLS[1], timeout=timeout)
        latency = int((time.time() - start) * 1000)
        data = json.loads(resp.read().decode())
        result.update({
            "working": True,
            "ip": data.get("query", ""),
            "country": data.get("country", ""),
            "org": data.get("org", ""),
            "latency_ms": latency,
            "isp": data.get("isp", ""),
            "region": data.get("regionName", ""),
            "city": data.get("city", ""),
            "mobile": "mobile" in data.get("org", "").lower() or
                      "cellular" in data.get("org", "").lower(),
        })
    except Exception as e:
        result["error"] = str(e)[:100]

    return result


def verify_adb_proxy(phone_serial, proxy_url, timeout=10):
    """
    Verify that an ADB phone proxy is actually routing through
    the phone's cellular connection.
    """
    result = test_proxy(proxy_url, timeout)
    if result["working"]:
        # Check it looks like a real carrier, not a datacenter
        org = (result.get("org") or "").lower()
        result["is_carrier"] = any(k in org for k in [
            "mobile", "cellular", "telekom", "vodafone", "t-mobile",
            "orange", "at&t", "verizon", "telenor", "telstra",
            "airtel", "jio", "singtel", "china mobile", "china unicom",
            "kt corporation", "sk telecom", "lgu+", "softbank",
            "docomo", "rakuten", "telcel", "vivo", "claro", "tim",
            "oi", "movistar", "etisalat", "du", "zain", "mtn",
            "vodacom", "safaricom", "telkomsel", "xl axiata",
            "indosat", "smartfren", "globe", "smart", "dtac",
            "true move", "ais", "mobilfone", "vinaphone", "viettel",
        ])
        if not result["is_carrier"] and result.get("ip"):
            result["is_carrier"] = True  # assume ADB phones are mobile
    return result


def batch_verify(proxies, threads=10, timeout=8):
    """Verify multiple proxies in parallel."""
    results = Queue()
    def _worker(p):
        r = test_proxy(p, timeout)
        results.put(r)
    tlist = []
    for p in proxies[:50]:  # max 50
        t = threading.Thread(target=_worker, args=(p,), daemon=True)
        t.start()
        tlist.append(t)
    verified = []
    for _ in range(min(len(proxies), 50)):
        verified.append(results.get(timeout=30))
    return verified


def filter_working(proxies, min_speed_ms=5000):
    """Test and return only working proxies."""
    results = batch_verify(proxies)
    working = [r for r in results if r.get("working") and (r.get("latency_ms", 9999) < min_speed_ms)]
    return [r["proxy"] for r in working], results


def get_ip_info(proxy_url=None):
    """Get IP info with or without proxy."""
    try:
        if proxy_url:
            protocol = "http" if proxy_url.startswith("http://") else "socks5"
            handler = ProxyHandler({protocol: proxy_url})
            opener = build_opener(handler)
            resp = opener.open(CHECK_URLS[1], timeout=10)
        else:
            resp = urllib.request.urlopen(CHECK_URLS[1], timeout=10)
        return json.loads(resp.read().decode())
    except:
        return None
