import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = str(_PROJECT_ROOT / ".env")

_PROVIDER_KEYS = {
    "llm":  ("LLM_PROVIDER",      "LANGCHAIN_MODEL",      "CLAUDE_MODEL", "LANGCHAIN_BACKEND"),
    "eval": ("LLM_PROVIDER_EVAL", "LANGCHAIN_MODEL_EVAL", "CLAUDE_MODEL", "LANGCHAIN_BACKEND_EVAL"),
}

_CLAUDE_DEFAULT    = "claude-haiku-4-5-20251001"
_OLLAMA_DEFAULT    = "llama3.1:8b"
_DEEPSEEK_DEFAULT  = "deepseek-v4-flash"

_LC_BACKEND_DEFAULTS = {
    "ollama":   _OLLAMA_DEFAULT,
    "deepseek": _DEEPSEEK_DEFAULT,
}

_PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek":  "DEEPSEEK_API_KEY",
}


def _mask_key(value: str) -> str:
    if not value:
        return "(missing)"
    if len(value) <= 8:
        return "set"
    return f"{value[:6]}...{value[-4:]}"


def _read_env_value(key: str) -> str | None:
    from dotenv import dotenv_values
    return dotenv_values(ENV_FILE).get(key)


def run_provider_show():
    from dotenv import dotenv_values
    cfg = dotenv_values(ENV_FILE)

    def _fmt(provider_key: str, lc_model_key: str, _: str, lc_backend_key: str) -> str:
        backend = cfg.get(provider_key, "(not set)").lower()
        if backend == "langchain":
            model = cfg.get(lc_model_key, "(not set)")
            lc_backend = (cfg.get(lc_backend_key) or cfg.get("LANGCHAIN_BACKEND") or "ollama").lower()
            return f"langchain  backend={lc_backend}  model={model}"
        if backend == "claude":
            model = cfg.get("CLAUDE_MODEL", _CLAUDE_DEFAULT)
            return f"claude     model={model}"
        return backend

    print(f"  llm  (form Q&A):       {_fmt(*_PROVIDER_KEYS['llm'])}")
    print(f"  eval (job evaluation): {_fmt(*_PROVIDER_KEYS['eval'])}")
    print()
    print("  API keys:")
    for prov, env_var in _PROVIDER_KEY_ENV.items():
        print(f"    {prov:10s} {env_var:20s} {_mask_key(cfg.get(env_var, ''))}")


def run_provider_set(target: str, backend: str, model: str | None, lc_backend: str | None = None):
    from dotenv import set_key
    provider_key, lc_model_key, _, lc_backend_key = _PROVIDER_KEYS[target]

    set_key(ENV_FILE, provider_key, backend)

    if backend == "langchain":
        b = (lc_backend or "ollama").lower()
        m = model or _LC_BACKEND_DEFAULTS.get(b, _OLLAMA_DEFAULT)
        set_key(ENV_FILE, lc_model_key, m)
        set_key(ENV_FILE, lc_backend_key, b)
        print(f"[provider] {target} -> langchain  backend={b}  model={m}")
        if b == "deepseek" and not (os.getenv("DEEPSEEK_API_KEY") or _read_env_value("DEEPSEEK_API_KEY")):
            print("  [warn] DEEPSEEK_API_KEY not set. Run: provider key set deepseek <key>")
    else:
        if model:
            set_key(ENV_FILE, "CLAUDE_MODEL", model)
        m = model or os.getenv("CLAUDE_MODEL") or _CLAUDE_DEFAULT
        print(f"[provider] {target} -> claude     model={m}")


def run_provider_key_set(provider: str, value: str):
    from dotenv import set_key
    if provider not in _PROVIDER_KEY_ENV:
        raise ValueError(f"Unknown provider '{provider}'. Available: {', '.join(_PROVIDER_KEY_ENV)}")
    env_var = _PROVIDER_KEY_ENV[provider]
    set_key(ENV_FILE, env_var, value)
    print(f"[provider] {env_var} -> {_mask_key(value)}")


def run_provider_key_show():
    from dotenv import dotenv_values
    cfg = dotenv_values(ENV_FILE)
    for prov, env_var in _PROVIDER_KEY_ENV.items():
        print(f"  {prov:10s} {env_var:20s} {_mask_key(cfg.get(env_var, ''))}")
