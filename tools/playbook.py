# -*- coding: utf-8 -*-
"""
Origami Playbook Manager (Менеджер архитектурных плейбуков Origami Kernel).
Позволяет разработчикам и агентам просматривать, искать и читать стандарты
долговременной памяти (knowledge/playbooks/) без расхода системного контекста IDE.
Pure Python standard library.
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

# Обеспечиваем UTF-8 вывод на консоль Windows
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


def get_playbooks_dir() -> Path:
    """Определяет путь к каталогу knowledge/playbooks."""
    cur_dir = Path(__file__).resolve().parent
    project_root = cur_dir.parent
    playbooks_dir = project_root / "knowledge" / "playbooks"
    return playbooks_dir


def parse_playbook(file_path: Path) -> Dict[str, Any]:
    """Извлекает заголовок, назначение и ключевые инварианты из файла плейбука."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    
    title = file_path.stem
    purpose = ""
    invariants: List[str] = []
    
    # 1. Извлечение заголовка (# ...)
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        
    # 2. Назначение (Из блока > **Назначение стандарта:** ...)
    purpose_match = re.search(r">\s*\*\*Назначение стандарта:\*\*\s*(.+)", content)
    if purpose_match:
        purpose = purpose_match.group(1).strip()
    else:
        # Попробуем первый блок цитаты
        quote_match = re.search(r">\s*(.+)", content)
        if quote_match:
            purpose = quote_match.group(1).strip()

    # 3. Инварианты
    for line in content.splitlines():
        if re.search(r"^\s*-\s*\*\*(Инвариант\s*\d+|Табу|Правило|Архитектурное правило)[^:]*\*\*:\s*(.+)", line):
            m = re.search(r"^\s*-\s*\*\*(.+?)\*\*:\s*(.+)", line)
            if m:
                invariants.append(f"{m.group(1)}: {m.group(2)}")
                
    return {
        "id": file_path.stem,
        "filename": file_path.name,
        "path": str(file_path),
        "title": title,
        "purpose": purpose,
        "invariants": invariants,
        "size_bytes": file_path.stat().st_size
    }


def list_playbooks(playbooks_dir: Path) -> List[Dict[str, Any]]:
    """Возвращает список всех зарегистрированных плейбуков."""
    if not playbooks_dir.exists():
        return []
    
    items = []
    for f in sorted(playbooks_dir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        try:
            items.append(parse_playbook(f))
        except Exception as e:
            items.append({
                "id": f.stem,
                "filename": f.name,
                "path": str(f),
                "title": f.name,
                "purpose": f"Ошибка чтения: {e}",
                "invariants": [],
                "size_bytes": 0
            })
    return items


def find_playbooks(query: str, playbooks_dir: Path) -> List[Dict[str, Any]]:
    """Полнотекстовый поиск плейбуков по ключевым словам."""
    all_pbs = list_playbooks(playbooks_dir)
    query_lower = query.lower()
    matches = []
    
    for pb in all_pbs:
        score = 0
        file_content = Path(pb["path"]).read_text(encoding="utf-8", errors="replace").lower()
        
        if query_lower in pb["id"].lower():
            score += 10
        if query_lower in pb["title"].lower():
            score += 8
        if query_lower in pb["purpose"].lower():
            score += 5
        if query_lower in file_content:
            score += 2
            
        if score > 0:
            pb_copy = dict(pb)
            pb_copy["relevance"] = score
            matches.append(pb_copy)
            
    matches.sort(key=lambda x: x["relevance"], reverse=True)
    return matches


def main():
    parser = argparse.ArgumentParser(description="Origami Playbook Manager — Long-Term Memory of 1C Architecture")
    parser.add_argument("command", nargs="?", default="list", choices=["list", "find", "read", "show"], help="Команда: list, find, read")
    parser.add_argument("query", nargs="?", default="", help="Поисковый запрос или имя плейбука")
    parser.add_argument("--json", action="store_true", help="Выводить результат в формате JSON")
    
    args = parser.parse_args()
    playbooks_dir = get_playbooks_dir()
    
    if not playbooks_dir.exists():
        if args.json:
            print(json.dumps({"error": f"Каталог не найден: {playbooks_dir}"}, ensure_ascii=False))
        else:
            print(f"[!] Каталог плейбуков не найден: {playbooks_dir}")
        sys.exit(1)
        
    cmd = args.command.lower()
    
    if cmd == "list":
        pbs = list_playbooks(playbooks_dir)
        if args.json:
            print(json.dumps(pbs, ensure_ascii=False, indent=2))
        else:
            print("\n" + "=" * 80)
            print("  ORIGAMI KERNEL — РЕЕСТР АРХИТЕКТУРНЫХ ПЛЕЙБУКОВ (ДОЛГОВРЕМЕННАЯ ПАМЯТЬ)")
            print("=" * 80)
            print(f"Каталог: {playbooks_dir}\n")
            
            for idx, pb in enumerate(pbs, 1):
                print(f"[{idx}] {pb['title']}")
                print(f"    Файл: knowledge/playbooks/{pb['filename']}")
                if pb['purpose']:
                    print(f"    Назначение: {pb['purpose']}")
                if pb['invariants']:
                    print("    Ключевые инварианты:")
                    for inv in pb['invariants'][:3]:
                        print(f"      • {inv}")
                print("-" * 80)
            print(f"\nВсего плейбуков: {len(pbs)}. Расход токенов в системном промпте IDE: 0.")
            print("Использование: .\\tools\\origami.ps1 playbook find <тема> | read <имя>")
            
    elif cmd in ("find", "search"):
        if not args.query:
            print("Ошибка: укажите ключевое слово для поиска. Пример: origami playbook find ущерб")
            sys.exit(1)
            
        matches = find_playbooks(args.query, playbooks_dir)
        if args.json:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
        else:
            print(f"\nРезультаты поиска по запросу '{args.query}': найдено {len(matches)}\n")
            for m in matches:
                print(f"• [{m['id']}] {m['title']}")
                print(f"  Файл: knowledge/playbooks/{m['filename']}")
                if m['purpose']:
                    print(f"  Суть: {m['purpose']}")
                print()
                
    elif cmd in ("read", "show"):
        if not args.query:
            print("Ошибка: укажите имя плейбука для чтения. Пример: origami playbook read pb_damage_accounting_registers")
            sys.exit(1)
            
        target = args.query
        if not target.endswith(".md"):
            target += ".md"
            
        file_path = playbooks_dir / target
        if not file_path.exists():
            # Попробуем нечеткий поиск
            matches = find_playbooks(args.query, playbooks_dir)
            if matches:
                file_path = Path(matches[0]["path"])
            else:
                print(f"Плейбук '{args.query}' не найден в {playbooks_dir}")
                sys.exit(1)
                
        content = file_path.read_text(encoding="utf-8", errors="replace")
        print(content)


if __name__ == "__main__":
    main()
