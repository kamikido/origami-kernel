# -*- coding: utf-8 -*-
"""
Origami Kernel — Environment Doctor & Capability Matrix Inspector.
Inspects host developer machine, detects available 1C tooling, determines
graceful degradation level (L1/L2/L3), and suggests non-intrusive remediation.
Pure Python standard library.
"""

import os
import sys
import json
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add current dir to path to import origami_config
cur_dir = Path(__file__).resolve().parent
if str(cur_dir) not in sys.path:
    sys.path.insert(0, str(cur_dir))

try:
    from origami_config import get_config
    CFG = get_config()
except Exception:
    CFG = None


KNOWN_PATHS = {
    "git": [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"D:\Git\cmd\git.exe",
        r"E:\Git\cmd\git.exe",
    ],
    "onescript": [
        r"C:\Program Files\OneScript\bin\oscript.exe",
        r"C:\Program Files (x86)\OneScript\bin\oscript.exe",
        r"D:\OneScript\bin\oscript.exe",
        r"E:\OneScript\bin\oscript.exe",
    ],
    "phoenixbsl": [
        r"C:\phoenixbsl\phoenixbsl.exe",
        r"D:\phoenixbsl\phoenixbsl.exe",
        r"E:\phoenixbsl\phoenixbsl.exe",
    ],
    "sslhelp": [
        r"C:\sslhelp\sslhelp.exe",
        r"D:\sslhelp\sslhelp.exe",
        r"E:\sslhelp\sslhelp.exe",
    ],
    "platform_roots": [
        r"C:\Program Files\1cv8",
        r"C:\Program Files (x86)\1cv8",
        r"D:\Program Files\1cv8",
        r"E:\Program Files\1cv8",
    ]
}


def find_binary(name: str, candidate_paths: List[str]) -> Optional[str]:
    """Finds binary via PATH or fallback to well-known disk paths."""
    in_path = shutil.which(name)
    if in_path:
        return in_path
    for c in candidate_paths:
        if os.path.exists(c):
            return c
    return None


def detect_1c_platform() -> Tuple[Optional[str], Optional[str], List[str]]:
    """Detects installed 1C platform versions and returns newest 1cv8.exe/ibcmd.exe."""
    versions = []
    newest_v8 = None
    newest_ibcmd = None

    for root in KNOWN_PATHS["platform_roots"]:
        if os.path.exists(root):
            try:
                for entry in os.listdir(root):
                    full_p = os.path.join(root, entry)
                    if os.path.isdir(full_p) and (entry.startswith("8.3.") or entry.startswith("8.5.")):
                        versions.append(entry)
                        v8_bin = os.path.join(full_p, "bin", "1cv8.exe")
                        ibcmd_bin = os.path.join(full_p, "bin", "ibcmd.exe")
                        if os.path.exists(v8_bin):
                            newest_v8 = v8_bin
                        if os.path.exists(ibcmd_bin):
                            newest_ibcmd = ibcmd_bin
            except Exception:
                pass

    versions.sort(reverse=True)
    return newest_v8, newest_ibcmd, versions


def check_omniroute(endpoint: str = "http://localhost:20128") -> Tuple[bool, str]:
    """Checks if OmniRoute local LLM proxy is responding."""
    url = f"{endpoint.rstrip('/')}/v1/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Origami-Doctor"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status in (200, 401, 403):  # 401/403 means proxy is alive and requires key
                return True, f"Активен ({endpoint})"
            return True, f"Отвечает с кодом {resp.status}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return True, f"Активен ({endpoint}, защищен ключом)"
        return False, f"Ошибка HTTP {e.code}"
    except Exception as e:
        return False, f"Не отвечает ({e})"


