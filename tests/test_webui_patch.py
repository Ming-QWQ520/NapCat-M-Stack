"""stack.webui_patch 单元测试。

用最小化夹具覆盖重写规则的关键性质：三类规则命中、引号边界保护、
路由链接不误伤、幂等性。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stack.webui_patch import rewrite_text


def test_axios_base_and_fetch_base():
    src = 'const t="/api";e.baseURL=t;const f=await fetch("/api"+e,t);'
    out, n = rewrite_text(src)
    assert out == (
        'const t="/napcat/api";e.baseURL=t;'
        'const f=await fetch("/napcat/api"+e,t);'
    )
    assert n == 2


def test_router_basename_and_sw():
    src = 'basename:"/webui/",children:x;const e="/webui/",t=`${e}sw.js`;'
    out, n = rewrite_text(src)
    assert out == (
        'basename:"/napcat/webui/",children:x;'
        'const e="/napcat/webui/",t=`${e}sw.js`;'
    )
    assert n == 2


def test_terminal_ws_and_debug_ws_template_literal():
    src = 'a.pathname="/api/ws/terminal";'
    out, _ = rewrite_text(src)
    assert out == 'a.pathname="/napcat/api/ws/terminal";'

    src = "const u=`${window.location.host}/api/Debug/ws`;"
    out, n = rewrite_text(src)
    assert out == "const u=`${window.location.host}/napcat/api/Debug/ws`;"
    assert n == 1


def test_sse_endpoints():
    src = "new EventSourcePolyfill('/api/Log/GetLogRealTime',{})"
    out, n = rewrite_text(src)
    assert out == "new EventSourcePolyfill('/napcat/api/Log/GetLogRealTime',{})"
    assert n == 1


def test_plugin_pages_but_not_router_links():
    src = 'window.open(`/plugin/${e}/page/${l}`);href:"/plugins";href:"/plugin_store";'
    out, n = rewrite_text(src)
    assert "/napcat/plugin/${e}/page/${l}" in out
    assert 'href:"/plugins"' in out
    assert 'href:"/plugin_store"' in out
    assert n == 1


def test_external_urls_untouched():
    src = 'fetch(`https://api.github.com/repos/${e}`);get("https://api.iowen.cn/favicon/x")'
    out, n = rewrite_text(src)
    assert out == src
    assert n == 0


def test_css_url():
    src = "src:url(/webui/fonts/AaCute.woff) format('woff');"
    out, n = rewrite_text(src)
    assert out == "src:url(/napcat/webui/fonts/AaCute.woff) format('woff');"
    assert n == 1


def test_html_asset_references():
    src = '<link href="/webui/assets/x.css"><script src="/webui/assets/y.js"></script>'
    out, n = rewrite_text(src)
    assert out.count('"/napcat/webui/assets/') == 2
    assert n == 2


def test_theme_css_fetch():
    src = 'im("/files/theme.css?_t="+Date.now())'
    out, n = rewrite_text(src)
    assert out == 'im("/napcat/files/theme.css?_t="+Date.now())'
    assert n == 1


def test_idempotent():
    src = 'const t="/api";a.pathname="/api/ws/terminal";basename:"/webui/"'
    once, _ = rewrite_text(src)
    twice, n2 = rewrite_text(once)
    assert twice == once
    assert n2 == 0


def test_relative_api_call_paths_untouched():
    # axios 相对路径（自动拼 baseURL）不应被改写
    src = 'serverRequest.post("/auth/check");x.get("/File/font/exists/webui")'
    out, n = rewrite_text(src)
    assert out == src
    assert n == 0
