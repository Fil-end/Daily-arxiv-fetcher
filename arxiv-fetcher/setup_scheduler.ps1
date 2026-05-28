# ============================================================
# arXiv Daily Fetcher — Windows 定时任务安装脚本
# 用法: 以管理员身份运行 PowerShell，然后执行此脚本
#   powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
# ============================================================

param(
    [string]$TaskName = "arXiv Daily Fetcher",
    [string]$ScheduleTime = "08:00",
    [string]$PythonPath = "python",
    [switch]$Uninstall,
    [switch]$RunNow
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MainScript = Join-Path $ScriptDir "arxiv_daily.py"
$LogDir = Join-Path $ScriptDir "logs"
$LogFile = Join-Path $LogDir "arxiv_daily_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ─── 卸载 ───
if ($Uninstall) {
    Write-Host "正在移除定时任务: $TaskName ..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    if ($?) {
        Write-Host "[成功] 定时任务已移除。"
    } else {
        Write-Host "[信息] 任务不存在或已移除。"
    }
    exit 0
}

# ─── 立即运行 ───
if ($RunNow) {
    Write-Host "正在立即运行一次..."
    $Command = "`"$PythonPath`" `"$MainScript`" *>&1 | Tee-Object -FilePath `"$LogFile`""
    Invoke-Expression "& $Command"
    Write-Host "日志已保存到: $LogFile"
    exit 0
}

# ─── 安装定时任务 ───
Write-Host "================================================"
Write-Host "  arXiv Daily Fetcher — 定时任务安装"
Write-Host "================================================"
Write-Host ""
Write-Host "任务名称: $TaskName"
Write-Host "脚本路径: $MainScript"
Write-Host "Python:    $PythonPath"
Write-Host "执行时间: 每天 $ScheduleTime"
Write-Host "日志目录: $LogDir"
Write-Host ""

# 构建触发条件
$Trigger = New-ScheduledTaskTrigger -Daily -At $ScheduleTime

# 构建执行动作：运行 python + 脚本，输出到日志
$ActionArg = "-NoProfile -ExecutionPolicy Bypass -Command `"& '$PythonPath' '$MainScript' *>&1 | Out-File -FilePath '$LogDir\arxiv_daily_`$(Get-Date -Format 'yyyyMMdd').log' -Encoding utf8`""
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArg

# 任务配置
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# 以当前用户身份运行
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

try {
    Register-ScheduledTask -TaskName $TaskName `
        -Trigger $Trigger `
        -Action $Action `
        -Settings $Settings `
        -Principal $Principal `
        -Description "每天自动从 arXiv 抓取感兴趣领域的论文并导入 Obsidian 知识图谱" `
        -Force

    Write-Host ""
    Write-Host "================================================"
    Write-Host "  [成功] 定时任务已安装！"
    Write-Host "================================================"
    Write-Host ""
    Write-Host "任务将在每天 $ScheduleTime 自动运行。"
    Write-Host ""
    Write-Host "管理命令："
    Write-Host "  手动运行一次:  .\setup_scheduler.ps1 -RunNow"
    Write-Host "  查看任务:      Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  禁用任务:      Disable-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  启用任务:      Enable-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  卸载任务:      .\setup_scheduler.ps1 -Uninstall"
    Write-Host ""
    Write-Host "如需修改执行时间，重新运行此脚本即可："
    Write-Host "  .\setup_scheduler.ps1 -ScheduleTime '09:00'"
    Write-Host ""
} catch {
    Write-Host "[错误] 安装失败: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "可能的原因："
    Write-Host "  1. 需要以管理员身份运行 PowerShell"
    Write-Host "  2. 任务名称已存在（使用 -Uninstall 先卸载）"
    Write-Host ""
    exit 1
}
