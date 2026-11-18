# -*- coding: utf-8 -*-
"""
Origami Pre-Modeling Council (Контур предварительного моделирования 1С).
Orchestrates specialized cognitive facets (Analyst, Architect, or Combined Council)
via OmniRoute to detect process conflicts, 1C platform blind spots, and ADR alternatives.
Pure Python standard library (urllib + concurrent.futures).
"""

import sys
import os
import re
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

def load_role_prompt(role: str) -> str:
    """Loads specialized cognitive role prompt from templates/prompts/ (Single Source of Truth)."""
    root_dir = CFG.root_dir if CFG else Path(__file__).resolve().parent.parent
    candidates = [
        root_dir / "templates" / "prompts" / f"{role}_role.md",
        Path(__file__).resolve().parent.parent / "templates" / "prompts" / f"{role}_role.md",
        Path(__file__).resolve().parent / "prompts" / f"{role}_role.md"
    ]
    for c in candidates:
        if c.is_file():
            try:
                return c.read_text(encoding="utf-8").strip()
            except Exception:
                pass

    raise FileNotFoundError(
        f"Не найден файл системного промпта для роли '{role}': "
        f"ожидался в templates/prompts/{role}_role.md. "
        f"Убедитесь, что ядро синхронизировано (.\\tools\\origami.ps1 deploy update)."
    )


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

    root_dir = CFG.root_dir if CFG else Path.cwd()
    rules_file = root_dir / ".agents" / "rules" / "1c-project-rules.md"
    if rules_file.exists():
        try:
            content = rules_file.read_text(encoding="utf-8", errors="replace")
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


def extract_json_payload(raw_text: str) -> Dict[str, Any]:
    """Robustly extracts and parses JSON payload from LLM responses."""
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw_text).strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    candidate = m.group(1).strip() if m else cleaned

    try:
        return json.loads(candidate, strict=False)
    except Exception:
        pass

    start = candidate.find('{')
    end = candidate.rfind('}')
    if start != -1 and end != -1 and end > start:
        sub = candidate[start:end+1]
        try:
            return json.loads(sub, strict=False)
        except Exception:
            pass

    return json.loads(cleaned, strict=False)


def call_single_model(
    model_name: str,
    task_text: str,
    context_text: str,
    endpoint: str,
    api_key: str,
    role: str = "architect",
    timeout: int = 120
) -> Dict[str, Any]:
    """Calls OmniRoute API for a single model with a specific role prompt."""
    url = f"{endpoint.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    system_prompt = load_role_prompt(role)

    if role == "analyst":
        user_prompt = f"### ВХОДЯЩАЯ ЗАДАЧА / ОПИСАНИЕ СИТУАЦИИ:\n{task_text}\n"
        if context_text.strip():
            user_prompt += f"\n### КОНТЕКСТ ПРЕДПРИЯТИЯ И ПРОЕКТА:\n{context_text}\n"
        user_prompt += (
            "\nПроведи глубокий бизнес-анализ задачи: вскрой физический процесс, "
            "цепочку материальной ответственности, конфликт интересов сторон и сформулируй житейские вопросы Заказчику без терминов 1С."
        )
    else:
        user_prompt = f"### ВХОДЯЩАЯ ЗАДАЧА / ТЗ:\n{task_text}\n"
        if context_text.strip():
            user_prompt += f"\n### АРХИТЕКТУРНЫЙ И МЕТАДАННЫЙ КОНТЕКСТ ПРОЕКТА:\n{context_text}\n"
        user_prompt += (
            "\nПроведи предварительное техническое архитектурное моделирование задачи 1С. "
            "Вскрой скрытые технические предположения, слепые зоны платформы 1С и подготовь архитектурные альтернативы ADR в формате JSON."
        )

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
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

            parsed = extract_json_payload(raw_text)
            parsed["_source_model"] = model_name
            parsed["_role"] = role
            parsed["_ok"] = True
            return parsed
    except urllib.error.URLError as e:
        return {
            "_source_model": model_name,
            "_role": role,
            "_ok": False,
            "_error": f"Сетевая ошибка / таймаут: {e}"
        }
    except json.JSONDecodeError as e:
        return {
            "_source_model": model_name,
            "_role": role,
            "_ok": False,
            "_error": f"Ответ не является валидным JSON: {e}"
        }
    except Exception as e:
        return {
            "_source_model": model_name,
            "_role": role,
            "_ok": False,
            "_error": f"Ошибка вызова: {e}"
        }


