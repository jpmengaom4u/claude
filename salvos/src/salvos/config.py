"""Configuração: caminhos, modelos, limites e a chave da OpenRouter."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Config:
    biblioteca: Path
    pasta_app: Path
    modelo_nichos: str = "anthropic/claude-sonnet-5.5"
    modelo_classificacao: str = "typesafe/jev-1.13"
    modelo_whisper: str = "small"
    limite: int = 150
    pausa_min: float = 4
    pausa_max: float = 10
    parada_conhecidos: int = 5
    porta: int = 8000


def _pasta_app() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "salvos"
    return Path.home() / ".salvos"


def carregar_config() -> Config:
    raiz = os.environ.get("SALVOS_BIBLIOTECA")
    biblioteca = Path(raiz) if raiz else Path.home() / "Salvos"
    cfg = Config(biblioteca=biblioteca, pasta_app=_pasta_app())
    toml = biblioteca / "salvos.toml"
    if toml.exists():
        dados = tomllib.loads(toml.read_text(encoding="utf-8"))
        permitidos = {f.name for f in fields(Config)} - {"biblioteca", "pasta_app"}
        for chave, valor in dados.items():
            if chave in permitidos:
                setattr(cfg, chave, valor)
    return cfg


def chave_openrouter(cfg: Config) -> str | None:
    chave = os.environ.get("OPENROUTER_API_KEY")
    if chave:
        return chave
    env = cfg.pasta_app / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            nome, _, valor = linha.strip().partition("=")
            if nome.strip() == "OPENROUTER_API_KEY" and valor.strip():
                return valor.strip().strip('"').strip("'")
    return None
