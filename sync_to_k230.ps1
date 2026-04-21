# sync_to_k230.ps1 - 一键同步 K230 前端代码到设备
# 用法: powershell -ExecutionPolicy Bypass -File sync_to_k230.ps1
#
# 策略：后台自动按确认键，前台直接覆盖拷贝，用户无需任何操作

$ErrorActionPreference = "Stop"

$SRC_DIR = "D:\code\py\AIassistant\k230"
$DEVICE_NAME = "CanMV"

Write-Host "======================================" -ForegroundColor Cyan
Write-Host " K230 前端代码同步工具" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# 连接 MTP 设备
$shell = New-Object -ComObject Shell.Application
$myComputer = $shell.NameSpace(17)

$canmv = $null
foreach ($item in $myComputer.Items()) {
    if ($item.Name -eq $DEVICE_NAME) {
        $canmv = $item
        break
    }
}

if (-not $canmv) {
    Write-Host "[ERROR] 未找到设备 '$DEVICE_NAME'，请确认 K230 已通过 USB 连接" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] 已连接: $($canmv.Name)" -ForegroundColor Green

# 导航到 sdcard/aiAssitant
$sdcard = $canmv.GetFolder.Items() | Where-Object { $_.Name -eq "sdcard" }
if (-not $sdcard) {
    Write-Host "[ERROR] 未找到 sdcard" -ForegroundColor Red
    exit 1
}

$destFolder = $null
foreach ($item in $sdcard.GetFolder.Items()) {
    if ($item.Name -eq "aiAssitant") {
        $destFolder = $item.GetFolder
        break
    }
}

if (-not $destFolder) {
    Write-Host "[ERROR] 未找到 sdcard/aiAssitant" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] 目标: sdcard/aiAssitant/" -ForegroundColor Green

# 启动后台自动确认（持续按 Enter，覆盖弹窗时自动确认）
$bgJob = Start-Job -ScriptBlock {
    $wshell = New-Object -ComObject WScript.Shell
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 300
        $wshell.SendKeys("{ENTER}")
    }
}

Start-Sleep -Milliseconds 500

# 拷贝所有 .py 文件
$srcFolder = $shell.NameSpace($SRC_DIR)
$success = 0
$failed = 0

Write-Host ""
foreach ($item in $srcFolder.Items()) {
    if ($item.Name -notlike "*.py") { continue }
    try {
        $destFolder.CopyHere($item, 0x04)
        Write-Host "  OK  $($item.Name)" -ForegroundColor Green
        $success++
        Start-Sleep -Milliseconds 1000
    } catch {
        Write-Host "  FAIL  $($item.Name)" -ForegroundColor Red
        $failed++
    }
}

# 停止后台任务
Stop-Job $bgJob -ErrorAction SilentlyContinue
Remove-Job $bgJob -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host " 完成: $success 成功, $failed 失败" -ForegroundColor $(if ($failed -gt 0) { "Yellow" } else { "Green" })
Write-Host "======================================" -ForegroundColor Cyan