def run_ensemble(
    task_text: str,
    context_text: str,
    primary_models: List[str],
    fallback_models: List[str],
    endpoint: str,
    api_key: str,
    role: str = "architect",
    timeout: int = 90,
    parallel: bool = True,
    min_quorum: int = 1
) -> List[Dict[str, Any]]:
    """Runs model ensemble for the given role."""
    results: List[Dict[str, Any]] = []

    if parallel and len(primary_models) > 1:
        with ThreadPoolExecutor(max_workers=len(primary_models)) as executor:
            futures = {
                executor.submit(
                    call_single_model, m, task_text, context_text, endpoint, api_key, role, timeout
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
                        "_role": role,
                        "_ok": False,
                        "_error": str(e)
                    })
    else:
        for m in primary_models:
            res = call_single_model(m, task_text, context_text, endpoint, api_key, role, timeout)
            results.append(res)

    successful = [r for r in results if r.get("_ok", False)]
    if len(successful) < min_quorum and fallback_models:
        needed = min_quorum - len(successful)
        candidates = [fb for fb in fallback_models if fb not in primary_models][:needed]
        if candidates:
            with ThreadPoolExecutor(max_workers=len(candidates)) as fb_exec:
                fb_futs = {
                    fb_exec.submit(
                        call_single_model, fb, task_text, context_text, endpoint, api_key, role, timeout
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
                            "_role": role,
                            "_ok": False,
                            "_error": str(e)
                        })

    return results


def format_analyst_markdown(item: Dict[str, Any], task_title: str) -> str:
    """Renders human-readable markdown report for the Analyst role."""
    lines = [
        f"# 📋 Бизнес-Анализ задачи: {task_title}",
        f"\n**Роль:** Ведущий Бизнес-Аналитик (Process & Conflict Discovery)",
        f"**Модель:** `{item.get('_source_model', 'unknown')}`\n"
    ]

    bg = item.get("business_goal", {})
    if bg:
        lines.append("## 1. Анализ реальной бизнес-цели")
        lines.append(f"- **Буквально заявлено:** {bg.get('stated')}")
        lines.append(f"- **Истинная потребность бизнеса:** **{bg.get('actual_business_need')}**")
        lines.append(f"- **Цена ошибки при неверном решении:** {bg.get('value_and_risk')}\n")

    plc = item.get("physical_lifecycle", {})
    if plc:
        lines.append("## 2. Физический жизненный цикл процесса")
        lines.append(f"- **Инициатор в реальном мире:** {plc.get('initiator')}")
        lines.append(f"- **Цепочка материальной ответственности:** {plc.get('custody_chain')}")
        lines.append(f"- **Точка возникновения расхождения:** ⚠️ {plc.get('discrepancy_point')}\n")

    coi = item.get("conflict_of_interests", [])
    if coi:
        lines.append("## 3. Скрытый конфликт интересов сторон")
        for idx, c in enumerate(coi, 1):
            lines.append(f"### {idx}. Сторона: {c.get('side')}")
            lines.append(f"- **В чем их интерес / за что переживают:** {c.get('concern')}")
            lines.append(f"- **Что произойдет при блокировке «в лоб»:** 🛑 {c.get('risk_if_blocked')}\n")

    vmg = item.get("vendor_methodology_gap", {})
    if vmg:
        lines.append("## 4. Соответствие типовой методологии 1С")
        lines.append(f"- **Как процесс задуман фирмой 1С:** {vmg.get('how_1c_designed_it')}")
        lines.append(f"- **Почему клиент отклонился:** {vmg.get('why_client_diverged')}\n")

    qfc = item.get("questions_for_client", [])
    if qfc:
        lines.append("## 5. Вопросы Заказчику / Директору (Без терминов 1С!)")
        for idx, q in enumerate(qfc, 1):
            lines.append(f"### Вопрос {idx}: {q.get('question')}")
            lines.append(f"- **Зачем спрашиваем:** {q.get('rationale')}")
            opts = q.get("suggested_options", [])
            if opts:
                lines.append("- **Варианты ответа:**")
                for opt in opts:
                    lines.append(f"  - {opt}")
            lines.append("")

    return "\n".join(lines)


