﻿# pre_command_guard.ps1 — Хук PreToolUse: Защита от деструктивных терминальных команд



. "$PSScriptRoot\common_hook.ps1"



try {

    $payload = Read-HookInput



    if ($payload -and $payload.toolCall -and $payload.toolCall.args) {

        $cmd = $payload.toolCall.args.CommandLine



        if ($cmd) {

            # Проверяем опасные шаблоны:

            # 1. Принудительное закрытие 1С (Конфигуратора разработчика)

            $killPattern = "(Stop-Process|taskkill).*?(1cv8|1c|rac|ras)"

            # 2. Удаление каталога базы данных

            $deleteBasePattern = "(Remove-Item|rmdir|rd|del).*?(1C base|\.1CD)"



            if ($cmd -match $killPattern) {

                Write-HookOutput @{

                    decision = "ask"

                    reason   = "[Origami Platform Safety Gate] Внимание: команда попытается завершить процесс 1С ('$cmd'), что может закрыть открытый Конфигуратор с несохраненными данными. Подтверждаете выполнение?"

                }

                exit 0

            }



            if ($cmd -match $deleteBasePattern) {

                Write-HookOutput @{

                    decision = "ask"

                    reason   = "[Origami Platform Safety Gate] Внимание: команда содержит операцию удаления данных в каталоге базы 1С ('$cmd'). Подтверждаете выполнение?"

                }

                exit 0

            }

        }

    }



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

