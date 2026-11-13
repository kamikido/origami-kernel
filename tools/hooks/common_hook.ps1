# common_hook.ps1 — Общая библиотека функций для системных хуков Antigravity IDE (Origami Platform)



# 1. Гарантируем UTF-8 ввод/вывод в Windows PowerShell 5.1 / 7
try {
    [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {}



$global:ORIGAMI_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$global:LOCK_FILE = Join-Path $PSScriptRoot ".format_lock"

$global:ISSUES_FILE = Join-Path $PSScriptRoot ".last_lint_issues.json"



function Read-HookInput {

    <#

    .SYNOPSIS

        Считывает JSON из stdin, переданный ядром Antigravity IDE.

    #>

    try {

        $rawInput = [Console]::In.ReadToEnd()

        if ([string]::IsNullOrWhiteSpace($rawInput)) {

            return $null

        }

        return ($rawInput | ConvertFrom-Json)

    }

    catch {

        return $null

    }

}



function Write-HookOutput {

    <#

    .SYNOPSIS

        Выводит JSON в stdout для Antigravity IDE.

    #>

    param(

        [Parameter(Mandatory = $true)]

        $OutputObject

    )

    $json = $OutputObject | ConvertTo-Json -Depth 5 -Compress

    [Console]::Out.WriteLine($json)

}



function Get-EditedFileInfo {

    <#

    .SYNOPSIS

        Извлекает целевой файл и диапазон строк из полезной нагрузки хука или transcript.jsonl.

    #>

    param(

        $Payload

    )



    $result = [PSCustomObject]@{

        TargetFile = ""

        StartLine  = 0

        EndLine    = 0

    }



    if (-not $Payload) {

        return $result

    }



    # Вариант 1: аргументы переданы напрямую в toolCall.args

    if ($Payload.toolCall -and $Payload.toolCall.args) {

        $argsObj = $Payload.toolCall.args

        if ($argsObj.TargetFile) {

            $result.TargetFile = $argsObj.TargetFile

        }

        if ($argsObj.StartLine) { $result.StartLine = [int]$argsObj.StartLine }

        if ($argsObj.EndLine) { $result.EndLine = [int]$argsObj.EndLine }

        return $result

    }



    # Вариант 2: считывание из transcriptPath по stepIdx

    if ($Payload.transcriptPath -and (Test-Path $Payload.transcriptPath)) {

        try {

            $lines = Get-Content -Path $Payload.transcriptPath -Encoding UTF8

            $stepIdx = if ($Payload.stepIdx) { [int]$Payload.stepIdx } else { -1 }



            # Ищем с конца подходящую запись шага с tool_calls

            for ($i = $lines.Count - 1; $i -ge 0; $i--) {

                $line = $lines[$i]

                if ([string]::IsNullOrWhiteSpace($line)) { continue }

                $step = $line | ConvertFrom-Json

                if ($stepIdx -gt 0 -and $step.step_index -ne $stepIdx) { continue }



                if ($step.tool_calls) {

                    foreach ($tc in $step.tool_calls) {

                        if ($tc.name -match "write_to_file|replace_file_content|multi_replace_file_content") {

                            if ($tc.args -and $tc.args.TargetFile) {

                                $result.TargetFile = $tc.args.TargetFile

                                if ($tc.args.StartLine) { $result.StartLine = [int]$tc.args.StartLine }

                                if ($tc.args.EndLine) { $result.EndLine = [int]$tc.args.EndLine }

                                return $result

                            }

                        }

                    }

                }

            }

        }

        catch {

            # Фолбэк без падения

        }

    }



    return $result

}

