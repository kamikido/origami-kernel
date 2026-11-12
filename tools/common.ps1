# tools/common.ps1 — Системная библиотека вызовов 1С платформенного каркаса Origami
# Обеспечивает безопасную инициализацию с поддержкой деградации L1 (без фатальных падений)

[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$global:ProjectRoot = Split-Path -Parent $PSScriptRoot
$global:OrigamiConfigPath = Join-Path $global:ProjectRoot 'origami.config.json'
$global:HasConfig = Test-Path $global:OrigamiConfigPath

if ($global:HasConfig) {
    try {
        $RawCfg = Get-Content -Raw -Encoding UTF8 $global:OrigamiConfigPath | ConvertFrom-Json
        $global:Cfg = [PSCustomObject]@{
            configuration = if ($RawCfg.project.title) { $RawCfg.project.title } else { "1С:Предприятие" }
            platformBin   = if ($RawCfg.tools.platform) { Split-Path -Parent $RawCfg.tools.platform } elseif ($RawCfg.infobase.platformBin) { $RawCfg.infobase.platformBin } else { "" }
            ibFile        = if ($RawCfg.infobase.type -match 'file' -or -not $RawCfg.infobase.server) { $RawCfg.infobase.path } else { '' }
            ibServer      = if ($RawCfg.infobase.server) { $RawCfg.infobase.server } else { '' }
            user          = $RawCfg.infobase.user
            password      = if ($env:ORIGAMI_DB_PASSWORD) { $env:ORIGAMI_DB_PASSWORD } else { '' }
            extension     = $RawCfg.project.extensionName
            extensionSrc  = $RawCfg.project.extensionSrc
            projectRoot   = $global:ProjectRoot
        }
    } catch {
        $global:HasConfig = $false
    }
}

if (-not $global:HasConfig) {
    $global:Cfg = [PSCustomObject]@{
        configuration = "Origami Kernel"
        platformBin   = ""
        ibFile        = ""
        ibServer      = ""
        user          = ""
        password      = ""
        extension     = ""
        extensionSrc  = ""
        projectRoot   = $global:ProjectRoot
    }
}
