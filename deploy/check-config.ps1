# CDAP Tailscale 配置检查脚本
# 用于验证所有配置是否正确

Write-Host "=== CDAP Tailscale 配置检查 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 Docker 服务状态
Write-Host "[1/6] 检查 Docker 服务..." -ForegroundColor Yellow
$containers = docker ps --filter "name=cdap" --format "{{.Names}}: {{.Status}}"
if ($LASTEXITCODE -eq 0) {
    $containers | ForEach-Object { Write-Host "  ✓ $_" -ForegroundColor Green }
} else {
    Write-Host "  ✗ Docker 服务检查失败" -ForegroundColor Red
    exit 1
}

# 2. 检查端口映射
Write-Host ""
Write-Host "[2/6] 检查容器端口映射..." -ForegroundColor Yellow
$frontendPort = docker port cdap-frontend-1 80 2>&1
$minioPort = docker port cdap-minio-1 9000 2>&1

if ($frontendPort -match "127.0.0.1:8080") {
    Write-Host "  ✓ Frontend: 80 -> 127.0.0.1:8080" -ForegroundColor Green
} else {
    Write-Host "  ✗ Frontend 端口映射错误: $frontendPort" -ForegroundColor Red
}

if ($minioPort -match "127.0.0.1:9000") {
    Write-Host "  ✓ MinIO: 9000 -> 127.0.0.1:9000" -ForegroundColor Green
} else {
    Write-Host "  ✗ MinIO 端口映射错误: $minioPort" -ForegroundColor Red
}

# 3. 检查 Tailscale Funnel 配置
Write-Host ""
Write-Host "[3/6] 检查 Tailscale Funnel..." -ForegroundColor Yellow
$funnelStatus = tailscale funnel status

if ($funnelStatus -match "8443.*127.0.0.1:8080") {
    Write-Host "  ✓ Funnel 8443 -> 127.0.0.1:8080" -ForegroundColor Green
} else {
    Write-Host "  ✗ Funnel 8443 配置错误" -ForegroundColor Red
    Write-Host "    应该是: https://codex-pc.tail409d12.ts.net:8443 -> http://127.0.0.1:8080" -ForegroundColor Yellow
}

if ($funnelStatus -match "10000.*127.0.0.1:9000") {
    Write-Host "  ✓ Funnel 10000 -> 127.0.0.1:9000" -ForegroundColor Green
} else {
    Write-Host "  ✗ Funnel 10000 配置错误" -ForegroundColor Red
    Write-Host "    应该是: https://codex-pc.tail409d12.ts.net:10000 -> http://127.0.0.1:9000" -ForegroundColor Yellow
    Write-Host "    修复命令: tailscale funnel --https 10000 off; tailscale funnel --bg --https 10000 http://127.0.0.1:9000" -ForegroundColor Yellow
}

# 4. 检查 S3_PUBLIC_ENDPOINT 配置
Write-Host ""
Write-Host "[4/6] 检查 S3 公共端点配置..." -ForegroundColor Yellow
$s3Endpoint = docker exec cdap-api-1 printenv S3_PUBLIC_ENDPOINT 2>&1

if ($s3Endpoint -match "https://codex-pc.tail409d12.ts.net:10000") {
    Write-Host "  ✓ S3_PUBLIC_ENDPOINT: $s3Endpoint" -ForegroundColor Green
} else {
    Write-Host "  ✗ S3_PUBLIC_ENDPOINT 配置错误: $s3Endpoint" -ForegroundColor Red
    Write-Host "    应该是: https://codex-pc.tail409d12.ts.net:10000" -ForegroundColor Yellow
}

# 5. 检查端口冲突
Write-Host ""
Write-Host "[5/6] 检查端口冲突..." -ForegroundColor Yellow
$port8080 = netstat -ano | findstr ":8080" | findstr "LISTENING"
if ($port8080 -match "127.0.0.1:8080") {
    Write-Host "  ✓ 8080 端口正常监听 (Frontend)" -ForegroundColor Green
} else {
    Write-Host "  ✗ 8080 端口未监听或配置错误" -ForegroundColor Red
}

$port9000 = netstat -ano | findstr ":9000" | findstr "LISTENING"
if ($port9000 -match "127.0.0.1:9000") {
    Write-Host "  ✓ 9000 端口正常监听 (MinIO)" -ForegroundColor Green
} else {
    Write-Host "  ✗ 9000 端口未监听或配置错误" -ForegroundColor Red
}

# 6. 测试外网访问
Write-Host ""
Write-Host "[6/6] 测试外网访问..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "https://codex-pc.tail409d12.ts.net:8443/" -Method Head -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        Write-Host "  ✓ 前端访问正常 (HTTP $($response.StatusCode))" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 前端访问异常 (HTTP $($response.StatusCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "  ✗ 前端访问失败: $($_.Exception.Message)" -ForegroundColor Red
}

# 总结
Write-Host ""
Write-Host "=== 配置摘要 ===" -ForegroundColor Cyan
Write-Host "前端访问: https://codex-pc.tail409d12.ts.net:8443/" -ForegroundColor White
Write-Host "存储端点: https://codex-pc.tail409d12.ts.net:10000/" -ForegroundColor White
Write-Host ""

# 如果发现 Funnel 配置错误，提供快速修复命令
if ($funnelStatus -notmatch "10000.*127.0.0.1:9000") {
    Write-Host "=== 快速修复命令 ===" -ForegroundColor Yellow
    Write-Host "tailscale funnel --https 10000 off" -ForegroundColor Cyan
    Write-Host "tailscale funnel --bg --https 10000 http://127.0.0.1:9000" -ForegroundColor Cyan
    Write-Host ""
}
