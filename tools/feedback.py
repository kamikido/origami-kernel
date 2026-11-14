# -*- coding: utf-8 -*-
"""
Origami Architectural Feedback & Post-Mortem Analyzer.
Analyzes meeting transcripts (architecture reviews, syncs) and extracts:
- Developer blind spots and anti-patterns
- Principal Architect directives and invariants
- Actionable improvements for Origami Kernel (rules, premodel, TZ template)
Pure Python standard library (urllib + json).
"""

import sys
import os
import json
import argparse
import datetime
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

# Ensure UTF-8 output on Windows
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

cur_dir = Path(__file__).resolve().parent
if str(cur_dir) not in sys.path:
    sys.path.insert(0, str(cur_dir))

try:
    from origami_config import get_config
    CFG = get_config()
except Exception:
    CFG = None

SYSTEM_PROMPT = """Ты — Главный Архитектор корпоративной платформы разработки 1С (Origami Kernel).
Твоя цель — провести профессиональный ретроспективный анализ (Post-Mortem Review) стенограммы/транскрипта архитектурного совещания с ведущим архитектором/руководителем команды 1С.

Цель разбора:
1. Выявить, в чем разработчики ошиблись или мыслили поверхностно (Blind spots, Anti-patterns).
2. Зафиксировать ключевую архитектурную позицию ведущего архитектора/руководителя (Key Directives & Decisions).
3. Сформулировать системные уроки и новые инварианты (Invariants) для корпоративного стандарта 1С.
4. Предложить конкретные дополнения в ядро Origami (проверки для premodel.py, правила для 1c-protocol.md, разделы ТЗ).

ЖЕЛЕЗНОЕ ТРЕБОВАНИЕ ОБЕЗЛИЧЕННОСТИ И ОБОБЩЕНИЯ (Open Source Sanitization):
- Категорически запрещено включать в извлекаемые правила, заголовки, инварианты и отчеты реальные персональные данные (ФИО участников), наименования конкретных компаний/заказчиков и закрытые префиксы.
- Все роли обобщаются: «Ведущий архитектор», «Разработчик», «Заказчик», «Руководитель проекта». В поле "architect_name" указывать строго «Ведущий архитектор» или «Технический лидер».
- Все архитектурные правила и инварианты формулируются как универсальные стандарты платформы 1С:Предприятие 8.3, применимые к любой типовой (ERP, УТ, КА, БП, ЗУП) или отраслевой конфигурации.
- Объекты метаданных обобщаются до их архитектурных ролей (например: «Документ-инициатор», «Документ перемещения/списания», «Регистр накопления остатков»).

ОТВЕТ ДОЛЖЕН БЫТЬ СТРОГО В ФОРМАТЕ ВАЛИДНОГО JSON следующей структуры:
{
  "meeting_title": "Краткая универсальная суть и тема обсуждения (без названий компаний)",
  "architect_name": "Ведущий архитектор",
  "developer_blind_spots": [
    {
      "flaw": "В чем была ошибка разработчиков / черновика ТЗ",
      "why_flawed": "Почему это архитектурный дефект в парадигме 1С:Предприятие",
      "architect_verdict": "Что именно указал / потребовал ведущий архитектор"
    }
  ],
  "senior_invariants_extracted": [
    {
      "title": "Название архитектурного правила/инварианта",
      "statement": "Точная недвусмысленная формулировка правила для стандарта разработки 1С",
      "anti_pattern": "Что категорически запрещено делать (Табу)",
      "best_practice": "Как правильно реализовывать в 1С 8.3.27"
    }
  ],
  "origami_improvements": {
    "premodel_checks": [
      "Какую конкретную проверку добавить в premodel.py, чтобы агент вскрывал эту проблему ДО написания ТЗ"
    ],
    "rules_update": [
      "Какой пункт добавить в 1c-protocol.md / AGENTS.md"
    ],
    "tz_template_changes": [
      "Какой раздел или обязательный пункт добавить в шаблон ТЗ"
    ]
  },
  "executive_summary": "Итоговое резюме для команды (3-5 емких предложений)"
}

НЕ выводи никаких вступительных слов или markdown-блоков ```json вокруг ответа. Только чистый валидный JSON.
"""


def call_omniroute(prompt: str, user_content: str, model: Optional[str] = None, timeout: int = 120) -> Dict[str, Any]:
    endpoint = CFG.get("omniroute.endpoint", "http://localhost:20128/v1") if CFG else "http://localhost:20128/v1"
    api_key = CFG.get_omniroute_key() if CFG else ""
    model_name = model or (CFG.get("omniroute.criticModel") or "auto/best-reasoning" if CFG else "auto/best-reasoning")

    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "max_tokens": 4096
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)
            raw_text = data["choices"][0]["message"]["content"].strip()
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


