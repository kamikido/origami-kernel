# -*- coding: utf-8 -*-
"""
Origami Pre-Modeling Council (Контур предварительного архитектурного моделирования 1С).
Orchestrates parallel reasoning models via OmniRoute to detect 1C blind spots,
implicit assumptions, and formulate sharp clarifying questions according to AGENTS.md.
Pure Python standard library (urllib + concurrent.futures).
"""

import sys
import os
import json
import argparse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

SYSTEM_PROMPT = """Ты — ведущий советник и Principal Архитектор 1С:Предприятие (платформа 8.3.27, корпоративный регламент разработки).
Твоя задача — провести глубокий предварительный архитектурный анализ (Pre-Modeling) входящей задачи ДО написания кода и проектных решений.

Строго следуй «Протоколу взаимодействия и дисциплине мышления»:
1. НЕ ПРЕДЛАГАТЬ КОД СРАЗУ.
2. Определи реальную бизнес-цель задачи (в отличие от буквальной или поверхностной формулировки).
3. Выяви неявные предположения (implicit assumptions), сделанные автором задачи или разработчиком, которые могут оказаться ошибочными на платформе 1С.
4. Вскрой специфические слепые зоны (blind spots) 1С:
   - Блокировки (управляемые блокировки, гранулярность, ИсточникДанных = ТаблицаДанных, взаимоблокировки, эскалация);
   - RLS и права доступа (особенно в расширениях: безопасный режим, нехватка прав на добавленные реквизиты/объекты, привилегированный режим);
   - Границы транзакций и неоперативное проведение (запись в транзакции проведения, очистка движений);
   - Контекст выполнения и фоновые задания (клиент/сервер, отсутствие UI в фоне, обработчики ожидания на формах, блокировка сессий);
   - Расширения (&Перед / &После vs &Вместо, совместимость с обновлениями вендора, заимствованные формы BaseForm);
   - Обмен данными (КД 2.0 / EnterpriseData, сериализация XDTO, пустые ссылки, ключевые свойства);
   - Регуляторные, налоговые и учетные риски (ФНС, первичные документы, НДС, факсимиле на первичке/СФ, минусовые остатки, отключение типовых контролей БСП — обязательно указывать необходимость дисклеймера в ТЗ и письменного согласия заказчика на принятие рисков);
   - Производительность (запросы в циклах, монолитные выборки, индексация).
5. Сформулируй 3-5 точных, бескомпромиссных архитектурных вопросов Руководителю / Заказчику, без ответа на которые переходить к разработке опасно.

ОТВЕТ ДОЛЖЕН БЫТЬ СТРОГО В ФОРМАТЕ ВАЛИДНОГО JSON следующей структуры:
{
  "model_role": "Архитектурный анализ 1С",
  "business_goal": {
    "stated": "Буквальная формулировка задачи",
    "actual_business_need": "Истинная потребность бизнеса",
    "value_and_risk": "Бизнес-ценность и цена ошибки при неверном решении"
  },
  "implicit_assumptions": [
    {
      "assumption": "Неявное предположение",
      "why_dangerous": "Почему это может быть ложным в 1С 8.3.27",
      "verification_hint": "Что проверить в коде или метаданных для подтверждения"
    }
  ],
  "blind_spots": [
    {
      "category": "Locks" | "RLS_Rights" | "Transactions" | "BackgroundJobs_Context" | "Extensions" | "Exchange_KD2" | "Performance" | "VendorUpdate",
      "severity": "CRITICAL" | "HIGH" | "MEDIUM",
      "title": "Краткая суть слепой зоны",
      "technical_risk": "Технический риск (что упадет, зависнет или сломается)",
      "verification_action": "Что проверить тимлиду через MCP в базе"
    }
  ],
  "questions_for_user": [
    {
      "question": "Точный формулированный вопрос Руководителю",
      "rationale": "Зачем спрашиваем (влияние на архитектуру/бизнес)",
      "suggested_options": ["Вариант 1", "Вариант 2"]
    }
  ]
}

НЕ выводи никаких вступительных слов или markdown-блоков ```json вокруг ответа. Только чистый валидный JSON.
"""


