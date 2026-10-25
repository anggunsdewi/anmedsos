"""Registri provider. Pilih lewat `provider.name` di config.yaml."""

from __future__ import annotations

import importlib

from crawler.providers.base import NORMALIZED_FIELDS, Page, ProviderError, QuerySpec, SearchProvider

BUILTIN = {
    "x_api_v2": "crawler.providers.x_api_v2:XApiV2Provider",
    "mock": "crawler.providers.mock:MockProvider",
}


def load_provider(name: str, options: dict | None = None) -> SearchProvider:
    """`name` berupa nama bawaan (x_api_v2, mock) atau path 'paket.modul:Kelas'."""
    target = BUILTIN.get(name, name)
    if ":" not in target:
        raise ValueError(
            f"Provider '{name}' tidak dikenal. Pakai salah satu dari {sorted(BUILTIN)} "
            "atau path 'paket.modul:NamaKelas'."
        )
    module_name, cls_name = target.split(":", 1)
    cls = getattr(importlib.import_module(module_name), cls_name)
    if not issubclass(cls, SearchProvider):
        raise TypeError(f"{target} bukan turunan SearchProvider")
    return cls(options or {})


__all__ = ["NORMALIZED_FIELDS", "Page", "ProviderError", "QuerySpec", "SearchProvider", "load_provider"]