def save_reports(result: Dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"feedback_{ts}.json"
    md_path = output_dir / f"feedback_{ts}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    md_lines = [
        f"# Архитектурный разбор совещания (Origami Continuous Learning)",
        f"\n**Тема:** {result.get('meeting_title', 'Архитектурное совещание')}",
        f"**Ведущий архитектор:** {result.get('architect_name', 'Не указан')}",
        f"**Дата анализа:** {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n",
        "## 1. Резюме для команды",
        f"{result.get('executive_summary', '')}\n",
        "## 2. Вскрытые слепые зоны и ошибки разработчиков\n",
    ]

    for idx, flaw in enumerate(result.get("developer_blind_spots", []), 1):
        md_lines.append(f"### {idx}. {flaw.get('flaw', '')}")
        md_lines.append(f"- **Почему это ошибка в 1С:** {flaw.get('why_flawed', '')}")
        md_lines.append(f"- **Вердикт архитектора:** *{flaw.get('architect_verdict', '')}*\n")

    md_lines.append("## 3. Извлеченные архитектурные инварианты (Senior 1C)\n")
    for idx, inv in enumerate(result.get("senior_invariants_extracted", []), 1):
        md_lines.append(f"### Правило {idx}: {inv.get('title', '')}")
        md_lines.append(f"> **Формулировка:** {inv.get('statement', '')}")
        md_lines.append(f"- **Категорическое ТАБУ:** {inv.get('anti_pattern', '')}")
        md_lines.append(f"- **Эталонное решение:** {inv.get('best_practice', '')}\n")

    md_lines.append("## 4. Предложения по улучшению ядра Origami\n")
    improvements = result.get("origami_improvements", {})
    md_lines.append("### В консилиум premodel.py:")
    for item in improvements.get("premodel_checks", []):
        md_lines.append(f"- {item}")

    md_lines.append("\n### В регламент 1c-protocol.md / AGENTS.md:")
    for item in improvements.get("rules_update", []):
        md_lines.append(f"- {item}")

    md_lines.append("\n### В шаблон ТЗ разработчика:")
    for item in improvements.get("tz_template_changes", []):
        md_lines.append(f"- {item}")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Origami Architectural Feedback & Learning Loop")
    parser.add_argument("--meeting", "-m", required=True, help="Путь к файлу транскрипта/стенограммы совещания")
    parser.add_argument("--tz", "-t", help="Опциональный путь к черновику ТЗ или исходному коду")
    parser.add_argument("--model", help="Модель OmniRoute (по умолчанию criticModel / best-reasoning)")
    parser.add_argument("--timeout", type=int, default=120, help="Таймаут запроса в секундах")
    parser.add_argument("--output", "-o", help="Каталог для сохранения отчетов")

    args = parser.parse_args()

    meeting_path = Path(args.meeting)
    if not meeting_path.exists():
        print(f"[!] Файл стенограммы не найден: {meeting_path}", file=sys.stderr)
        sys.exit(2)

    meeting_text = meeting_path.read_text(encoding="utf-8", errors="replace")
    if not meeting_text.strip():
        print("[!] Файл стенограммы пуст.", file=sys.stderr)
        sys.exit(2)

    tz_text = ""
    if args.tz:
        tz_path = Path(args.tz)
        if tz_path.exists():
            tz_text = f"\n\n--- ИСХОДНЫЙ ЧЕРНОВИК ТЗ / ПОСТАНОВКИ ---\n{tz_path.read_text(encoding='utf-8', errors='replace')}"

    user_content = f"Стенограмма архитектурного совещания:\n\n{meeting_text}{tz_text}"

    # Ограничение до ~250000 символов (для длинных стенограмм)
    if len(user_content) > 250000:
        user_content = user_content[:250000] + "\n\n// ... [Текст усечен до 250000 символов]"

    print(f">>> Запуск архитектурного анализа совещания через OmniRoute...")
    print(f"    Источник: {meeting_path.name}")
    try:
        result = call_omniroute(SYSTEM_PROMPT, user_content, model=args.model, timeout=args.timeout)
    except Exception as e:
        print(f"[!] Ошибка анализа OmniRoute: {e}", file=sys.stderr)
        sys.exit(1)

    root_dir = CFG.root_dir if CFG else Path.cwd()
    output_dir = Path(args.output) if args.output else (root_dir / "scratch" / "feedback")
    json_path, md_path = save_reports(result, output_dir)

    print("\n" + "=" * 80)
    print(f"      ORIGAMI FEEDBACK: АРХИТЕКТУРНЫЙ РАЗБОР ЗАВЕРШЕН")
    print("=" * 80)
    print(f"Тема:    {result.get('meeting_title', '')}")
    print(f"Эксперт: {result.get('architect_name', 'Ведущий архитектор')}")
    print("\n[РЕЗЮМЕ]:")
    print(result.get("executive_summary", ""))

    print("\n[ИЗВЛЕЧЕННЫЕ ИНВАРИАНТЫ]:")
    for inv in result.get("senior_invariants_extracted", []):
        print(f"  * {inv.get('title')}: {inv.get('statement')}")

    print("\n[ОТЧЕТЫ СОХРАНЕНЫ]:")
    print(f"  Markdown: {md_path}")
    print(f"  JSON:     {json_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
