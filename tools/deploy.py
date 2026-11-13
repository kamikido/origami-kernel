# -*- coding: utf-8 -*-
"""
Origami Kernel — Deployment & Project Synchronization Manager.
Deploys, upgrades, and audits Origami platform components across downstream projects.
Pure Python standard library.
"""

import sys
import os
import shutil
import filecmp
import json
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

KERNEL_DIR = Path(__file__).resolve().parent.parent


def get_workspace_projects() -> List[Path]:
    """Resolves tracked projects from optional local origami.workspace.json or returns empty list."""
    ws_file = KERNEL_DIR / "origami.workspace.json"
    if ws_file.exists():
        try:
            with open(ws_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            projects = [Path(p) for p in data.get("projects", [])]
            return [p for p in projects if p.exists()]
        except Exception:
            pass
    return []


# Core files and directories managed strictly by the Kernel
KERNEL_MANAGED_ITEMS = [
    "tools/origami.ps1",
    "tools/origami_config.py",
    "tools/doctor.py",
    "tools/premodel.py",
    "tools/feedback.py",
    "tools/adversarial_review.py",
    "tools/lint_bsl_diff.py",
    "tools/common.ps1",
    "tools/query.os",
    "tools/format_bsl",
    "tools/hooks",
    ".agents/hooks.json",
    ".agents/plugins.json",
    ".agents/plugins/origami-platform",
    ".bsl-language-server.json",
    "templates",
    "knowledge",
]

# Sensitive project files NEVER overwritten during 'update'
PROTECTED_PROJECT_FILES = [
    "origami.config.json",
    "origami.workspace.json",
    "autumn-properties.json",
    ".agents/rules/1c-project-rules.md",
    "build",
    "tests",
    "scratch",
]


def confirm_session_kill(force: bool = False) -> bool:
    """Requires explicit confirmation before killing 1C user sessions."""
    if force:
        return True
    print("\n[ВНИМАНИЕ] Операция требует сброса активных сеансов пользователей в информационной базе 1С.")
    try:
        ans = input("Подтверждаете сброс сеансов? (y/N): ").strip().lower()
        return ans in ("y", "yes", "д", "да")
    except (EOFError, KeyboardInterrupt):
        return False


def check_agents_md(target_dir: Path) -> Optional[str]:
    """Checks synchronization of kernel rules block in downstream AGENTS.md."""
    agents_file = target_dir / "AGENTS.md"
    if not agents_file.exists():
        return "Отсутствует: AGENTS.md"
    kernel_agents = KERNEL_DIR / "templates" / "AGENTS.template.md"
    if not kernel_agents.exists():
        return None
    try:
        import re
        k_text = kernel_agents.read_text(encoding="utf-8")
        t_text = agents_file.read_text(encoding="utf-8")
        k_match = re.search(r"<!-- origami-kernel-rules -->(.*?)<!-- /origami-kernel-rules -->", k_text, re.DOTALL)
        t_match = re.search(r"<!-- origami-kernel-rules -->(.*?)<!-- /origami-kernel-rules -->", t_text, re.DOTALL)
        if k_match and t_match:
            if k_match.group(1).strip() != t_match.group(1).strip():
                return "Отличается: блок правил ядра в AGENTS.md"
        elif not t_match:
            return "Устаревший формат AGENTS.md (отсутствуют метки origami-kernel-rules)"
    except Exception:
        pass
    return None


def update_agents_md(target_dir: Path, dry_run: bool = False) -> Optional[str]:
    """Safely updates kernel rules block in downstream AGENTS.md without touching project overlay."""
    agents_file = target_dir / "AGENTS.md"
    kernel_agents = KERNEL_DIR / "templates" / "AGENTS.template.md"
    if not kernel_agents.exists():
        return None

    if not agents_file.exists():
        if not dry_run:
            tmpl = KERNEL_DIR / "templates" / "AGENTS.template.md"
            if tmpl.exists():
                shutil.copy2(tmpl, agents_file)
        return "Создан: AGENTS.md"

    try:
        import re
        k_text = kernel_agents.read_text(encoding="utf-8")
        t_text = agents_file.read_text(encoding="utf-8")
        k_match = re.search(r"<!-- origami-kernel-rules -->(.*?)<!-- /origami-kernel-rules -->", k_text, re.DOTALL)
        t_match = re.search(r"<!-- origami-kernel-rules -->(.*?)<!-- /origami-kernel-rules -->", t_text, re.DOTALL)
        if k_match and t_match:
            if k_match.group(1).strip() != t_match.group(1).strip():
                if not dry_run:
                    new_text = t_text[:t_match.start(1)] + k_match.group(1) + t_text[t_match.end(1):]
                    agents_file.write_text(new_text, encoding="utf-8")
                return "Обновлен: блок правил ядра в AGENTS.md"
    except Exception:
        pass
    return None


def audit_project(target_dir: Path) -> Tuple[bool, List[str]]:
    """Audits a downstream project against Kernel."""
    if not target_dir.exists():
        return False, [f"Каталог проекта не существует: {target_dir}"]

    diffs = []
    for rel_path in KERNEL_MANAGED_ITEMS:
        src = KERNEL_DIR / rel_path
        dst = target_dir / rel_path

        if not dst.exists():
            diffs.append(f"Отсутствует: {rel_path}")
            continue

        if src.is_dir():
            for s_child in src.rglob("*"):
                if s_child.is_file():
                    child_rel = s_child.relative_to(KERNEL_DIR)
                    d_child = target_dir / child_rel
                    if not d_child.exists():
                        diffs.append(f"Отсутствует: {child_rel}")
                    elif not filecmp.cmp(s_child, d_child, shallow=False):
                        diffs.append(f"Отличается: {child_rel}")
        else:
            if not filecmp.cmp(src, dst, shallow=False):
                diffs.append(f"Отличается: {rel_path}")

    # Check AGENTS.md kernel rules block
    agents_diff = check_agents_md(target_dir)
    if agents_diff:
        diffs.append(agents_diff)

    return len(diffs) == 0, diffs


def update_project(target_dir: Path, dry_run: bool = False) -> List[str]:
    """Safely deploys Kernel updates to downstream project."""
    if not target_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {target_dir}")

    actions = []
    for rel_path in KERNEL_MANAGED_ITEMS:
        src = KERNEL_DIR / rel_path
        dst = target_dir / rel_path

        if not src.exists():
            continue

        if src.is_dir():
            for s_child in src.rglob("*"):
                if s_child.is_file():
                    child_rel = s_child.relative_to(KERNEL_DIR)
                    d_child = target_dir / child_rel
                    
                    # Skip protected files
                    if any(child_rel.as_posix().startswith(p) for p in PROTECTED_PROJECT_FILES):
                        continue

                    need_copy = False
                    if not d_child.exists():
                        need_copy = True
                        actions.append(f"Создан: {child_rel}")
                    elif not filecmp.cmp(s_child, d_child, shallow=False):
                        need_copy = True
                        actions.append(f"Обновлен: {child_rel}")

                    if need_copy and not dry_run:
                        d_child.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(s_child, d_child)
        else:
            if any(Path(rel_path).as_posix().startswith(p) for p in PROTECTED_PROJECT_FILES):
                continue

            need_copy = False
            if not dst.exists():
                need_copy = True
                actions.append(f"Создан: {rel_path}")
            elif not filecmp.cmp(src, dst, shallow=False):
                need_copy = True
                actions.append(f"Обновлен: {rel_path}")

            if need_copy and not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    agents_act = update_agents_md(target_dir, dry_run=dry_run)
    if agents_act:
        actions.append(agents_act)

    return actions


def find_installed_1c_versions() -> List[str]:
    """Finds all installed 1C:Enterprise versions on the machine."""
    roots = [
        r"C:\Program Files\1cv8",
        r"C:\Program Files (x86)\1cv8"
    ]
    versions = set()
    for root_str in roots:
        root_p = Path(root_str)
        if root_p.exists():
            for child in root_p.iterdir():
                if child.is_dir() and (child / "bin" / "1cv8.exe").exists():
                    versions.add(child.name)
    def ver_key(v: str):
        try:
            return [int(x) for x in v.split(".")]
        except Exception:
            return [0]
    return sorted(list(versions), key=ver_key, reverse=True)


def resolve_platform_version(explicit_version: Optional[str] = None) -> Tuple[str, str]:
    """
    Resolves (full_version, major_minor_version).
    Example: ('8.3.27.2342', '8.3.27')
    """
    if explicit_version:
        parts = explicit_version.split(".")
        short = ".".join(parts[:3]) if len(parts) >= 3 else explicit_version
        return explicit_version, short

    found = find_installed_1c_versions()
    if not found:
        default_v = "8.3.27.2342"
        if sys.stdin.isatty():
            try:
                ans = input(f"Установленные платформы 1С не найдены. Введите версию [{default_v}]: ").strip()
                if ans:
                    default_v = ans
            except Exception:
                pass
        parts = default_v.split(".")
        short = ".".join(parts[:3]) if len(parts) >= 3 else default_v
        return default_v, short

    if len(found) == 1:
        v = found[0]
        parts = v.split(".")
        short = ".".join(parts[:3]) if len(parts) >= 3 else v
        print(f"  [i] Найдена платформа 1С: {v}")
        return v, short

    # Multiple versions found
    if sys.stdin.isatty():
        print("  [?] Обнаружено несколько версий платформы 1С:")
        for idx, v in enumerate(found, 1):
            rec = " (Рекомендуется)" if idx == 1 else ""
            print(f"      {idx}) {v}{rec}")
        try:
            choice = input(f"  Выберите версию [1-{len(found)}, по умолчанию 1]: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(found):
                selected = found[int(choice) - 1]
            else:
                selected = found[0]
        except Exception:
            selected = found[0]
    else:
        # Pick the highest 8.3 version if possible
        v83 = [v for v in found if v.startswith("8.3")]
        selected = v83[0] if v83 else found[0]
        print(f"  [i] Автоматически выбрана старшая версия платформы: {selected}")

    parts = selected.split(".")
    short = ".".join(parts[:3]) if len(parts) >= 3 else selected
    return selected, short


def init_project(target_dir: Path, name: str, prefix: str, ext: str, ib: str, v8version: Optional[str] = None, db_user: Optional[str] = None) -> None:
    """Bootstraps a brand new 1C project with Origami platform components."""
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"Инициализация проекта Origami в {target_dir}...")
    full_v8, short_v8 = resolve_platform_version(v8version)

    user = db_user
    if not user:
        if sys.stdin.isatty():
            try:
                u_in = input("Имя пользователя ИБ [Администратор]: ").strip()
                user = u_in if u_in else "Администратор"
            except Exception:
                user = "Администратор"
        else:
            user = "Администратор"

    update_project(target_dir, dry_run=False)

    # 1. Generate origami.config.json from template if not present
    cfg_file = target_dir / "origami.config.json"
    if not cfg_file.exists():
        tmpl_file = KERNEL_DIR / "templates" / "origami.config.template.json"
        if tmpl_file.exists():
            with open(tmpl_file, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace("{{PROJECT_NAME}}", name)
            content = content.replace("{{PROJECT_TITLE}}", f"1С:Предприятие ({name})")
            content = content.replace("{{PREFIX}}", prefix)
            content = content.replace("{{EXTENSION_NAME}}", ext)
            content = content.replace("{{EXTENSION_SRC}}", ext)
            content = content.replace("{{SUBSYSTEM}}", f"{prefix}Main")
            content = content.replace("{{INFOBASE_PATH}}", ib.replace("\\", "\\\\"))
            content = content.replace("{{DB_USER}}", user)
            content = content.replace("{{PLATFORM_VERSION}}", short_v8)
            with open(cfg_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [+] Создан origami.config.json (платформа {short_v8})")

    # 2. Generate autumn-properties.json from template if not present
    autumn_file = target_dir / "autumn-properties.json"
    if not autumn_file.exists():
        tmpl_autumn = KERNEL_DIR / "templates" / "autumn-properties.template.json"
        if tmpl_autumn.exists():
            with open(tmpl_autumn, "r", encoding="utf-8") as f:
                content = f.read()
            ib_conn = f"File='{ib}';" if not ib.startswith("srvr=") else ib
            content = content.replace("{{IBCONNECTION}}", ib_conn.replace("\\", "\\\\"))
            content = content.replace("{{V8_VERSION}}", full_v8)
            content = content.replace("{{DB_USER}}", user)
            with open(autumn_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [+] Создан autumn-properties.json (v8version {full_v8})")

    # 3. Generate .agents/rules/1c-project-rules.md from template if not present
    rules_file = target_dir / ".agents" / "rules" / "1c-project-rules.md"
    if not rules_file.exists():
        tmpl_rules = KERNEL_DIR / "templates" / "1c-project-rules.template.md"
        if tmpl_rules.exists():
            with open(tmpl_rules, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace("{{PREFIX}}", prefix)
            rules_file.parent.mkdir(parents=True, exist_ok=True)
            with open(rules_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  [+] Создан .agents/rules/1c-project-rules.md")

    # 4. Generate AGENTS.md from template if not present
    agents_file = target_dir / "AGENTS.md"
    if not agents_file.exists():
        tmpl_agents = KERNEL_DIR / "templates" / "AGENTS.template.md"
        if tmpl_agents.exists():
            shutil.copy2(tmpl_agents, agents_file)
            print(f"  [+] Создан AGENTS.md")

    print("\nПроект успешно инициализирован! Запуск первичной диагностики окружения:")
    doctor_script = target_dir / "tools" / "doctor.py"
    if doctor_script.exists():
        import subprocess
        subprocess.run([sys.executable, str(doctor_script)])


def main() -> None:
    parser = argparse.ArgumentParser(description="Origami Kernel Deployment Manager")
    subparsers = parser.add_subparsers(dest="subcommand", help="Команды")

    # status
    p_stat = subparsers.add_parser("status", help="Аудит соответствия проектов эталонному ядру")
    p_stat.add_argument("--target", default="all", help="Путь к проекту или 'all'")

    # update
    p_upd = subparsers.add_parser("update", help="Накатить обновления ядра на проекты")
    p_upd.add_argument("--target", default="all", help="Путь к проекту или 'all'")
    p_upd.add_argument("--dry-run", action="store_true", help="Режим имитации (без записи)")
    p_upd.add_argument("--force", action="store_true", help="Не запрашивать подтверждений")

    # init
    p_init = subparsers.add_parser("init", help="Развернуть новый проект Origami с нуля")
    p_init.add_argument("--target", required=True, help="Каталог целевого проекта")
    p_init.add_argument("--name", default="MyProject", help="Имя проекта")
    p_init.add_argument("--prefix", default="ext_", help="Префикс метаданных (например: ext_)")
    p_init.add_argument("--extension", default="Customization", help="Имя расширения 1С")
    p_init.add_argument("--infobase", default=r"D:\1C base\my_project", help="Путь к ИБ")
    p_init.add_argument("--v8version", default=None, help="Версия платформы 1С (например, 8.3.27.2342)")
    p_init.add_argument("--user", default=None, help="Имя пользователя ИБ")

    args = parser.parse_args()

    ws_projects = get_workspace_projects()

    if not args.subcommand or args.subcommand == "status":
        if not getattr(args, "target", None) or args.target == "all":
            targets = ws_projects
        else:
            targets = [Path(args.target)]

        print(f"\n=== Origami Kernel: Аудит соответствия проектов ===")
        print(f"Эталонное ядро (Upstream): {KERNEL_DIR}\n")
        if not targets:
            print("Не указаны целевые проекты (передайте --target <путь> или настройте origami.workspace.json).")
            return

        all_ok = True
        for t in targets:
            ok, diffs = audit_project(t)
            status_text = "[OK] Полностью синхронизирован" if ok else f"[WARN] Отличий: {len(diffs)}"
            print(f"Проект: {t.name} ({t}) -> {status_text}")
            if not ok:
                all_ok = False
                for d in diffs[:8]:
                    print(f"   - {d}")
                if len(diffs) > 8:
                    print(f"   ... еще {len(diffs)-8} отличий")
        if all_ok:
            print("\nВсе проверенные проекты на 100% соответствуют эталонному ядру Origami!")

    elif args.subcommand == "update":
        if args.target == "all":
            targets = ws_projects
        else:
            targets = [Path(args.target)]

        if not targets:
            print("Не указаны целевые проекты для обновления (--target <путь> или origami.workspace.json).")
            return

        mode_str = "[DRY-RUN]" if args.dry_run else "[UPDATE]"
        print(f"\n=== Origami Kernel: Обновление проектов {mode_str} ===")
        for t in targets:
            print(f"\nПроект: {t.name} ({t})")
            try:
                actions = update_project(t, dry_run=args.dry_run)
                if not actions:
                    print("  -> Проект уже синхронизирован с ядром.")
                else:
                    for a in actions:
                        print(f"  -> {a}")
            except Exception as e:
                print(f"  [ERROR] Сбой обновления: {e}")

    elif args.subcommand == "init":
        t = Path(args.target)
        init_project(t, args.name, args.prefix, args.extension, args.infobase, v8version=args.v8version, db_user=args.user)


if __name__ == "__main__":
    main()
