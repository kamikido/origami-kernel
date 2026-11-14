# -*- coding: utf-8 -*-
"""
Origami Kernel — Repository Quality Gate & Standards Linter (OPCES-1.1).
Audits repository files for Zero-Leak security, professional tone of voice,
character encodings (BOM discipline), playbook schemas, and templates integrity.
Pure Python standard library.
"""

import os
import sys
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

# Ensure UTF-8 console output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

KERNEL_DIR = Path(__file__).resolve().parent.parent

# Files and directories ignored during scanning
IGNORE_DIRS = {
    ".git",
    "scratch",
    "temp",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".bsl-language-server",
    ".phoenixbsl",
}

IGNORE_FILES = {
    "LICENSE",
    "credentials.json",
}

# Binary extensions to skip
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".ico", ".gif",
    ".1cd", ".cf", ".cfe", ".epf", ".erf", ".dt",
    ".pyc", ".zip", ".tar", ".gz"
}

# Zero-Leak: Patterns indicating exposed secrets and tokens
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9_\-]{20,}", "Потенциальный API-ключ (OpenAI / Anthropic / Gemini / OmniRoute)"),
    (r"ghp_[a-zA-Z0-9]{36}", "Персональный токен GitHub (PAT)"),
    (r"-----BEGIN (?:RSA|EC|OPENSSH|PGP) PRIVATE KEY-----", "Приватный криптографический ключ"),
    (r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{30,}", "Bearer-токен авторизации в открытом виде"),
    (r"(?i)password\s*[:=]\s*['\"][^'\"{}]{8,}['\"]", "Незамаскированный пароль"),
]

# Client Neutrality: Commercial and customer-specific identifiers banned in the kernel
PROPRIETARY_PATTERNS = [
    (r"(?i)\bbinom\s+systems\b", "Упоминание коммерческого заказчика 'Binom Systems' (требуется обобщение)"),
    (r"(?i)\blsgroup\b", "Упоминание внутреннего контура 'LSGroup' (требуется плейсхолдер)"),
]

# Tone of Voice: Slang, colloquialisms, and unprofessional terms (OPCES-1.1 standard)
SLANG_PATTERNS = [
    (r"(?i)конфигуратор\s+на\s+стероидах", "Жаргонизм 'конфигуратор на стероидах' запрещен стандартом OPCES-1.1"),
    (r"(?i)\bкостыл[ьяеиюмей]*\b", "Жаргонизм 'костыль' запрещен (используйте 'временное решение' или 'компромисс')"),
    (r"(?i)\bнакостыля[тьлило]*\b", "Жаргонизм 'накостылять' запрещен"),
    (r"(?i)\bколхоз[а-я]*\b", "Разговорное выражение 'колхоз' запрещено"),
    (r"(?i)\bприкол[а-я]*\b", "Разговорное выражение 'прикол' запрещено"),
    (r"(?i)\bфиксик[а-я]*\b", "Неформальный термин 'фиксик' запрещен в нормативной документации"),
    (r"(?i)\bзапил[итьилило]+\b", "Сленговое выражение 'запилить' запрещено (используйте 'реализовать')"),
]

# Whitelisted files for meta-references, tests or forbidden terms definition
WHITELISTED_META_FILES = {
    "tools/lint_kernel.py",
    "docs/standards/origami-engineering-standard.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "AGENTS.md",
}


class LintViolation:
    def __init__(self, file_path: Path, line_no: int, category: str, message: str, sample: str = ""):
        self.file_path = file_path
        self.line_no = line_no
        self.category = category
        self.message = message
        self.sample = sample.strip()

    def __str__(self) -> str:
        rel = self.file_path.relative_to(KERNEL_DIR)
        pos = f"{rel}:{self.line_no}" if self.line_no > 0 else str(rel)
        if self.sample:
            return f"  [{self.category}] {pos} -> {self.message}\n     Фрагмент: {self.sample[:80]}"
        return f"  [{self.category}] {pos} -> {self.message}"


