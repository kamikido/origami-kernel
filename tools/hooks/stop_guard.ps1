# stop_guard.ps1 — Хук Stop: Гарантия качества (блокировка model_stop при наличии ERROR)



. "$PSScriptRoot\common_hook.ps1"



try {

    $payload = Read-HookInput



    if (Test-Path $global:ISSUES_FILE) {

        $jsonText = Get-Content -Path $global:ISSUES_FILE -Raw -Encoding UTF8

        $issues = $null

        try {

            $issues = $jsonText | ConvertFrom-Json

        } catch {}



        if ($issues) {

            $errors = @($issues | Where-Object { $_.severity -eq "ERROR" })

            if ($errors.Count -gt 0) {

                $firstErr = $errors[0]

                $reasonMsg = "[Origami Platform Quality Gate] Завершение заблокировано! В добавленном BSL коде найдены нарушения стандартов ($($errors.Count)): строка $($firstErr.line) [$($firstErr.code)]: $($firstErr.message). Исправьте замечания линтера перед сдачей задачи."

                Write-HookOutput @{

                    decision = "continue"

                    reason   = $reasonMsg

                }

                exit 0

            }

        }

    }



    # Все проверки пройдены

    Write-HookOutput @{

        decision = "allow"

    }

    exit 0

}

catch {

    Write-HookOutput @{

        decision = "allow"

    }

    exit 0

}