def load_project_base_context() -> str:
    """Loads default architectural context from origami.config.json and rules."""
    ctx_parts: List[str] = []

    if CFG:
        p_name = CFG.get("project.title", "1С:Предприятие")
        ext = CFG.get("project.extensionName", "Customization")
        pfx = CFG.get("project.prefix", "ext_")
        sub = CFG.get("project.subsystem", "Customization")
        ver = CFG.get("infobase.version", "8.3.27")

        ctx_parts.append(
            f"Базовая конфигурация: {p_name}\n"
            f"Платформа 1С: {ver}\n"
            f"Текущее расширение: {ext} (префикс объектов: {pfx})\n"
            f"Подсистема доработок: {sub}"
        )

    # Загружаем правила проекта из .agents/rules/1c-project-rules.md если есть
    root_dir = CFG.root_dir if CFG else Path.cwd()
    rules_file = root_dir / ".agents" / "rules" / "1c-project-rules.md"
    if rules_file.exists():
        try:
            content = rules_file.read_text(encoding="utf-8", errors="replace")
            # Извлекаем краткие тезисы активных правил
            lines = content.splitlines()
            active_rules: List[str] = []
            for line in lines:
                if line.startswith("### R-"):
                    active_rules.append(line.replace("### ", "").strip())
                elif line.startswith("- **Правило:**") and active_rules:
                    rule_text = line.replace("- **Правило:**", "").strip()[:200]
                    active_rules[-1] += f": {rule_text}..."
            if active_rules:
                ctx_parts.append("Активные регламентные правила проекта:\n" + "\n".join(f"- {r}" for r in active_rules[:6]))
        except Exception:
            pass

    return "\n\n".join(ctx_parts)


def call_single_model(
    model_name: str,
    task_text: str,
    context_text: str,
    endpoint: str,
    api_key: str,
    timeout: int = 90
) -> Dict[str, Any]:
    """Calls OmniRoute API for a single model and parses JSON response."""
    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    user_prompt = f"### ВХОДЯЩАЯ ЗАДАЧА / ТЗ:\n{task_text}\n"
    if context_text.strip():
        user_prompt += f"\n### АРХИТЕКТУРНЫЙ И МЕТАДАННЫЙ КОНТЕКСТ ПРОЕКТА:\n{context_text}\n"

    user_prompt += (
        "\nПроведи предварительное архитектурное моделирование задачи. "
        "Вскрой скрытые предположения, слепые зоны платформы 1С и подготовь вопросы Руководителю в формате JSON."
    )

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 4096
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)
            raw_text = data["choices"][0]["message"]["content"].strip()

            # Очистка markdown блоков ```json ... ```
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            parsed = json.loads(raw_text)
            parsed["_source_model"] = model_name
            parsed["_ok"] = True
            return parsed
    except urllib.error.URLError as e:
        return {
            "_source_model": model_name,
            "_ok": False,
            "_error": f"Сетевая ошибка / таймаут: {e}",
            "blind_spots": [],
            "questions_for_user": []
        }
    except json.JSONDecodeError as e:
        return {
            "_source_model": model_name,
            "_ok": False,
            "_error": f"Ответ не является валидным JSON: {e}",
            "_raw_snippet": raw_text[:300] if 'raw_text' in locals() else "",
            "blind_spots": [],
            "questions_for_user": []
        }
    except Exception as e:
        return {
            "_source_model": model_name,
            "_ok": False,
            "_error": f"Ошибка вызова: {e}",
            "blind_spots": [],
            "questions_for_user": []
        }


