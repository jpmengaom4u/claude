"""Descoberta da lista de nichos a partir dos posts (LLM generativo)."""
from __future__ import annotations

import json
import re

from .biblioteca import OUTROS, Biblioteca
from .ia import ClienteIA, ErroIA
from .modelos import Nicho, Post

_INSTRUCOES = (
    "Você organiza posts salvos do Instagram de uma pessoa. Abaixo, um resumo por post "
    "(autor, início da legenda e da transcrição). Proponha de 5 a 15 nichos (assuntos) que "
    "agrupem bem esses posts: nomes curtos em português e uma descrição de uma linha que "
    "deixe claro o que entra em cada um. Não inclua 'Outros'. "
    'Responda somente com JSON: [{"nome": "...", "descricao": "..."}].'
)

_INSTRUCOES_NOVOS = (
    " Já existem estes nichos, que não devem ser repetidos: {existentes}. "
    "Proponha apenas nichos novos para os posts abaixo (pode ser uma lista curta)."
)


def resumo(post: Post, transcricao: str) -> str:
    return f"@{post.autor}: {post.legenda[:300]} | {transcricao[:300]}"


def _extrair_lista(texto: str) -> list[Nicho]:
    cerca = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if cerca:
        texto = cerca.group(1)
    inicio, fim = texto.find("["), texto.rfind("]")
    try:
        dados = json.loads(texto[inicio : fim + 1]) if inicio != -1 else None
        nichos = [Nicho(str(d["nome"]).strip(), str(d.get("descricao", "")).strip()) for d in dados]
    except (json.JSONDecodeError, TypeError, KeyError):
        nichos = []
    nichos = [n for n in nichos if n.nome]
    if not nichos:
        raise ErroIA("Resposta da IA sem lista de nichos válida")
    return nichos


def propor_nichos(
    bib: Biblioteca,
    ia: ClienteIA,
    modelo: str,
    posts: list[Post] | None = None,
    existentes: list[Nicho] | None = None,
) -> list[Nicho]:
    posts = bib.listar() if posts is None else posts
    instrucoes = _INSTRUCOES
    if existentes:
        instrucoes += _INSTRUCOES_NOVOS.format(existentes=", ".join(n.nome for n in existentes))
    resumos = "\n".join(resumo(p, bib.transcricao(p.shortcode)) for p in posts)
    resposta = ia.chat(
        modelo,
        [{"role": "system", "content": instrucoes}, {"role": "user", "content": resumos}],
    )
    nomes_existentes = {n.nome.lower() for n in existentes or []}
    nichos = [
        n for n in _extrair_lista(resposta)
        if n.nome.lower() != OUTROS.lower() and n.nome.lower() not in nomes_existentes
    ]
    if not existentes:
        nichos.append(Nicho(OUTROS, "Posts que não se encaixam nos outros nichos."))
    return nichos


def revisar_nichos(bib: Biblioteca, ia: ClienteIA, modelo: str) -> list[Nicho]:
    return propor_nichos(bib, ia, modelo, posts=bib.listar(nicho=OUTROS), existentes=bib.nichos())
