# -*- coding: utf-8 -*-
"""
Adversarial AI Reviewer for Origami Platform.
Performs independent, strict code review of 1C (BSL) diffs/code using local OmniRoute.
Does not require external pip dependencies (pure Python 3 urllib).
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# Гарантируем UTF-8 вывод на консоль Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Подключаем слой конфигурации
cur_dir = Path(__file__).resolve().parent
if str(cur_dir) not in sys.path:
    sys.path.insert(0, str(cur_dir))

try:
    from origami_config import get_config
    CFG = get_config()
except Exception:
    CFG = None

SYSTEM_PROMPT = """Ты — независимый Senior Архитектор и ведущий ревьюер 1С:Предприятие 8.3.27.
Твоя цель — провести бескомпромиссный adversarial-аудит предоставленного BSL-кода или diff-изменений.
Ищи критические дефекты, которые пропускает обычный синтакс-чекер.

Критерии проверки:
1. [BLOCKER] Табу 1С:
   - Запросы в цикле (ТЧ должна выгружаться в ВТ и соединяться одним запросом).
   - Вызовы ПолучитьОбъект() или разыменование ссылок через точку в циклах выборки.
   - Управляемые блокировки без ИсточникДанных = ТаблицаДанных.
   - Ранний выход из цикла при сборе ошибок ТЧ (должен быть полный обход всех строк).
2. [ARCHITECTURAL] Архитектура и БСП:
   - Изобретение велосипедов вместо типовых методов БСП (СтроковыеФункцииКлиентСервер, ОбщегоНазначенияКлиентСервер).
   - Неоправданное использование &Вместо в расширениях вместо &После / &Перед.
   - Неверное разделение контекстов (&НаКлиенте / &НаСервере / &НаСервереБезКонтекста).
3. [EDGE_CASES] Пограничные сценарии:
   - Деление на 0 при расчете сумм и процентов.
   - Обращение к свойствам пустых ссылок без проверки ЗначениеЗаполнено().
   - Отсутствие блока Иначе в цепочках Если-ИначеЕсли.
4. [STANDARDS] Корпоративные стандарты:
   - Псевдонимы таблиц расширения должны иметь префикс проекта (например: КАК <префикс>...).
   - Длина строк не более 120 символов.
   - Регламентные комментарии // { + <метка> ... } и сохранение удаляемого кода // { - ... }.

