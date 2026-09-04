param(
    [ValidateSet("qa", "prod")]
    [string]$Environment = "qa",

    [int]$EveryMinutes = 5,
    [string]$TaskName = "SiesaPaymentSyncQA",
    [string]$PythonPath = "python",
    [switch]$Send
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runner = Join-Path $repoRoot "scripts\Invoke-SiesaPaymentSync.ps1"

$runnerArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-Environment", $Environment,
    "-PythonPath", "`"$PythonPath`""
)

if ($Send) {
    $runnerArgs += "-Send"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($runnerArgs -join " ") -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Sincroniza pagos desde Sheets hacia Siesa HUB." -Force

Write-Host "Tarea registrada: $TaskName cada $EveryMinutes minutos en ambiente $Environment"
