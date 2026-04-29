from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Provider:
    name: str
    default_model: str | None
    wrapper_path: str


class Store:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or Path.home() / ".config" / "claude-env"
        self.path = self.config_dir / "providers.json"

    def get_provider(self, name: str) -> Provider | None:
        providers = self._read()["providers"]
        item = providers.get(name)
        if item is None:
            return None
        return Provider(
            name=name,
            default_model=item.get("default_model"),
            wrapper_path=item["wrapper_path"],
        )

    def list_providers(self) -> list[Provider]:
        providers = self._read()["providers"]
        return [
            Provider(
                name=name,
                default_model=item.get("default_model"),
                wrapper_path=item["wrapper_path"],
            )
            for name, item in sorted(providers.items())
        ]

    def save_provider(self, provider: Provider) -> None:
        data = self._read()
        data["providers"][provider.name] = {
            "default_model": provider.default_model,
            "wrapper_path": provider.wrapper_path,
            "managed_by": "claude-env",
            "version": 2,
        }
        self._write(data)

    def remove_provider(self, name: str) -> None:
        data = self._read()
        data["providers"].pop(name, None)
        self._write(data)

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "providers": {}}
        with self.path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        data.setdefault("version", 1)
        data.setdefault("providers", {})
        return data

    def _write(self, data: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(self.path)
        os.chmod(self.path, 0o600)
