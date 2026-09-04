param(
    [ValidateSet("qa", "prod")]
    [string]$Environment = "qa",

    [string]$EnvFile,
    [string]$InputCsv,
    [string]$SheetsCsvUrl,
    [string]$PythonPath = "python",
    [switch]$Send
)

$ErrorActionPreference = "Stop"

function Import-DotEnv {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $separator = $line.IndexOf("=")
        if ($separator -lt 1) {
            return
        }

        $name = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:$name" -Value $value
    }
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $repoRoot

if (-not $EnvFile) {
    $candidate = Join-Path $repoRoot ".env.$Environment"
    if (Test-Path -LiteralPath $candidate) {
        $EnvFile = $candidate
    } else {
        $EnvFile = Join-Path $repoRoot ".env"
    }
}

Import-DotEnv -Path $EnvFile

$env:SIESA_ENV = $Environment
if ($Send) {
    $env:SIESA_DRY_RUN = "false"
} else {
    $env:SIESA_DRY_RUN = "true"
}

$arguments = @("-m", "siesa_payments.cli", "sync", "--env", $Environment)

if ($InputCsv) {
    $arguments += @("--input-csv", $InputCsv)
}

if ($SheetsCsvUrl) {
    $arguments += @("--sheets-csv-url", $SheetsCsvUrl)
}

if ($Send) {
    $arguments += "--send"
} else {
    $arguments += "--dry-run"
}

& $PythonPath @arguments
exit $LASTEXITCODE
