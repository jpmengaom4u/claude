"""Exportação do conteúdo de um nicho em Markdown e em .zip."""
from __future__ import annotations

import re
import zipfile
from datetime import date
from typing import BinaryIO

from .biblioteca import Biblioteca

_RESERVADOS = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def nome_arquivo(nicho: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", nicho).rstrip(" .").strip()
    if not nome:
        return "nicho"
    if nome.upper() in _RESERVADOS:
        return "_" + nome
    return nome


def exportar_md(bib: Biblioteca, nicho: str) -> str:
    posts = bib.listar(nicho=nicho)
    blocos = []
    for p in posts:
        partes = [f"## @{p.autor} — {p.data[:10]}", p.url, "### Legenda", p.legenda or "_(sem legenda)_"]
        transcricao = bib.transcricao(p.shortcode)
        if transcricao:
            partes += ["### Transcrição", transcricao]
        blocos.append("\n\n".join(partes))
    cabecalho = f"# {nicho}\n\nExportado em {date.today().isoformat()} · {len(posts)} posts\n\n"
    return cabecalho + "\n\n---\n\n".join(blocos) + "\n"


def exportar_zip(bib: Biblioteca, nicho: str, destino: BinaryIO) -> None:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{nome_arquivo(nicho)}.md", exportar_md(bib, nicho))
        for p in bib.listar(nicho=nicho):
            pasta = bib.pasta(p.shortcode)
            for arq in sorted(pasta.iterdir()):
                if arq.is_file():
                    z.write(arq, f"posts/{p.shortcode}/{arq.name}")
