[CmdletBinding()]
param(
    [ValidateSet("debug", "profile", "release")]
    [string]$Mode = "release",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$App = Join-Path $Root "sirius_companion"
$StateFile = Join-Path $App ".companion_build_state.json"
$PackageConfig = Join-Path $App ".dart_tool\package_config.json"

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

function Get-DependencyFingerprint {
    $flutterVersion = (& flutter --version --machine | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($flutterVersion)) {
        throw "Flutter is not available or could not report its version."
    }

    $files = @(
        "pubspec.yaml",
        "pubspec.lock",
        "android\settings.gradle.kts",
        "android\build.gradle.kts",
        "android\app\build.gradle.kts",
        "android\gradle\wrapper\gradle-wrapper.properties"
    )
    $parts = [System.Collections.Generic.List[string]]::new()
    [void]$parts.Add("flutter=$flutterVersion")

    foreach ($relative in $files) {
        $path = Join-Path $App $relative
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            [void]$parts.Add("$relative=$hash")
        }
    }

    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($parts -join "`n"))
    $digest = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($digest.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $digest.Dispose()
    }
}

Push-Location $App
try {
    $fingerprint = Get-DependencyFingerprint
    $state = $null
    if (Test-Path -LiteralPath $StateFile) {
        try {
            $state = Get-Content -Raw -LiteralPath $StateFile | ConvertFrom-Json
        }
        catch {
            $state = $null
        }
    }

    if ($Clean) {
        Write-Host "[COMPANION] Cleaning Flutter build outputs..."
        Invoke-Checked "flutter" @("clean")
        $state = $null
    }

    $needsPubGet = -not (Test-Path -LiteralPath $PackageConfig -PathType Leaf)
    $needsPubGet = $needsPubGet -or $null -eq $state -or $state.fingerprint -ne $fingerprint

    if ($needsPubGet) {
        Write-Host "[COMPANION] Dependency lock/config changed; running flutter pub get..."
        Invoke-Checked "flutter" @("pub", "get")
    }
    else {
        Write-Host "[COMPANION] Dart dependencies unchanged; reusing pub cache."
    }

    Write-Host "[COMPANION] Building APK ($Mode)..."
    Invoke-Checked "flutter" @("build", "apk", "--$Mode", "--no-pub")

    $apk = Join-Path $App "build\app\outputs\flutter-apk\app-$Mode.apk"
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) {
        throw "Flutter completed without producing the expected APK: $apk"
    }

    @{
        fingerprint = $fingerprint
        mode = $Mode
        flutter = (& flutter --version --machine | Out-String).Trim()
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StateFile -Encoding UTF8

    Write-Host "[COMPANION] APK ready: $apk"
}
finally {
    Pop-Location
}
