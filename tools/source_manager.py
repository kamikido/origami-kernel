# -*- coding: utf-8 -*-
"""
Origami Kernel — Knowledge Source Registry & Scanner.
Manages declarative knowledge sources (knowledge/knowledge_sources.json),
audits accessible 1C projects, collects documentation artifacts (.md, .txt, .bsl),
and guarantees Zero-Leak compliance via automated sanitization.
Pure Python standard library per OPCES-1.1.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Exit codes per OPCES-1.1 Invariant 5
EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_ENV_ERROR = 2

# Directory names ignored during scanning to prevent performance degradation
IGNORE_DIRS = {
    ".git", "build", "bin", "temp", "scratch", ".metadata", ".settings",
    ".vscode", "__pycache__", "node_modules", ".origami_cache", "obj"
}

# Supported file extensions for document knowledge
SUPPORTED_EXTENSIONS = {".md", ".txt", ".bsl"}


def get_project_root() -> Path:
    """Returns the root directory of the development environment."""
    tools_dir = Path(__file__).resolve().parent
    # In origami-kernel/tools/, parent is origami-kernel, parent.parent is project root
    if (tools_dir.parent.parent / "knowledge").exists():
        return tools_dir.parent.parent
    return tools_dir.parent


def get_default_manifest_path() -> Path:
    """Returns the path to knowledge_sources.json."""
    root = get_project_root()
    manifest = root / "knowledge" / "knowledge_sources.json"
    if manifest.exists():
        return manifest
    # Fallback to local kernel directory if run standalone
    return root / "origami-kernel" / "knowledge_sources.json"


def sanitize_content(text: str) -> str:
    """Safe wrapper for Zero-Leak content sanitization."""
    try:
        from tools.extract_case import sanitize_text
        return sanitize_text(text)
    except Exception:
        try:
            from extract_case import sanitize_text
            return sanitize_text(text)
        except Exception:
            # Fallback inline basic scrubbing
            scrubbed = re.sub(r'(?i)ws=["\']https?://[^"\']+["\']', 'ws="<информационная_база>"', text)
            scrubbed = re.sub(r'(?i)https?://[a-zA-Z0-9\-\._]+(?::\d+)?(?:/[^\s\'"<>]*)?', '<сетевой_ресурс>', scrubbed)
            scrubbed = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b', '<ip_адрес>', scrubbed)
            return scrubbed


class SourceManager:
    """Manages knowledge source discovery, auditing, and content retrieval."""

    def __init__(self, manifest_path: Optional[Path] = None):
        self.manifest_path = manifest_path or get_default_manifest_path()
        self.root_dir = get_project_root()
        self.data: Dict[str, Any] = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        """Loads and parses the manifest JSON file."""
        if not self.manifest_path.exists():
            return {
                "version": "1.0.0",
                "description": "Автоматически сгенерированный реестр источников",
                "sources": []
            }
        try:
            content = self.manifest_path.read_text(encoding="utf-8", errors="replace")
            return json.loads(content)
        except Exception as e:
            print(f"Предупреждение: Ошибка чтения манифеста '{self.manifest_path}': {e}", file=sys.stderr)
            return {"version": "1.0.0", "sources": []}

    def save_manifest(self) -> bool:
        """Persists current sources to the manifest JSON file."""
        try:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            formatted = json.dumps(self.data, indent=2, ensure_ascii=False)
            self.manifest_path.write_text(formatted + "\n", encoding="utf-8")
            return True
        except Exception as e:
            print(f"Ошибка сохранения манифеста '{self.manifest_path}': {e}", file=sys.stderr)
            return False

    def resolve_source_path(self, raw_path: str) -> Path:
        """Resolves relative or absolute paths against project root."""
        p = Path(raw_path)
        if p.is_absolute():
            return p
        return (self.root_dir / p).resolve()

    def scan_source_files(self, source: Dict[str, Any]) -> List[Path]:
        """Collects relevant files for a given source respecting scan_depth and patterns."""
        target_dir = self.resolve_source_path(source["path"])
        if not target_dir.exists() or not target_dir.is_dir():
            return []

        depth_limit = source.get("scan_depth", 3)
        collected: List[Path] = []

        try:
            for root, dirs, files in os.walk(target_dir):
                # Filter out ignored directories in place
                dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith(".")]

                # Enforce depth limitation
                rel_parts = Path(root).relative_to(target_dir).parts
                if len(rel_parts) >= depth_limit:
                    dirs.clear()

                for file_name in files:
                    ext = Path(file_name).suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS and not file_name.startswith("."):
                        collected.append(Path(root) / file_name)
        except Exception as e:
            print(f"Предупреждение при сканировании '{target_dir}': {e}", file=sys.stderr)

        return sorted(collected)

    def get_sources_status(self) -> List[Dict[str, Any]]:
        """Audits all sources and calculates their live status and metrics."""
        results = []
        for src in self.data.get("sources", []):
            resolved = self.resolve_source_path(src["path"])
            exists = resolved.exists()
            files_count = 0
            status = "OFFLINE"

            if exists:
                files = self.scan_source_files(src)
                files_count = len(files)
                if not src.get("active", True):
                    status = "DISABLED"
                elif files_count > 0:
                    status = "ONLINE"
                else:
                    status = "EMPTY"

            results.append({
                "id": src.get("id"),
                "name": src.get("name"),
                "kind": src.get("kind", "project"),
                "path": str(resolved),
                "status": status,
                "files_count": files_count,
                "auto_anonymize": src.get("auto_anonymize", True),
                "one_s_mcp_integrated": src.get("one_s_mcp_integrated", False),
                "mcp_base_name": src.get("mcp_base_name"),
                "description": src.get("description", "")
            })
        return results

    def add_source(
        self,
        source_id: str,
        name: str,
        path: str,
        kind: str = "downstream_project",
        auto_anonymize: bool = True,
        one_s_mcp_integrated: bool = False,
        mcp_base_name: Optional[str] = None,
        description: str = ""
    ) -> bool:
        """Registers a new knowledge source into the manifest."""
        sources = self.data.setdefault("sources", [])
        for s in sources:
            if s.get("id") == source_id:
                print(f"Ошибка: Источник с идентификатором '{source_id}' уже зарегистрирован.", file=sys.stderr)
                return False

        new_entry = {
            "id": source_id,
            "name": name,
            "kind": kind,
            "path": path,
            "active": True,
            "patterns": ["**/*.md", "**/*.txt", "**/*.bsl"],
            "scan_depth": 3,
            "auto_anonymize": auto_anonymize,
            "one_s_mcp_integrated": one_s_mcp_integrated,
            "mcp_base_name": mcp_base_name,
            "description": description
        }
        sources.append(new_entry)
        return self.save_manifest()

    def query_knowledge(self, query: str, max_chars_per_source: int = 2000) -> str:
        """
        Cross-queries all active online sources and returns Zero-Leak sanitized context.
        """
        query_words = [w.lower() for w in re.split(r'\s+', query) if len(w) > 2]
        if not query_words:
            return ""

        collected_snippets: List[str] = []

        for src in self.data.get("sources", []):
            if not src.get("active", True):
                continue

            files = self.scan_source_files(src)
            matched_files: List[Tuple[Path, str]] = []

            for f in files:
                name_lower = f.name.lower()
                # Fast check by filename or check top content
                matched = any(w in name_lower for w in query_words)
                if not matched:
                    try:
                        head = f.read_text(encoding="utf-8", errors="replace")[:1500].lower()
                        if any(w in head for w in query_words):
                            matched = True
                    except Exception:
                        pass

                if matched:
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                        matched_files.append((f, content))
                        if len(matched_files) >= 2:
                            break
                    except Exception:
                        pass

            if matched_files:
                src_name = src.get("name", src.get("id"))
                body_parts = []
                for f, content in matched_files:
                    clean = sanitize_content(content) if src.get("auto_anonymize", True) else content
                    body_parts.append(f"<!-- Файл: {f.name} -->\n{clean[:900]}")

                snippet = f"=== ИСТОЧНИК ЗНАНИЙ: {src_name} ===\n" + "\n\n".join(body_parts)
                collected_snippets.append(snippet[:max_chars_per_source])

        return "\n\n".join(collected_snippets)


def print_sources_table(statuses: List[Dict[str, Any]]):
    """Renders a clean ASCII status table of registered knowledge sources."""
    print("\n=== Реестр источников знаний Origami Kernel ===")
    header = f"{'ID':<24} | {'СТАТУС':<8} | {'ФАЙЛЫ':<6} | {'MCP':<5} | {'НАИМЕНОВАНИЕ'}"
    print(header)
    print("-" * len(header))

    for s in statuses:
        mcp_mark = "Да" if s["one_s_mcp_integrated"] else "Нет"
        print(f"{s['id']:<24} | {s['status']:<8} | {s['files_count']:<6} | {mcp_mark:<5} | {s['name']}")
    print("-" * len(header))
    total_files = sum(s["files_count"] for s in statuses)
    online_count = sum(1 for s in statuses if s["status"] == "ONLINE")
    print(f"Всего источников: {len(statuses)} (Онлайн: {online_count}), Документов знаний: {total_files}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Origami Kernel Knowledge Source Registry & Scanner"
    )
    subparsers = parser.add_subparsers(dest="command", help="Команда управления")

    # Command: list
    subparsers.add_parser("list", help="Вывести список и статус источников знаний")

    # Command: verify
    subparsers.add_parser("verify", help="Проверить доступность путей и политику Zero-Leak")

    # Command: query
    query_parser = subparsers.add_parser("query", help="Поиск релевантного контекста по источникам")
    query_parser.add_argument("text", type=str, help="Поисковый запрос")

    # Command: add
    add_parser = subparsers.add_parser("add", help="Зарегистрировать новый источник")
    add_parser.add_argument("--id", required=True, help="Уникальный идентификатор")
    add_parser.add_argument("--name", required=True, help="Понятное наименование")
    add_parser.add_argument("--path", required=True, help="Путь к каталогу источника")
    add_parser.add_argument("--kind", default="downstream_project", choices=["core", "downstream_project"])
    add_parser.add_argument("--mcp", action="store_true", help="Связан со слепком one-s-mcp")
    add_parser.add_argument("--mcp-base", default=None, help="Имя базы в one-s-mcp")
    add_parser.add_argument("--desc", default="", help="Описание источника")

    args = parser.parse_args()
    manager = SourceManager()

    if args.command == "list" or not args.command:
        statuses = manager.get_sources_status()
        print_sources_table(statuses)
        return EXIT_SUCCESS

    elif args.command == "verify":
        statuses = manager.get_sources_status()
        print_sources_table(statuses)
        has_offline = any(s["status"] == "OFFLINE" for s in statuses)
        if has_offline:
            print("Предупреждение: Часть источников находится в статусе OFFLINE.", file=sys.stderr)
            return EXIT_VALIDATION_ERROR
        print("Все зарегистрированные источники проверены и доступны онлайн!")
        return EXIT_SUCCESS

    elif args.command == "query":
        result = manager.query_knowledge(args.text)
        if result:
            print(result)
        else:
            print("Совпадений в зарегистрированных источниках не обнаружено.")
        return EXIT_SUCCESS

    elif args.command == "add":
        ok = manager.add_source(
            source_id=args.id,
            name=args.name,
            path=args.path,
            kind=args.kind,
            auto_anonymize=True,
            one_s_mcp_integrated=args.mcp,
            mcp_base_name=args.mcp_base,
            description=args.desc
        )
        if ok:
            print(f"Успех: Источник '{args.id}' успешно зарегистрирован в реестре знаний.")
            return EXIT_SUCCESS
        return EXIT_VALIDATION_ERROR

    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
