# -*- coding: utf-8 -*-
"""
Origami Kernel — Configuration Access Layer.
Universal configuration reader for origami.config.json.
Pure Python standard library.
"""

import os
import sys
import json
from pathlib import Path
from typing import Any, Optional


def find_project_root(start_dir: Optional[Path] = None) -> Path:
    """Finds directory containing origami.config.json by walking up."""
    cur = start_dir or Path(__file__).resolve().parent
    for _ in range(6):
        if (cur / "origami.config.json").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path.cwd()


class OrigamiConfig:
    """Unified configuration accessor for Origami Kernel."""

    def __init__(self, config_path: Optional[Path] = None):
        self.root_dir = find_project_root(config_path.parent if config_path else None)
        if config_path:
            self.config_file = config_path
        else:
            self.config_file = self.root_dir / "origami.config.json"
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Loads configuration from disk."""
        if not self.config_file.exists():
            # Return safe default structure if file not yet created
            self._data = {
                "origami": {"version": "1.0.0", "name": "Origami Kernel"},
                "project": {"prefix": "ext_", "extensionName": "Customization"},
                "omniroute": {"endpoint": "http://localhost:20128/v1"}
            }
            return
        with open(self.config_file, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Retrieves a setting using dot-notation.
        Example: cfg.get("infobase.path") -> "D:\\1C base\\my_project"
        """
        parts = key_path.split(".")
        current: Any = self._data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def get_db_password(self) -> str:
        """Resolves database password from environment variable."""
        env_var = self.get("infobase.passwordEnv", "ORIGAMI_DB_PASSWORD")
        return os.environ.get(env_var, "")

    def get_llm_endpoint(self) -> str:
        """Resolves OpenAI-compatible LLM endpoint (OmniRoute, LM Studio, Ollama, OpenRouter, etc.)."""
        # 1. Config 'llm.endpoint'
        val = self.get("llm.endpoint")
        if val and not str(val).startswith("{{"):
            return str(val)
        # 2. Config 'omniroute.endpoint'
        val = self.get("omniroute.endpoint")
        if val and not str(val).startswith("{{"):
            return str(val)
        # 3. Environment variables
        for env_name in ("OPENAI_BASE_URL", "LLM_ENDPOINT", "OMNIROUTE_ENDPOINT"):
            if env_name in os.environ and os.environ[env_name].strip():
                return os.environ[env_name].strip()
        # Default fallback to standard local proxy port
        return "http://localhost:20128/v1"

    def get_llm_key(self) -> str:
        """Resolves API key for LLM provider across environment variables and config."""
        # 1. Custom env var defined in config
        custom_env = self.get("llm.apiKeyEnv") or self.get("omniroute.apiKeyEnv")
        if custom_env and custom_env in os.environ and os.environ[custom_env].strip():
            return os.environ[custom_env].strip()
        # 2. Explicit key in local config (if populated)
        cfg_key = self.get("llm.apiKey") or self.get("omniroute.subagentKey")
        if cfg_key and not str(cfg_key).startswith("{{"):
            return str(cfg_key).strip()
        # 3. Standard environment variables
        for env_name in ("ORIGAMI_LLM_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "OMNIROUTE_API_KEY"):
            if env_name in os.environ and os.environ[env_name].strip():
                return os.environ[env_name].strip()
        return ""

    def get_omniroute_key(self) -> str:
        """Backward-compatible alias for get_llm_key()."""
        return self.get_llm_key()

    def get_admin_key(self) -> str:
        """Resolves admin key for Team Lead diagnostics and admin API only."""
        env_var = self.get("omniroute.adminKeyEnv", "OMNIROUTE_ADMIN_KEY")
        if env_var and env_var in os.environ:
            return os.environ[env_var]
        return self.get("omniroute.adminKey", "")

    def to_dict(self) -> dict[str, Any]:
        """Returns deep copy of raw config data."""
        return json.loads(json.dumps(self._data))


# Singleton instance
_instance: Optional[OrigamiConfig] = None


def get_config(config_path: Optional[Path] = None) -> OrigamiConfig:
    global _instance
    if _instance is None or config_path is not None:
        _instance = OrigamiConfig(config_path)
    return _instance


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python origami_config.py [show | get <key_path>]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    try:
        cfg = get_config()
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    if cmd == "show":
        print(json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2))
    elif cmd == "key":
        print(cfg.get_omniroute_key())
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Error: key path required. Example: get infobase.path", file=sys.stderr)
            sys.exit(1)
        key = sys.argv[2]
        val = cfg.get(key)
        if val is None:
            print("", end="")
        elif isinstance(val, (dict, list)):
            print(json.dumps(val, ensure_ascii=False, indent=2))
        else:
            print(str(val))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