def run_doctor() -> Dict[str, Any]:
    """Performs full diagnostic audit of developer machine."""
    results: Dict[str, Any] = {
        "python": {"version": sys.version.split()[0], "ok": True, "path": sys.executable},
        "git": {"ok": False, "path": None, "remediation": None},
        "onescript": {"ok": False, "path": None, "remediation": None},
        "platform_1c": {"ok": False, "path": None, "ibcmd": None, "versions": []},
        "omniroute": {"ok": False, "status": ""},
        "level": "L1",
        "level_name": "L1: Standalone Core (Zero-Dependency)",
        "capabilities": [],
        "warnings": []
    }

    # 1. Git
    git_path = find_binary("git", KNOWN_PATHS["git"])
    if git_path:
        results["git"]["ok"] = True
        results["git"]["path"] = git_path
    else:
        results["git"]["remediation"] = (
            "Git не найден в PATH. Установите: 'winget install Git.Git' "
            "или добавьте 'E:\\Git\\cmd' в системную переменную PATH."
        )
        results["warnings"].append("Git отсутствует: сравнение с базовыми коммитами отключено.")

    # 2. OneScript
    oscript_path = find_binary("oscript", KNOWN_PATHS["onescript"])
    if oscript_path:
        results["onescript"]["ok"] = True
        results["onescript"]["path"] = oscript_path
    else:
        results["onescript"]["remediation"] = (
            "OneScript не найден. Установите: 'winget install OneScript.OneScript' "
            "или добавьте 'E:\\OneScript\\bin' в системный PATH."
        )
        results["warnings"].append("OneScript отсутствует: автоформатирование BSL на лету будет пропущено.")

    # 3. 1C Platform
    v8_bin, ibcmd_bin, versions = detect_1c_platform()
    if v8_bin:
        results["platform_1c"]["ok"] = True
        results["platform_1c"]["path"] = v8_bin
        results["platform_1c"]["ibcmd"] = ibcmd_bin
        results["platform_1c"]["versions"] = versions
    else:
        results["warnings"].append("Платформа 1С:Предприятие не обнаружена в Program Files.")

    # 4. OmniRoute
    omni_endpoint = CFG.get("omniroute.endpoint", "http://localhost:20128") if CFG else "http://localhost:20128"
    omni_ok, omni_msg = check_omniroute(omni_endpoint)
    results["omniroute"]["ok"] = omni_ok
    results["omniroute"]["status"] = omni_msg
    if not omni_ok:
        results["warnings"].append(f"OmniRoute оффлайн: консилиум моделей переключится в одиночный режим агента.")

    # 5. Determine Capability Level
    # L1: Python is working (always true if we are running)
    results["capabilities"].append("Pure-Diff BSL Линтер (lint_bsl_diff.py)")
    results["capabilities"].append("Синтез ТЗ разработчика по стандарту Invariant-Driven Development")
    results["capabilities"].append("Системные сторожевые хуки IDE (hooks.json)")

    if omni_ok:
        results["capabilities"].append("Консилиум моделей Pre-Modeling Council (premodel.py)")
        results["capabilities"].append("Adversarial AI Review (adversarial_review.py)")

    if results["onescript"]["ok"]:
        results["level"] = "L2"
        results["level_name"] = "L2: DevTools Active (OneScript + Linter + AST)"
        results["capabilities"].append("Автоформатирование BSL (format_bsl.os --diff)")

    if results["platform_1c"]["ok"]:
        results["level"] = "L3"
        results["level_name"] = "L3: Enterprise Full (1C Runtime + COM + Vanessa + Build)"
        results["capabilities"].append("COM-запросы к данным (query.os / COMConnector)")
        results["capabilities"].append("Сборка пакетов поставки (.cfe / .epf)")
        results["capabilities"].append("Автотесты Vanessa-Automation")

    return results


def print_doctor_report(res: Dict[str, Any]) -> None:
    """Prints rich human-readable doctor report."""
    print("\n" + "=" * 78)
    print("                 ORIGAMI KERNEL — ДИАГНОСТИКА ОКРУЖЕНИЯ")
    print("=" * 78)

    # Status table
    def status_badge(ok: bool) -> str:
        return "[OK]" if ok else "[WARN]"

    print(f"\n1. Программный стек машины разработчика:")
    print(f"  {status_badge(res['python']['ok'])} Python:        {res['python']['version']} ({res['python']['path']})")

    git_stat = f"{res['git']['path']}" if res['git']['ok'] else "Отсутствует в PATH"
    print(f"  {status_badge(res['git']['ok'])} Git:           {git_stat}")

    oscript_stat = f"{res['onescript']['path']}" if res['onescript']['ok'] else "Отсутствует в PATH"
    print(f"  {status_badge(res['onescript']['ok'])} OneScript:     {oscript_stat}")

    v8_stat = f"{res['platform_1c']['path']} (найдено версий: {len(res['platform_1c']['versions'])})" if res['platform_1c']['ok'] else "Не найдена в Program Files"
    print(f"  {status_badge(res['platform_1c']['ok'])} Платформа 1С:  {v8_stat}")

    print(f"  {status_badge(res['omniroute']['ok'])} OmniRoute:     {res['omniroute']['status']}")

    print(f"\n2. Активный уровень отказоустойчивости (Capability Level):")
    print(f"  >>> {res['level_name']} <<<")

    print(f"\n3. Доступные возможности системы:")
    for cap in res["capabilities"]:
        print(f"  + {cap}")

    if res["warnings"]:
        print(f"\n4. Предупреждения и рекомендации:")
        for w in res["warnings"]:
            print(f"  ! {w}")

        if res["git"]["remediation"]:
            print(f"  -> {res['git']['remediation']}")
        if res["onescript"]["remediation"]:
            print(f"  -> {res['onescript']['remediation']}")

    print("\n" + "=" * 78 + "\n")


def main() -> None:
    json_mode = "--json" in sys.argv
    res = run_doctor()
    if json_mode:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_doctor_report(res)


if __name__ == "__main__":
    main()
