"""Classificação de cada post em um nicho aprovado (Jev)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from .biblioteca import OUTROS, Biblioteca
from .ia import ClienteIA, ErroFatalIA, ErroIA
from .modelos import Post

LIMIAR_CONFIANCA = 0.5
LIMITE_STATE = 4000
INSTRUCOES = (
    "Pick the niche that best matches the main subject of this saved Instagram post. "
    "Use 'Outros' when none fits."
)


@dataclass
class ResultadoClassificacao:
    classificados: int
    em_outros: int
    sem_nichos: bool
    parado_por: str | None = None


def state_do_post(post: Post, transcricao: str) -> str:
    def montar(legenda: str, trans: str) -> str:
        return json.dumps(
            {"autor": post.autor, "legenda": legenda, "hashtags": post.hashtags, "transcricao": trans},
            ensure_ascii=False,
        )

    legenda, trans = post.legenda, transcricao
    state = montar(legenda, trans)
    while len(state) > LIMITE_STATE and (legenda or trans):
        excesso = len(state) - LIMITE_STATE
        if len(trans) >= len(legenda):
            trans = trans[: max(0, len(trans) - excesso)]
        else:
            legenda = legenda[: max(0, len(legenda) - excesso)]
        state = montar(legenda, trans)
    return state[:LIMITE_STATE]


def classificar_pendentes(bib: Biblioteca, ia: ClienteIA, modelo: str) -> ResultadoClassificacao:
    nichos = bib.nichos()
    if not nichos:
        return ResultadoClassificacao(0, 0, sem_nichos=True)
    opcoes = {n.nome: n.descricao for n in nichos}
    if OUTROS not in opcoes:
        opcoes[OUTROS] = "Posts que não se encaixam nos outros nichos."
    feitos = 0
    parado_por = None
    for post in bib.pendentes("classificado"):
        if not post.nicho_manual:
            try:
                escolha, confianca = ia.escolher(
                    state_do_post(post, bib.transcricao(post.shortcode)), opcoes, INSTRUCOES, modelo
                )
            except ErroFatalIA as e:
                parado_por = str(e)
                break
            except ErroIA:
                continue
            if escolha in opcoes:
                post.nicho, post.revisar = escolha, confianca < LIMIAR_CONFIANCA
            else:
                post.nicho, post.revisar = OUTROS, True
            post.confianca = confianca
            feitos += 1
        post.etapas["classificado"] = True
        bib.salvar(post)
    return ResultadoClassificacao(
        classificados=feitos,
        em_outros=bib.contagem().get(OUTROS, 0),
        sem_nichos=False,
        parado_por=parado_por,
    )
