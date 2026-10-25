"""Modelos de dados: Post e Nicho."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Literal

ETAPAS = ("baixado", "transcrito", "classificado")


@dataclass
class Post:
    shortcode: str
    url: str
    autor: str
    data: str
    legenda: str
    hashtags: list[str]
    tipo: Literal["imagem", "carrossel", "video"]
    arquivos: list[str]
    etapas: dict[str, bool] = field(default_factory=lambda: {e: False for e in ETAPAS})
    nicho: str | None = None
    nicho_manual: bool = False
    revisar: bool = False
    confianca: float | None = None
    indisponivel: bool = False

    def para_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict) -> "Post":
        nomes = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in nomes})


@dataclass
class Nicho:
    nome: str
    descricao: str
