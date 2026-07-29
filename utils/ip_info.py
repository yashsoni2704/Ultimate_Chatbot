"""
utils/ip_info.py
~~~~~~~~~~~~~~~~
Resolve a client IP address into geo + ISP data using the free
ip-api.com JSON endpoint (no API key needed, 45 req/min limit).

Returns a flat dict of strings — safe to store directly in MongoDB.
Falls back to empty strings if the lookup fails (network down, rate
limited, private IP, etc.) so callers never crash.

Usage:
    from utils.ip_info import get_ip_info, get_client_ip
    ip  = get_client_ip(request)
    geo = get_ip_info(ip)
"""

from __future__ import annotations

import requests
from flask import Request
from utils.logger import get_logger

logger = get_logger(__name__)

# Fields we ask ip-api.com to return
_FIELDS = "status,country,regionName,city,isp,timezone,query"
_API_URL = "http://ip-api.com/json/{ip}?fields={fields}"

# IPs that can never be geo-resolved
_LOCAL_PREFIXES = ("127.", "192.168.", "10.", "172.", "::1", "localhost")


def get_client_ip(req: Request) -> str:
    """
    Extract the real client IP from a Flask Request object.

    Checks X-Forwarded-For first (set by reverse proxies / load balancers),
    then falls back to REMOTE_ADDR.
    """
    forwarded = req.headers.get("X-Forwarded-For", "")
    if forwarded:
        # Header can contain a comma-separated chain — first entry is the client
        ip = forwarded.split(",")[0].strip()
        if ip:
            return ip
    return req.remote_addr or "127.0.0.1"


def _is_local(ip: str) -> bool:
    return any(ip.startswith(p) for p in _LOCAL_PREFIXES)


def get_ip_info(ip: str) -> dict:
    """
    Lookup geo + ISP info for *ip*.

    Returns a dict with keys:
        ip_address, country, region, city, isp, timezone
    All values are strings; empty string on failure.
    """
    base: dict = {
        "ip_address": ip,
        "country":    "",
        "region":     "",
        "city":       "",
        "isp":        "",
        "timezone":   "",
    }

    if not ip or _is_local(ip):
        logger.debug(f"  Skipping geo lookup for local/private IP: {ip}")
        return base

    try:
        url  = _API_URL.format(ip=ip, fields=_FIELDS)
        resp = requests.get(url, timeout=3)
        data = resp.json()

        if data.get("status") == "success":
            base.update({
                "country":  data.get("country",    ""),
                "region":   data.get("regionName", ""),
                "city":     data.get("city",       ""),
                "isp":      data.get("isp",        ""),
                "timezone": data.get("timezone",   ""),
            })
            logger.debug(f" IP resolved: {ip} → {base['city']}, {base['country']}")
        else:
            logger.debug(f"  ip-api.com returned non-success for {ip}: {data}")

    except Exception as exc:
        logger.warning(f"  IP lookup failed for {ip}: {exc}")

    return base


def get_browser_os(user_agent: str) -> tuple[str, str, str]:
    """
    Very lightweight UA parse — returns (browser, os, device_type).
    No external dependency, covers the most common cases.
    """
    ua = user_agent.lower()

    # Browser
    if "edg/" in ua or "edge/" in ua:
        browser = "Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "chrome" in ua and "safari" in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    else:
        browser = "Other"

    # OS
    if "windows" in ua:
        os_name = "Windows"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"

    # Device type
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        device = "mobile"
    elif "tablet" in ua or "ipad" in ua:
        device = "tablet"
    else:
        device = "desktop"

    return browser, os_name, device
