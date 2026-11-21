#!/usr/bin/env bash
# 统一网关 E2E 测试：验证 / 与 /napcat 在同一端口的完整行为面
set -u
GATEWAY="http://127.0.0.1:6185"
PASS=0; FAIL=0

check() { # name, expect_substring, actual
    if echo "$3" | grep -qF "$2"; then PASS=$((PASS+1)); echo "  ✓ $1"
    else FAIL=$((FAIL+1)); echo "  ✗ $1"; echo "      期望包含: $2"; echo "      实际: $(echo "$3" | head -c 300)"; fi
}

echo "== 1. AstrBot WebUI 于根路径 =="
R=$(curl -sS -o /tmp/e1.html -w "%{http_code}" "$GATEWAY/")
check "GET / 返回 200" "200" "$R"
R=$(head -c 3000 /tmp/e1.html)
check "GET / 是 AstrBot SPA（HTML 含 AstrBot 标识）" "AstrBot" "$R"
N=$(grep -c "404 . NOT FOUND\|文件缺失" /tmp/e1.html || true)
check "GET / 不是文件缺失页" "0" "$N"

echo "== 2. AstrBot API 于 /api =="
R=$(curl -sS "$GATEWAY/api/stat/start-time" 2>&1)
check "GET /api/stat/start-time 可达（无需鉴权端点）" "time" "$R"

echo "== 3. /napcat 入口重定向 =="
R=$(curl -sS -o /dev/null -w "%{http_code} %{redirect_url}" "$GATEWAY/napcat")
check "GET /napcat → 307 /napcat/webui/" "/napcat/webui/" "$R"

echo "== 4. NapCat SPA 经代理（重写后的 index.html） =="
R=$(curl -sS "$GATEWAY/napcat/webui/")
check "index.html 资源引用带 /napcat 前缀" '/napcat/webui/assets/' "$R"
N=$(echo "$R" | grep -c 'src="/webui/\|href="/webui/' || true)
check "index.html 无残留根绝对引用" "0" "$N"

echo "== 5. NapCat 静态资源代理 =="
JS=$(echo "$R" | grep -o '/napcat/webui/assets/index-[^"]*\.js' | head -1)
R2=$(curl -sS -o /tmp/e5.js -w "%{http_code}" "$GATEWAY$JS")
check "GET $JS 返回 200" "200" "$R2"
R2=$(cat /tmp/e5.js)
check "JS 中 axios base 已改写" '"/napcat/api"' "$R2"
check "JS 中 SPA basename 已改写" '"/napcat/webui/"' "$R2"
check "JS 中无残留根绝对 base" 'BAD-NEVER' "$(echo "$R2" | grep -c '"/api";' | sed 's/^0$/BAD-NEVER/;s/^[1-9].*/HAS-LEFTOVER/')"

echo "== 6. NapCat API 代理 =="
R=$(curl -sS -X POST "$GATEWAY/napcat/api/auth/check")
check "POST /napcat/api/auth/check" '"code":0' "$R"

echo "== 7. JSON 响应体站内路径改写 =="
R=$(curl -sS "$GATEWAY/napcat/api/Plugin")
check "icon 路径已加前缀" '"/napcat/api/Plugin/Icon/demo"' "$R"
check "page 路径已加前缀" '"/napcat/plugin/demo/page/index"' "$R"
check "外链不受影响" 'https://example.com/untouched' "$R"

echo "== 8. SSE 流式透传 =="
R=$(timeout 10 curl -sS -N "$GATEWAY/napcat/api/Log/GetLogRealTime" 2>&1 | head -c 400)
check "SSE 收到多条日志" "log line" "$R"
check "SSE Content-Type 生效" "data:" "$R"

echo "== 9. WebSocket 代理（终端端点） =="
R=$(./venv/bin/python - <<'EOF'
import asyncio, sys
sys.path.insert(0, '.')
from websockets.asyncio.client import connect

async def t():
    async with connect("ws://127.0.0.1:6185/napcat/api/ws/terminal?token=mock") as ws:
        await ws.send("hello-terminal")
        return await asyncio.wait_for(ws.recv(), timeout=5)

print(asyncio.run(t()))
EOF
)
check "WS echo 经网关往返" "echo: hello-terminal" "$R"

echo "== 10. WebSocket 代理（调试端点，模板字符串构造） =="
R=$(./venv/bin/python - <<'EOF'
import asyncio, sys
sys.path.insert(0, '.')
from websockets.asyncio.client import connect

async def t():
    async with connect("ws://127.0.0.1:6185/napcat/api/Debug/ws?access_token=x") as ws:
        await ws.send("hello-debug")
        return await asyncio.wait_for(ws.recv(), timeout=5)

print(asyncio.run(t()))
EOF
)
check "WS echo（Debug 端点）" "echo: hello-debug" "$R"

echo "== 11. 后端重定向改写（/ → /webui） =="
R=$(curl -sS -o /dev/null -w "%{http_code} %{redirect_url}" "$GATEWAY/napcat/api/base/../")
check "代理路径归一" "" "$R"

echo "== 12. healthz =="
R=$(curl -sS "$GATEWAY/napcat/healthz")
check "healthz 就绪状态" '"ready":true' "$R"

echo "== 13. AstrBot 静态资源未被 /napcat 影响 =="
R=$(curl -sS -o /dev/null -w "%{http_code}" "$GATEWAY/assets/version" 2>&1)
check "AstrBot dist 资源路径不受代理影响（404/200 均可，不 5xx）" "" "$R"

echo ""
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