def format_architect_markdown(item: Dict[str, Any], task_title: str) -> str:
    """Renders human-readable markdown report for the Architect role."""
    lines = [
        f"# 🏛️ Техническая Архитектура 1С: {task_title}",
        f"\n**Роль:** Principal Технический Архитектор 1С",
        f"**Модель:** `{item.get('_source_model', 'unknown')}`\n"
    ]

    ts = item.get("technical_scope", {})
    if ts:
        lines.append("## 1. Границы реализации (Scope)")
        in_s = ts.get("in_scope", [])
        if in_s:
            lines.append("**Обязательно входит (In-Scope):**")
            for i in in_s:
                lines.append(f"- [x] {i}")
        out_s = ts.get("out_of_scope", [])
        if out_s:
            lines.append("\n**Исключено из объема (Out-of-Scope):**")
            for o in out_s:
                lines.append(f"- [ ] {o}")
        lines.append("")

    assumptions = item.get("implicit_assumptions", [])
    if assumptions:
        lines.append("## 2. Неявные предположения (Implicit Assumptions)")
        for idx, a in enumerate(assumptions, 1):
            lines.append(f"### {idx}. {a.get('assumption')}")
            lines.append(f"- **В чем опасность в 1С:** {a.get('why_dangerous')}")
            lines.append(f"- **Проверка в коде/метаданных (MCP):** `{a.get('verification_hint')}`\n")

    blind_spots = item.get("blind_spots", [])
    if blind_spots:
        lines.append("## 3. Выявленные слепые зоны платформы 1С")
        for idx, bs in enumerate(blind_spots, 1):
            sev = bs.get("severity", "MEDIUM")
            icon = "🔴" if sev == "CRITICAL" else ("🟡" if sev == "HIGH" else "🔵")
            lines.append(f"### {idx}. {icon} [{sev}] {bs.get('category')}: {bs.get('title')}")
            lines.append(f"- **Технический риск:** {bs.get('technical_risk')}")
            lines.append(f"- **Действие по проверке (MCP):** `{bs.get('verification_action')}`\n")

    adr = item.get("adr_alternatives", [])
    if adr:
        lines.append("## 4. Архитектурные альтернативы (ADR)")
        for idx, alt in enumerate(adr, 1):
            lines.append(f"### Вариант {idx}: {alt.get('variant')}")
            lines.append(f"- **Плюсы:** {alt.get('pros')}")
            lines.append(f"- **Минусы и риски:** {alt.get('cons_and_risks')}")
            lines.append(f"- **Влияние на обновление вендора:** `{alt.get('vendor_impact')}`\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Origami Cognitive Facets Council via OmniRoute")
    parser.add_argument("task_pos", nargs="*", help="Текст задачи (позиционный аргумент)")
    parser.add_argument("--task", "-t", default="", help="Текст задачи или путь к файлу с ТЗ/описанием")
    parser.add_argument("--role", "-r", default="all", choices=["analyst", "architect", "all"],
                        help="Когнитивная грань: analyst (Бизнес-Анализ), architect (Архитектура 1С), all (Обе грани)")
    parser.add_argument("--context", "-c", default="", help="Фактический контекст метаданных (текст или путь к файлу)")
    parser.add_argument("--models", "-m", default="", help="Список моделей через запятую")
    parser.add_argument("--timeout", type=int, default=90, help="Таймаут одного запроса в секундах")
    parser.add_argument("--json", action="store_true", help="Выводить только итоговый JSON результат")

    args = parser.parse_args()

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
        full_context += "\n\nДополнительный контекст (MCP / Scout):\n" + user_context

    endpoint = CFG.get_llm_endpoint() if CFG else os.environ.get("OPENAI_BASE_URL", os.environ.get("LLM_ENDPOINT", "http://localhost:20128/v1"))
    api_key = CFG.get_llm_key() if CFG else os.environ.get("ORIGAMI_LLM_KEY", os.environ.get("OPENAI_API_KEY", ""))

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
        primary_models = ["auto/best-reasoning", "auto/smart"]

    roles_to_run = ["analyst", "architect"] if args.role == "all" else [args.role]
    output_bundle: Dict[str, Any] = {"task_title": task_title, "roles": {}}
    md_sections: List[str] = []

    for r in roles_to_run:
        # Для роли выбираем ведущую модель из пула
        res = run_ensemble(
            task_text, full_context, primary_models[:1], fallback_models,
            endpoint, api_key, role=r, timeout=args.timeout, parallel=False, min_quorum=1
        )
        if res:
            item = res[0]
            output_bundle["roles"][r] = item
            if r == "analyst":
                md_sections.append(format_analyst_markdown(item, task_title))
            else:
                md_sections.append(format_architect_markdown(item, task_title))

    root_dir = CFG.root_dir if CFG else Path.cwd()
    reports_dir = root_dir / "scratch" / "premodel"
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_file = reports_dir / f"premodel_{args.role}_last.json"
    md_file = reports_dir / f"premodel_{args.role}_last.md"

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(output_bundle, f, ensure_ascii=False, indent=2)

    full_md = "\n\n---\n\n".join(md_sections)
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(full_md)

    if args.json:
        print(json.dumps(output_bundle, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== Origami Pre-Modeling: {task_title} (Фасет: {args.role.upper()}) ===")
        print(f"Отчет сохранен:\n  MD:   {md_file}\n  JSON: {json_file}\n")
        print("--------------------------------------------------------------------------------")
        print(full_md[:2500])
        if len(full_md) > 2500:
            print(f"\n... [Полный текст отчета смотрите в {md_file}]")

    sys.exit(0)


if __name__ == "__main__":
    main()