ОТВЕТ ДОЛЖЕН БЫТЬ СТРОГО В ФОРМАТЕ JSON следующей структуры:
{
  "decision": "APPROVED" | "REJECTED",
  "summary": "Краткий итог проверки (1-2 предложения)",
  "issues": [
    {
      "severity": "BLOCKER" | "WARNING" | "INFO",
      "category": "Performance" | "Architecture" | "Reliability" | "Standards",
      "line": 0,
      "message": "Суть проблемы",
      "recommendation": "Как правильно исправить"
    }
  ]
}
Если найден хотя бы один дефект с severity="BLOCKER", decision ДОЛЖЕН быть "REJECTED".
Если критических дефектов нет (только рекомендации или чисто), decision="APPROVED".
НЕ выводи никаких вступительных слов или markdown-блоков вокруг JSON, только чистый JSON.
"""


def call_omniroute(prompt: str, code_content: str, model: str = None, timeout: int = 60) -> dict:
    endpoint = CFG.get_llm_endpoint() if CFG else os.environ.get("OPENAI_BASE_URL", os.environ.get("LLM_ENDPOINT", "http://localhost:20128/v1"))
    api_key = CFG.get_llm_key() if CFG else os.environ.get("ORIGAMI_LLM_KEY", os.environ.get("OPENAI_API_KEY", ""))
    model_name = model or (CFG.get("llm.criticModel") or CFG.get("omniroute.model", "auto/best-reasoning") if CFG else "auto/best-reasoning")

    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    user_message = f"Проведи строгий аудит следующего фрагмента BSL кода / diff:\n\n```bsl\n{code_content}\n```"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.1,
        "max_tokens": 2048
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)
            raw_text = data["choices"][0]["message"]["content"].strip()
            
            # Очистка markdown блоков ```json ... ``` если модель их добавила
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            return json.loads(raw_text)
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ошибка связи с OmniRoute ({url}): {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Ответ модели не является валидным JSON: {e}\nОтвет: {raw_text[:300]}")


def save_reports(result: dict, raw_code: str, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "ai_audit_last.json"
    md_path = reports_dir / "ai_audit_last.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    decision_emoji = "🟢 ПРИНЯТО (APPROVED)" if result.get("decision") == "APPROVED" else "🔴 ОТКЛОНЕНО (REJECTED)"
    md_lines = [
        "# Независимый AI-аудит кода BSL (Origami Adversarial Review)",
        f"\n**Вердикт:** {decision_emoji}",
        f"\n**Резюме:** {result.get('summary', 'Нет резюме')}",
        "\n## Замечания аудитора\n"
    ]

    issues = result.get("issues", [])
    if not issues:
        md_lines.append("*Критических замечаний и дефектов не обнаружено.*")
    else:
        for idx, item in enumerate(issues, 1):
            sev = item.get("severity", "INFO")
            icon = "🔴" if sev == "BLOCKER" else ("🟡" if sev == "WARNING" else "🔵")
            md_lines.append(f"### {idx}. {icon} [{sev}] {item.get('category', 'General')} (строка {item.get('line', '?')})")
            md_lines.append(f"- **Проблема:** {item.get('message', '')}")
            md_lines.append(f"- **Рекомендация:** {item.get('recommendation', '')}\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Origami Adversarial Code Reviewer via OmniRoute")
    parser.add_argument("--file", "-f", help="Путь к файлу BSL для проверки")
    parser.add_argument("--diff", "-d", help="Путь к файлу diff или патча")
    parser.add_argument("--model", "-m", help="Модель OmniRoute (по умолчанию из origami.config.json)")
    parser.add_argument("--timeout", "-t", type=int, default=60, help="Таймаут запроса в секундах")
    parser.add_argument("--json", action="store_true", help="Выводить только JSON результат")

    args = parser.parse_args()

    content = ""
    target_name = ""

    if args.diff:
        diff_path = Path(args.diff)
        if not diff_path.exists():
            print(f"[!] Файл diff не найден: {diff_path}", file=sys.stderr)
            sys.exit(2)
        content = diff_path.read_text(encoding="utf-8", errors="replace")
        target_name = diff_path.name
    elif args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"[!] Файл BSL не найден: {file_path}", file=sys.stderr)
            sys.exit(2)
        content = file_path.read_text(encoding="utf-8", errors="replace")
        target_name = file_path.name
    else:
        if not sys.stdin.isatty():
            content = sys.stdin.read()
            target_name = "stdin"
        else:
            print("[!] Укажите --file, --diff или передайте данные через конвейер stdin.", file=sys.stderr)
            sys.exit(2)

    if not content.strip():
        print("[!] Входные данные для анализа пусты.", file=sys.stderr)
        sys.exit(2)

    # Ограничение размера для одного аудита (~4000 строк)
    max_chars = 40000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n// ... [Фрагмент усечен до 40000 символов]"

    try:
        result = call_omniroute(SYSTEM_PROMPT, content, model=args.model, timeout=args.timeout)
    except Exception as e:
        err_msg = f"[!] Ошибка вызова OmniRoute AI: {e}"
        if args.json:
            print(json.dumps({"decision": "ERROR", "summary": str(e), "issues": []}, ensure_ascii=False))
        else:
            print(err_msg, file=sys.stderr)
        sys.exit(1)

    # Сохраняем отчеты
    root_dir = CFG.root_dir if CFG else Path.cwd()
    reports_dir = root_dir / (CFG.get("testing.reportsPath", "tests/reports") if CFG else "tests/reports")
    json_path, md_path = save_reports(result, content, reports_dir)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        decision = result.get("decision", "UNKNOWN")
        badge = "[APPROVED]" if decision == "APPROVED" else "[REJECTED]"
        print(f"\n=== Origami AI Adversarial Review: {target_name} {badge} ===")
        print(f"Резюме: {result.get('summary', '')}\n")
        issues = result.get("issues", [])
        if issues:
            print(f"Найдено замечаний: {len(issues)}")
            for item in issues:
                sev = item.get("severity", "INFO")
                icon = "[!]" if sev == "BLOCKER" else ("[-]" if sev == "WARNING" else "[i]")
                print(f"  {icon} [{sev}] Строка {item.get('line', '?')}: {item.get('message')}")
                print(f"      Рекомендация: {item.get('recommendation')}")
        else:
            print("[OK] Замечаний к коду нет.")
        print(f"\nОтчет сохранен: {md_path}")

    sys.exit(0 if result.get("decision") == "APPROVED" else 1)


if __name__ == "__main__":
    main()