def run_ensemble(
    task_text: str,
    context_text: str,
    primary_models: List[str],
    fallback_models: List[str],
    endpoint: str,
    api_key: str,
    timeout: int = 90,
    parallel: bool = True,
    min_quorum: int = 2
) -> List[Dict[str, Any]]:
    """
    Runs model ensemble with automatic quorum protection.
    If any primary model fails, fallback models are engaged to achieve min_quorum.
    """
    results: List[Dict[str, Any]] = []

    # 1. Запуск основных моделей
    if parallel and len(primary_models) > 1:
        with ThreadPoolExecutor(max_workers=len(primary_models)) as executor:
            futures = {
                executor.submit(
                    call_single_model, m, task_text, context_text, endpoint, api_key, timeout
                ): m for m in primary_models
            }
            for fut in as_completed(futures):
                model_name = futures[fut]
                try:
                    res = fut.result()
                    results.append(res)
                except Exception as e:
                    results.append({
                        "_source_model": model_name,
                        "_ok": False,
                        "_error": str(e),
                        "blind_spots": [],
                        "questions_for_user": []
                    })
    else:
        for m in primary_models:
            res = call_single_model(m, task_text, context_text, endpoint, api_key, timeout)
            results.append(res)

    # 2. Проверка кворума и дозапуск из резерва
    successful = [r for r in results if r.get("_ok", False)]
    if len(successful) < min_quorum and fallback_models:
        needed = min_quorum - len(successful)
        candidates = [fb for fb in fallback_models if fb not in primary_models][:needed]
        if candidates:
            with ThreadPoolExecutor(max_workers=len(candidates)) as fb_exec:
                fb_futs = {
                    fb_exec.submit(
                        call_single_model, fb, task_text, context_text, endpoint, api_key, timeout
                    ): fb for fb in candidates
                }
                for fut in as_completed(fb_futs):
                    fb_name = fb_futs[fut]
                    try:
                        fb_res = fut.result()
                        results.append(fb_res)
                    except Exception as e:
                        results.append({
                            "_source_model": fb_name,
                            "_ok": False,
                            "_error": str(e),
                            "blind_spots": [],
                            "questions_for_user": []
                        })

    return results


