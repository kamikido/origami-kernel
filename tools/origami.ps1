<#
.SYNOPSIS
    Origami CLI Facade — Единая консоль управления операционной платформой разработки 1С.
.DESCRIPTION
    Предоставляет централизованный доступ к операциям платформенного каркаса Origami:
    - doctor   : Диагностика окружения и определение уровней деградации (L1 / L2 / L3)
    - status   : Проверка активного проекта, расширения и базы 1С
    - config   : Просмотр и получение параметров конфигурации (origami.config.json)
    - premodel : Архитектурное моделирование и консилиум OmniRoute (слепые зоны, риски)
    - audit    : Независимый AI-аудит качества кода через OmniRoute (DeepSeek-R1 / Claude)
    - format   : Автоформатирование BSL на 120 символов (format_bsl.os --diff)
    - lint     : Pure-Diff статический анализ BSL (lint_bsl_diff.py)
    - check    : Комплексный контроль качества (format + lint)
    - deploy   : Автономное развертывание и синхронизация проектов
    - query    : Выполнение тестового запроса к базе 1С через COM-соединение
#>

param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$SubArgs = @()
)

[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8

$PSScriptRootResolved = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $PSScriptRootResolved

# Загружаем системную библиотеку
. "$PSScriptRootResolved\common.ps1"

function Show-Help {
    Write-Host @"
================================================================================
           ORIGAMI: Операционная среда автономной разработки 1С
================================================================================
Использование: .\tools\origami.ps1 <команда> [параметры...]

Команды окружения и диагностики:
  doctor                     Диагностика окружения и определение уровня деградации (L1/L2/L3)
  status                     Статус активного проекта, расширения и базы данных
  config [show|get <ключ>]   Просмотр конфигурации проекта (origami.config.json)

Команды AI-консилиума и качества:
  premodel "<задача>"        Консилиум моделей OmniRoute: цели, слепые зоны, риски
  feedback -m <стенограмма>  Архитектурный анализ совещания (Continuous Learning Loop)
  playbook [list|find|read]  Каталог архитектурных плейбуков долговременной памяти
  audit <файл|diff>          Независимый AI-аудит качества BSL-кода
  format <файл> [--diff]     Автоформатирование BSL на 120 символов (OneScript)
  lint <файл> [-l строки]    Pure-Diff статический линтинг измененных строк
  check <файл>               Комплексный контроль качества (format + lint)

Команды поставки и данных:
  deploy [status|update|init] Синхронизация и развертывание проектов из ядра
  query "<текст запроса>"    Выполнение запроса 1С через COM-соединение

Примеры:
  .\tools\origami.ps1 doctor
  .\tools\origami.ps1 premodel "Интеграция со службой доставки через HTTP"
  .\tools\origami.ps1 format src\CommonModules\MyModule\Ext\Module.bsl --diff
  .\tools\origami.ps1 lint src\CommonModules\MyModule\Ext\Module.bsl
  .\tools\origami.ps1 audit src\CommonModules\MyModule\Ext\Module.bsl
================================================================================
"@
}

$cmd = $Command.ToLower()

switch ($cmd) {
    "help" {
        Show-Help
    }

    "doctor" {
        python (Join-Path $PSScriptRootResolved "doctor.py") @SubArgs
    }

    "status" {
        Write-Host "`n=== Origami: Статус проекта ===" -ForegroundColor Cyan
        if (Test-Path (Join-Path $ProjectRoot "origami.config.json")) {
            Get-Content -Raw -Encoding UTF8 (Join-Path $ProjectRoot "origami.config.json")
        } else {
            Write-Host "Файл origami.config.json не обнаружен в корне: $ProjectRoot" -ForegroundColor Yellow
            Write-Host "Используется upstream-режим ядра Origami Kernel."
        }
    }

    "config" {
        python (Join-Path $PSScriptRootResolved "origami_config.py") @SubArgs
    }

    "premodel" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите текст задачи или файл для premodel." -ForegroundColor Red
            exit 1
        }
        python (Join-Path $PSScriptRootResolved "premodel.py") @SubArgs
    }

    "feedback" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите путь к файлу стенограммы (-m <файл>)." -ForegroundColor Red
            exit 1
        }
        python (Join-Path $PSScriptRootResolved "feedback.py") @SubArgs
    }

    "playbook" {
        python (Join-Path $PSScriptRootResolved "playbook.py") @SubArgs
    }

    "audit" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите файл BSL для аудита." -ForegroundColor Red
            exit 1
        }
        $targetFile = $SubArgs[0]
        if ($targetFile -match '\.(diff|patch)$') {
            python (Join-Path $PSScriptRootResolved "adversarial_review.py") --diff $targetFile
        } else {
            python (Join-Path $PSScriptRootResolved "adversarial_review.py") --file $targetFile
        }
    }

    "format" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите файл BSL для форматирования." -ForegroundColor Red
            exit 1
        }
        $formatScript = Join-Path $PSScriptRootResolved "format_bsl\format_bsl.os"
        & "oscript" $formatScript @SubArgs
    }

    "lint" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите файл BSL для линтинга." -ForegroundColor Red
            exit 1
        }
        python (Join-Path $PSScriptRootResolved "lint_bsl_diff.py") --file $SubArgs[0]
    }

    "check" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите файл BSL для комплексного контроля." -ForegroundColor Red
            exit 1
        }
        $targetFile = $SubArgs[0]
        Write-Host ">>> Шаг 1/2: Автоформатирование BSL (Smart Diff, 120 символов)..." -ForegroundColor Cyan
        $formatScript = Join-Path $PSScriptRootResolved "format_bsl\format_bsl.os"
        & "oscript" $formatScript $targetFile --diff
        Write-Host "`n>>> Шаг 2/2: Pure-Diff статический линтинг..." -ForegroundColor Cyan
        python (Join-Path $PSScriptRootResolved "lint_bsl_diff.py") --file $targetFile
    }

    "deploy" {
        python (Join-Path $PSScriptRootResolved "deploy.py") @SubArgs
    }

    "query" {
        if ($SubArgs.Count -lt 1) {
            Write-Host "Ошибка: Укажите текст запроса." -ForegroundColor Red
            exit 1
        }
        $queryScript = Join-Path $PSScriptRootResolved "query.os"
        & "oscript" $queryScript @SubArgs
    }

    default {
        Write-Host "Неизвестная команда: $Command" -ForegroundColor Yellow
        Show-Help
        exit 1
    }
}
