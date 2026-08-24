"""Model provider listing for the desktop launcher.

Provider configuration lives in `$DSH_HOME/settings.yaml` under
`llm-pi-ai.providers` (configured through the dsh Web UI's Settings -> Models
page; API keys are write-only there and stored in
`$DSH_HOME/.credentials.yaml`). This module reads the configuration without
exposing any secret values — it only reports which providers exist, their
endpoint info, and whether their credential reference resolves.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("providers")


def dsh_home() -> str:
    return os.environ.get("DSH_HOME") or os.path.join(
        os.path.expanduser("~"), ".dsh")


def list_providers(app_key_set: bool = False) -> dict:
    """Read installed model providers from settings.yaml (no secrets)."""
    home = dsh_home()
    providers: list[dict] = []
    settings_path = os.path.join(home, "settings.yaml")
    if os.path.isfile(settings_path):
        try:
            import yaml
            with open(settings_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as exc:  # broken yaml should not break the page
            log.warning("settings.yaml parse failed: %s", exc)
            data = {}
        for plugin, plugin_cfg in data.items():
            if not isinstance(plugin_cfg, dict):
                continue
            provider_cfg = plugin_cfg.get("providers")
            if not isinstance(provider_cfg, dict):
                continue
            for pid, cfg in provider_cfg.items():
                if not isinstance(cfg, dict):
                    continue
                models = cfg.get("models") or []
                env_ref = cfg.get("apiKeyEnv") or ""
                env_set = bool(env_ref and os.environ.get(env_ref))
                providers.append({
                    "id": pid,
                    "baseURL": cfg.get("baseURL") or "",
                    "api": cfg.get("api") or "",
                    "modelCount": len(models) if isinstance(models, list) else 0,
                    "models": [m.get("id", "") for m in models if isinstance(m, dict)],
                    "envRef": env_ref,
                    "credentialSet": env_set,
                })
    return {
        "providers": providers,
        "home": home,
        "appKeySet": app_key_set,
    }