def synthesize_results(task_text: str, ensemble_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merges and synthesizes responses from multiple reasoning models with consensus calculation."""
    combined_assumptions: List[Dict[str, Any]] = []
    combined_blind_spots: List[Dict[str, Any]] = []
    combined_questions: List[Dict[str, Any]] = []
    business_goals: List[Dict[str, Any]] = []
    models_used: List[str] = []
    successful_models: List[str] = []
    errors: List[str] = []

    category_votes: Dict[str, List[str]] = {}

    for item in ensemble_results:
        model = item.get("_source_model", "unknown")
        models_used.append(model)
        if not item.get("_ok", True) or "_error" in item:
            errors.append(f"[{model}] {item.get('_error', 'Unknown error')}")
            continue

        successful_models.append(model)

        if "business_goal" in item:
            bg = item["business_goal"]
            bg["_source_model"] = model
            business_goals.append(bg)

        for a in item.get("implicit_assumptions", []):
            a["_source_model"] = model
            combined_assumptions.append(a)

        for bs in item.get("blind_spots", []):
            bs["_source_model"] = model
            cat = bs.get("category", "General")
            category_votes.setdefault(cat, []).append(model)
            combined_blind_spots.append(bs)

        for q in item.get("questions_for_user", []):
            q["_source_model"] = model
            combined_questions.append(q)

    # Подсчет консенсуса по категориям
    total_successful = len(successful_models)
    for bs in combined_blind_spots:
        cat = bs.get("category", "General")
        votes = set(category_votes.get(cat, []))
        bs["_consensus_count"] = len(votes)
        bs["_is_consensus"] = len(votes) >= 2 if total_successful >= 2 else False

    # Приоритезация: Консенсус -> Тяжесть (CRITICAL > HIGH > MEDIUM)
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    combined_blind_spots.sort(
        key=lambda x: (
            0 if x.get("_is_consensus") else 1,
            severity_order.get(x.get("severity", "MEDIUM"), 99)
        )
    )

    status = "SUCCESS" if len(successful_models) >= 2 else ("PARTIAL" if successful_models else "FAILED")

    return {
        "status": status,
        "models_queried": models_used,
        "models_responded": successful_models,
        "quorum_achieved": len(successful_models) >= 2,
        "errors": errors,
        "business_goals": business_goals,
        "implicit_assumptions": combined_assumptions,
        "blind_spots": combined_blind_spots,
        "candidate_questions": combined_questions
    }


def format_markdown_report(synth: Dict[str, Any], task_title: str) -> str:
    """Renders human-readable markdown report for developer and review."""
    total_resp = len(synth.get('models_responded', []))
    lines = [
        f"# Предварительное архитектурное моделирование 1С: {task_title}",
        f"\n**Активная коллегия ({total_resp} моделей):** {', '.join(synth.get('models_responded', []))}",
        f"**Статус кворума:** {'🟢 КВОРУМ ДОСТИГНУТ' if synth.get('quorum_achieved') else '🟡 НЕПОЛНЫЙ КВОРУМ'}\n"
    ]

    if synth.get("errors"):
        lines.append("### ⚠️ Предупреждения коллегии:")
        for err in synth["errors"]:
            lines.append(f"- {err}")
        lines.append("")

    # 1. Бизнес-цель
    bgs = synth.get("business_goals", [])
    if bgs:
        lines.append("## 1. Анализ реальной бизнес-цели (Business Goal)")
        for bg in bgs:
            lines.append(f"**Экспертиза [{bg.get('_source_model')}]:**")
            lines.append(f"- *Заявлено:* {bg.get('stated')}")
            lines.append(f"- *Истинная потребность:* **{bg.get('actual_business_need')}**")
            lines.append(f"- *Ценность и риски:* {bg.get('value_and_risk')}\n")

    # 2. Неявные предположения
    assumptions = synth.get("implicit_assumptions", [])
    if assumptions:
        lines.append("## 2. Неявные предположения (Implicit Assumptions)")
        for idx, a in enumerate(assumptions, 1):
            lines.append(f"### {idx}. {a.get('assumption')}")
            lines.append(f"- **В чем опасность в 1С:** {a.get('why_dangerous')}")
            lines.append(f"- **Проверка Тимлидом (MCP/Код):** `{a.get('verification_hint')}`")
            lines.append(f"- *(Модель: {a.get('_source_model')})*\n")

    # 3. Слепые зоны
    blind_spots = synth.get("blind_spots", [])
    if blind_spots:
        lines.append("## 3. Выявленные слепые зоны (Blind Spots 1C:Enterprise)")
        for idx, bs in enumerate(blind_spots, 1):
            sev = bs.get("severity", "MEDIUM")
            icon = "🔴" if sev == "CRITICAL" else ("🟡" if sev == "HIGH" else "🔵")
            consensus_badge = f" 🔥 **[КОНСЕНСУС {bs.get('_consensus_count')}/{total_resp}]**" if bs.get("_is_consensus") else ""
            lines.append(
                f"### {idx}. {icon} [{sev}]{consensus_badge} {bs.get('category')}: {bs.get('title')}"
            )
            lines.append(f"- **Технический риск:** {bs.get('technical_risk')}")
            lines.append(f"- **Действие по проверке (MCP):** `{bs.get('verification_action')}`")
            lines.append(f"- *(Источник: {bs.get('_source_model')})*\n")

    # 4. Рекомендуемые вопросы Руководителю
    questions = synth.get("candidate_questions", [])
    if questions:
        lines.append("## 4. Рекомендуемые вопросы Руководителю / Заказчику (AGENTS.md)")
        for idx, q in enumerate(questions, 1):
            lines.append(f"### Вопрос {idx}: {q.get('question')}")
            lines.append(f"- **Обоснование:** {q.get('rationale')}")
            opts = q.get("suggested_options", [])
            if opts:
                lines.append("- **Варианты ответа:**")
                for opt in opts:
                    lines.append(f"  - {opt}")
            lines.append(f"- *(Сформировано: {q.get('_source_model')})*\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Origami Pre-Modeling Council via OmniRoute")
    parser.add_argument("task_pos", nargs="*", help="Текст задачи (позиционный аргумент)")
    parser.add_argument("--task", "-t", default="", help="Текст задачи или путь к файлу с ТЗ/описанием")
    parser.add_argument("--context", "-c", default="", help="Фактический контекст метаданных (текст или путь к файлу)")
    parser.add_argument("--models", "-m", default="", help="Список моделей через запятую (по умолчанию из origami.config.json)")
    parser.add_argument("--timeout", type=int, default=90, help="Таймаут одного запроса в секундах")
    parser.add_argument("--json", action="store_true", help="Выводить только итоговый JSON результат")
    parser.add_argument("--out", "-o", default="", help="Каталог или файл для сохранения отчетов")

    args = parser.parse_args()

    # 1. Чтение задачи
    task_input = args.task.strip()
    if not task_input and args.task_pos:
        task_input = " ".join(args.task_pos).strip()

    if not task_input:
        parser.error("Не указана задача (передайте текст задачи или путь к файлу).")

    task_text = ""
    task_title = "Задача"
    if os.path.exists(task_input):
        task_title = Path(task_input).stem
        task_text = Path(task_input).read_text(encoding="utf-8", errors="replace")
    else:
        task_text = task_input
        task_title = task_input[:40].replace("\n", " ") + "..."

    # 2. Формирование архитектурного контекста (проектный базовый + пользовательский/MCP)
    base_proj_context = load_project_base_context()
    user_context = ""
    if args.context:
        c_input = args.context.strip()
        if os.path.exists(c_input):
            user_context = Path(c_input).read_text(encoding="utf-8", errors="replace")
        else:
            user_context = c_input

    full_context = base_proj_context
    if user_context:
        full_context += "\n\nДополнительные факты метаданных (MCP / Scout):\n" + user_context

    # 3. Настройка эндпоинта и ключа (поддержка OmniRoute, LM Studio, Ollama, OpenRouter, DeepSeek и др.)
    endpoint = CFG.get_llm_endpoint() if CFG else os.environ.get("OPENAI_BASE_URL", os.environ.get("LLM_ENDPOINT", "http://localhost:20128/v1"))
    api_key = CFG.get_llm_key() if CFG else os.environ.get("ORIGAMI_LLM_KEY", os.environ.get("OPENAI_API_KEY", ""))

    # 4. Список моделей (основные + резервные)
    primary_models: List[str] = []
    fallback_models: List[str] = []

    if args.models:
        primary_models = [m.strip() for m in args.models.split(",") if m.strip()]
    elif CFG:
        cfg_models = CFG.get("premodeling.models")
        if isinstance(cfg_models, list) and cfg_models:
            primary_models = cfg_models
        elif CFG.get("omniroute.model"):
            primary_models = [CFG.get("omniroute.model")]

        cfg_fallback = CFG.get("premodeling.fallbackModels")
        if isinstance(cfg_fallback, list):
            fallback_models = cfg_fallback

    if not primary_models:
        primary_models = ["auto/best-reasoning", "auto/best-coding", "auto/smart"]

    parallel = CFG.get("premodeling.parallel", True) if CFG else True
    timeout = args.timeout or (CFG.get("premodeling.timeoutSeconds", 90) if CFG else 90)

    # 5. Вызов ансамбля моделей
    results = run_ensemble(
        task_text, full_context, primary_models, fallback_models,
        endpoint, api_key, timeout, parallel, min_quorum=2
    )
    synth = synthesize_results(task_text, results)

    # 6. Сохранение результатов
    root_dir = CFG.root_dir if CFG else Path.cwd()
    reports_dir = root_dir / "scratch" / "premodel"
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_file = reports_dir / "premodel_last.json"
    md_file = reports_dir / "premodel_last.md"

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(synth, f, ensure_ascii=False, indent=2)

    md_content = format_markdown_report(synth, task_title)
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    # 7. Вывод
    if args.json:
        print(json.dumps(synth, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== Origami Pre-Modeling Council: {task_title} ===")
        print(f"Опрошено моделей: {len(synth.get('models_queried', []))} -> Успешно ответили: {len(synth.get('models_responded', []))} ({', '.join(synth.get('models_responded', []))})")
        print(f"Статус кворума: {'[OK] КВОРУМ ДОСТИГНУТ' if synth.get('quorum_achieved') else '[!] НЕПОЛНЫЙ КВОРУМ'}")
        bs_count = len(synth.get("blind_spots", []))
        q_count = len(synth.get("candidate_questions", []))
        print(f"Синтезировано слепых зон: {bs_count}, вопросов Руководителю: {q_count}")
        print(f"\nОтчет сохранен:\n  MD:   {md_file}\n  JSON: {json_file}\n")
        print("--------------------------------------------------------------------------------")
        print(md_content[:2000])
        if len(md_content) > 2000:
            print("\n... [Полный текст отчета смотрите в scratch/premodel/premodel_last.md]")

    sys.exit(0)


if __name__ == "__main__":
    main()