def should_skip(path: Path) -> bool:
    """Checks whether a path should be skipped during linting."""
    if path.suffix.lower() in BINARY_EXTS:
        return True
    if path.name in IGNORE_FILES:
        return True
    for part in path.parts:
        if part in IGNORE_DIRS:
            return True
    return False


def check_encodings(path: Path) -> List[LintViolation]:
    """Audits UTF-8 encodings and BOM requirements."""
    violations = []

    try:
        raw_bytes = path.read_bytes()
    except Exception as e:
        return [LintViolation(path, 0, "ENCODING", f"Не удалось прочитать файл: {e}")]

    # Check for double BOM
    if raw_bytes.startswith(b"\xef\xbb\xbf\xef\xbb\xbf"):
        violations.append(LintViolation(
            path, 1, "ENCODING",
            "Обнаружен двойной UTF-8 BOM (\\xef\\xbb\\xbf\\xef\\xbb\\xbf). Файл поврежден."
        ))
        return violations

    has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")

    # PowerShell scripts MUST have UTF-8 BOM for PowerShell 5.1 compatibility
    if path.suffix.lower() == ".ps1":
        if not has_bom:
            violations.append(LintViolation(
                path, 1, "ENCODING",
                "PowerShell-скрипт (.ps1) обязан иметь UTF-8 BOM для совместимости с PowerShell 5.1"
            ))
        else:
            # Check that first non-BOM characters start with <# (comment header)
            content_after_bom = raw_bytes[3:].lstrip(b"\r\n \t")
            if not content_after_bom.startswith(b"<#"):
                violations.append(LintViolation(
                    path, 1, "PS1_SYNTAX",
                    "PowerShell-скрипт должен начинаться с блока описания '<#' в первой строке."
                ))
    else:
        # Markdown, Python, JSON files MUST NOT have UTF-8 BOM
        if has_bom and path.suffix.lower() in (".py", ".json", ".md"):
            violations.append(LintViolation(
                path, 1, "ENCODING",
                f"Файл {path.suffix} не должен содержать UTF-8 BOM (стандарт: UTF-8 without BOM)"
            ))

    # Verify UTF-8 decoding
    try:
        raw_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
        violations.append(LintViolation(
            path, 0, "ENCODING",
            f"Файл содержит недопустимые байты и не может быть декодирован как UTF-8: {err}"
        ))

    return violations


def check_content(path: Path) -> List[LintViolation]:
    """Audits file content for secrets, proprietary names, and slang."""
    violations = []
    rel_str = str(path.relative_to(KERNEL_DIR)).replace("\\", "/")

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return violations

    lines = text.splitlines()

    for idx, line in enumerate(lines, start=1):
        # 1. Check secrets
        for pat, desc in SECRET_PATTERNS:
            match = re.search(pat, line)
            if match:
                matched_val = match.group(0)
                # Ignore placeholders
                if any(x in matched_val for x in ["EXAMPLE", "YOUR_", "{{"]):
                    continue
                violations.append(LintViolation(
                    path, idx, "ZERO_LEAK",
                    desc, sample=line
                ))

        # 2. Check proprietary names (unless whitelisted documentation or linter itself)
        if rel_str not in WHITELISTED_META_FILES:
            for pat, desc in PROPRIETARY_PATTERNS:
                match = re.search(pat, line)
                if match:
                    violations.append(LintViolation(
                        path, idx, "NEUTRALITY",
                        desc, sample=line
                    ))

        # 3. Check Tone of Voice / Slang (unless whitelisted documentation)
        if rel_str not in WHITELISTED_META_FILES:
            for pat, desc in SLANG_PATTERNS:
                match = re.search(pat, line)
                if match:
                    violations.append(LintViolation(
                        path, idx, "TONE_OF_VOICE",
                        desc, sample=line
                    ))

    return violations


