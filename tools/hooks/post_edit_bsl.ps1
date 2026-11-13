<#
.SYNOPSIS
    Origami Platform Component Script
#>
# post_edit_bsl.ps1 — Хук PostToolUse: Автоформатирование на лету + Pure-Diff BSL линтер



. "$PSScriptRoot\common_hook.ps1"



try {

    $payload = Read-HookInput

    $fileInfo = Get-EditedFileInfo $payload



    $targetFile = $fileInfo.TargetFile

    if (-not $targetFile -or -not (Test-Path $targetFile)) {

        Write-HookOutput @{}

        exit 0

    }



    # Проверяем только файлы BSL

    if (-not $targetFile.EndsWith(".bsl", [System.StringComparison]::OrdinalIgnoreCase)) {

        Write-HookOutput @{}

        exit 0

    }



    # Защита от рекурсивных вызовов

    if (Test-Path $global:LOCK_FILE) {

        Write-HookOutput @{}

        exit 0

    }



    # Устанавливаем блокировку форматирования

    Set-Content -Path $global:LOCK_FILE -Value "$([DateTime]::UtcNow)" -Encoding UTF8



    try {

        # 1. Автоформатирование через format_bsl.os --diff

        $formatScript = Join-Path $PSScriptRoot "..\format_bsl\format_bsl.os"

        $oscript = (Get-Command oscript -ErrorAction SilentlyContinue).Source

        if ($oscript -and (Test-Path $formatScript)) {

            & $oscript $formatScript $targetFile --diff 2>$null | Out-Null

        }



        # 2. Pure-Diff статический анализ

        $linterScript = Join-Path $PSScriptRoot "..\lint_bsl_diff.py"

        $python = (Get-Command python -ErrorAction SilentlyContinue).Source



        if ($python -and (Test-Path $linterScript)) {

            $linesArg = ""

            if ($fileInfo.StartLine -gt 0 -and $fileInfo.EndLine -ge $fileInfo.StartLine) {

                # Небольшой запас по строкам контекста

                $linesArg = "$($fileInfo.StartLine)-$($fileInfo.EndLine)"

            }



            $cmdArgs = @($linterScript, "--file", $targetFile, "--json")

            $authorName = "Developer"
            $cfgPath = Join-Path $wsRoot "origami.config.json"
            if (Test-Path $cfgPath) {
                try {
                    $cfgJson = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($cfgJson.author) { $authorName = $cfgJson.author }
                } catch {}
            }
            if ($linesArg) {

                $cmdArgs += @("--lines", $linesArg)

            } else {

                $cmdArgs += @("--author", $authorName)

            }



            $lintOutput = & $python $cmdArgs 2>$null

            $issues = $null

            if ($lintOutput) {

                try {

                    $issues = $lintOutput | ConvertFrom-Json

                } catch {}

            }



            if ($issues -and $issues.Count -gt 0) {

                # Сохраняем состояние замечаний для stop_guard.ps1

                $lintOutput | Set-Content -Path $global:ISSUES_FILE -Encoding UTF8



                [Console]::Error.WriteLine("")

                [Console]::Error.WriteLine("[Origami Platform Quality Gate] Замечания Pure-Diff линтера в $targetFile ($($issues.Count)):")

                foreach ($iss in $issues) {

                    [Console]::Error.WriteLine("  * Линия $($iss.line): [$($iss.code)] $($iss.message)")

                }

                [Console]::Error.WriteLine("")

            } else {

                # Замечаний нет — очищаем файл ошибок

                if (Test-Path $global:ISSUES_FILE) {

                    Remove-Item $global:ISSUES_FILE -Force

                }

            }

        }

    }

    finally {

        if (Test-Path $global:LOCK_FILE) {

            Remove-Item $global:LOCK_FILE -Force

        }

    }



    Write-HookOutput @{}

    exit 0

}

catch {

    # Хук никогда не должен валить сессию падением скрипта

    if (Test-Path $global:LOCK_FILE) {

        Remove-Item $global:LOCK_FILE -Force

    }

    Write-HookOutput @{}

    exit 0

}

