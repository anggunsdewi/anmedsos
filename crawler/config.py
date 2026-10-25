"""Membaca config.yaml dan .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass
class Config:
    raw: dict[str, Any]
    base_dir: Path

    @property
    def project(self) -> dict:
        return self.raw["project"]

    @property
    def provider(self) -> dict:
        return self.raw["provider"]

    @property
    def query(self) -> dict:
        return self.raw["query"]

    @property
    def collection(self) -> dict:
        return self.raw["collection"]

    @property
    def processing(self) -> dict:
        return self.raw["processing"]

    def path(self, key: str) -> Path:
        p = Path(self.project[key])
        return p if p.is_absolute() else self.base_dir / p

    @property
    def data_dir(self) -> Path:
        return self.path("data_dir")

    @property
    def log_dir(self) -> Path:
        return self.path("log_dir")

    @property
    def checkpoint_file(self) -> Path:
        return self.path("checkpoint_file")

    @property
    def start_date(self) -> date:
        return _as_date(self.collection["start_date"])

    @property
    def end_date(self) -> date:
        return _as_date(self.collection["end_date"])


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


REQUIRED = {
    "project": ["data_dir", "log_dir", "checkpoint_file", "timezone"],
    "provider": ["name"],
    "query": ["lang", "groups"],
    "collection": ["start_date", "end_date", "window_days", "cap_per_window"],
    "processing": ["filters", "min_words"],
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_with_extends(path: Path, depth: int = 0) -> dict:
    """`extends: config.yaml` di bagian atas berkas = pakai berkas itu sebagai dasar, lalu timpa."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    parent = raw.pop("extends", None)
    if parent and depth < 5:
        raw = _deep_merge(_read_with_extends((path.parent / parent).resolve(), depth + 1), raw)
    return raw


def load_config(path: str | Path, env_file: str | Path | None = None) -> Config:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"Berkas konfigurasi tidak ditemukan: {path}")
    # .env dicari di folder yang sama dengan config.yaml, kecuali ditentukan lain.
    load_dotenv(env_file or path.parent / ".env")
    raw = _read_with_extends(path)

    for section, keys in REQUIRED.items():
        if section not in raw:
            raise ConfigError(f"Bagian '{section}' tidak ada di {path.name}")
        for k in keys:
            if k not in raw[section]:
                raise ConfigError(f"Kunci '{section}.{k}' tidak ada di {path.name}")

    groups = raw["query"]["groups"]
    if not isinstance(groups, dict) or not groups:
        raise ConfigError("query.groups harus berisi minimal satu grup kata kunci")
    for name, kws in groups.items():
        if not kws:
            raise ConfigError(f"Grup '{name}' tidak punya kata kunci")

    cfg = Config(raw=raw, base_dir=path.parent)
    if cfg.end_date < cfg.start_date:
        raise ConfigError("collection.end_date lebih awal dari start_date")
    return cfg


def get_secret(env_name: str, required: bool = True) -> str | None:
    value = os.environ.get(env_name)
    if required and not value:
        raise ConfigError(
            f"Variabel lingkungan {env_name} kosong. Isi di berkas .env (lihat .env.example)."
        )
    return value