def check_playbook_schema(path: Path) -> List[LintViolation]:
    """Validates structure and frontmatter of architectural playbooks."""
    violations = []
    if path.name.lower() == "readme.md":
        return violations

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return violations

    # Check YAML frontmatter presence
    if not text.startswith("---"):
        violations.append(LintViolation(
            path, 1, "PLAYBOOK_SCHEMA",
            "Плейбук обязан начинаться с YAML-frontmatter ('---')"
        ))
        return violations

    parts = text.split("---", 2)
    if len(parts) < 3:
        violations.append(LintViolation(
            path, 1, "PLAYBOOK_SCHEMA",
            "Некорректная структура YAML-frontmatter (не найден закрывающий разделитель '---')"
        ))
        return violations

    frontmatter = parts[1]
    required_fields = ["id", "title", "type", "category", "status", "version", "tags"]
    for field in required_fields:
        if not re.search(rf"(?m)^{field}\s*:", frontmatter):
            violations.append(LintViolation(
                path, 1, "PLAYBOOK_SCHEMA",
                f"В YAML-frontmatter плейбука отсутствует обязательное поле '{field}'"
            ))

    body = parts[2]
    # Check that playbook contains at least 3 structured H2 sections
    h2_sections = re.findall(r"(?m)^##\s+(\d+)\.\s+(.*)$", body)
    if len(h2_sections) < 3:
        violations.append(LintViolation(
            path, 1, "PLAYBOOK_SCHEMA",
            f"Плейбук должен содержать не менее 3 структурированных разделов уровня '## X. ...', обнаружено: {len(h2_sections)}"
        ))

    return violations


def check_templates_integrity() -> List[LintViolation]:
    """Validates critical downstream templates in templates/ directory."""
    violations = []
    agents_template = KERNEL_DIR / "templates" / "AGENTS.template.md"
    if not agents_template.exists():
        violations.append(LintViolation(
            agents_template, 0, "TEMPLATES",
            "Отсутствует критический шаблон 'templates/AGENTS.template.md'"
        ))
    else:
        text = agents_template.read_text(encoding="utf-8", errors="replace")
        if "<!-- origami-kernel-rules -->" not in text or "<!-- /origami-kernel-rules -->" not in text:
            violations.append(LintViolation(
                agents_template, 1, "TEMPLATES",
                "Шаблон AGENTS.template.md обязан содержать маркеры <!-- origami-kernel-rules -->"
            ))

    # Verify workspace isolation
    ws_file = KERNEL_DIR / "origami.workspace.json"
    if ws_file.exists():
        # Check if tracked by git
        import subprocess
        try:
            res = subprocess.run(
                ["git", "ls-files", "origami.workspace.json"],
                cwd=str(KERNEL_DIR),
                capture_output=True,
                text=True
            )
            if res.stdout.strip():
                violations.append(LintViolation(
                    ws_file, 0, "ZERO_LEAK",
                    "Файл origami.workspace.json отслеживается Git! Он ОБЯЗАН быть в .gitignore."
                ))
        except Exception:
            pass

    return violations


def main() -> int:
    print("\n=== Origami Kernel: Аудит стандартов и качества (OPCES-1.1) ===")
    print(f"Каталог ядра: {KERNEL_DIR}\n")

    all_violations: List[LintViolation] = []

    # 1. Audit all files
    for root, dirs, files in os.walk(KERNEL_DIR):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            path = Path(root) / file
            if should_skip(path):
                continue

            # Encoding & BOM checks
            all_violations.extend(check_encodings(path))

            # Content checks (secrets, tone of voice, neutrality)
            all_violations.extend(check_content(path))

            # Playbook schema check
            if "knowledge" in path.parts and "playbooks" in path.parts and path.suffix.lower() == ".md":
                all_violations.extend(check_playbook_schema(path))

    # 2. Audit template integrity
    all_violations.extend(check_templates_integrity())

    # Summary
    if not all_violations:
        print("[OK] Статический аудит завершен успешно. Нарушений стандартов OPCES-1.1 не обнаружено!\n")
        return 0

    print(f"[FAIL] Обнаружено нарушений: {len(all_violations)}\n")
    categories = {}
    for v in all_violations:
        categories[v.category] = categories.get(v.category, 0) + 1
        print(v)

    print("\nСводка по категориям:")
    for cat, count in sorted(categories.items()):
        print(f"  - {cat}: {count}")

    print("\nДля устранения нарушений ознакомьтесь с docs/standards/origami-engineering-standard.md\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
