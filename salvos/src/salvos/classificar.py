"""Classificação de cada post em um nicho aprovado.

Dois modos, escolhidos pelo modelo:
- Jev (`typesafe/...`): um post por chamada, com confiança numérica.
- Qualquer outro modelo de chat (ex.: os gratuitos): vários posts por chamada,
  para caber nos limites diários dos modelos gratuitos.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .biblioteca import OUTROS, Biblioteca
from .ia import ClienteIA, ErroFatalIA, ErroIA, LimiteIA
from .modelos import Post

LIMIAR_CONFIANCA = 0.5
LIMITE_STATE = 4000
LIMITE_STATE_LOTE = 1500
INSTRUCOES = (
    "Pick the niche that best matches the main subject of this saved Instagram post. "
    "Use 'Outros' when none fits."
)
INSTRUCOES_LOTE = (
    "Você classifica posts salvos do Instagram em nichos. Nichos disponíveis (nome: descrição):\n"
    "{nichos}\n\n"
    "Para cada post, escolha exatamente um nome da lista acima, pelo assunto principal. "
    "Use 'Outros' quando nenhum servir. Indique a certeza como 'alta' ou 'baixa'. "
    'Responda somente com JSON no formato {{"<id>": {{"nicho": "<nome>", "certeza": "alta"}}}}, '
    "com uma entrada para cada id recebido."
)


@dataclass
class ResultadoClassificacao:
    classificados: int
    em_outros: int
    sem_nichos: bool
    parado_por: str | None = None


def state_do_post(post: Post, transcricao: str, limite: int = LIMITE_STATE) -> str:
    def montar(legenda: str, trans: str) -> str:
        return json.dumps(
            {"autor": post.autor, "legenda": legenda, "hashtags": post.hashtags, "transcricao": trans},
            ensure_ascii=False,
        )

    legenda, trans = post.legenda, transcricao
    state = montar(legenda, trans)
    while len(state) > limite and (legenda or trans):
        excesso = len(state) - limite
        if len(trans) >= len(legenda):
            trans = trans[: max(0, len(trans) - excesso)]
        else:
            legenda = legenda[: max(0, len(legenda) - excesso)]
        state = montar(legenda, trans)
    return state[:limite]


def _aplicar(bib: Biblioteca, post: Post, escolha: str, confianca: float | None, revisar: bool, opcoes) -> bool:
    """Grava o nicho escolhido, a menos que o usuário tenha movido o post nesse meio-tempo."""
    atual = bib.obter(post.shortcode)
    atual.etapas["classificado"] = True
    if atual.nicho_manual:
        bib.salvar(atual)
        return False
    if escolha in opcoes:
        atual.nicho, atual.revisar = escolha, revisar
    else:
        atual.nicho, atual.revisar = OUTROS, True
    atual.confianca = confianca
    bib.salvar(atual)
    return True


def _por_post(bib, ia, modelo, pendentes, opcoes) -> tuple[int, str | None]:
    feitos = 0
    for post in pendentes:
        try:
            escolha, confianca = ia.escolher(
                state_do_post(post, bib.transcricao(post.shortcode)), opcoes, INSTRUCOES, modelo
            )
        except (ErroFatalIA, LimiteIA) as e:
            return feitos, str(e)
        except ErroIA:
            continue
        feitos += _aplicar(bib, post, escolha, confianca, confianca < LIMIAR_CONFIANCA, opcoes)
    return feitos, None


def _ler_resposta_lote(texto: str) -> dict:
    cerca = re.search(r"```(?:json)?\s*(.*?)```", texto, re.S)
    if cerca:
        texto = cerca.group(1)
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1:
        return {}
    try:
        dados = json.loads(texto[inicio : fim + 1])
    except json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _em_lote(bib, ia, modelo, pendentes, opcoes, tamanho_lote, reservas, progresso) -> tuple[int, str | None]:
    lista = "\n".join(f"- {nome}: {descricao}" for nome, descricao in opcoes.items())
    sistema = INSTRUCOES_LOTE.format(nichos=lista)
    feitos = 0
    total_lotes = -(-len(pendentes) // tamanho_lote)
    for i in range(0, len(pendentes), tamanho_lote):
        progresso(f"Classificando lote {i // tamanho_lote + 1}/{total_lotes}…")
        lote = pendentes[i : i + tamanho_lote]
        posts = [
            {"id": p.shortcode, **json.loads(state_do_post(p, bib.transcricao(p.shortcode), LIMITE_STATE_LOTE))}
            for p in lote
        ]
        mensagens = [
            {"role": "system", "content": sistema},
            {"role": "user", "content": "Posts:\n" + json.dumps(posts, ensure_ascii=False)},
        ]
        try:
            resposta = _ler_resposta_lote(ia.chat(modelo, mensagens, reservas=reservas))
        except (ErroFatalIA, LimiteIA) as e:
            return feitos, str(e)
        except ErroIA:
            continue
        for post in lote:
            item = resposta.get(post.shortcode)
            if isinstance(item, str):
                escolha, certeza = item, "alta"
            elif isinstance(item, dict) and isinstance(item.get("nicho"), str):
                escolha, certeza = item["nicho"], str(item.get("certeza", "alta"))
            else:
                continue  # o modelo esqueceu este post: fica para o próximo sync
            feitos += _aplicar(bib, post, escolha.strip(), None, certeza.strip().lower() != "alta", opcoes)
    return feitos, None


def classificar_pendentes(
    bib: Biblioteca,
    ia: ClienteIA,
    modelo: str,
    tamanho_lote: int = 25,
    reservas: list[str] | None = None,
    progresso: Callable[[str], None] = lambda texto: None,
) -> ResultadoClassificacao:
    nichos = bib.nichos()
    if not nichos:
        return ResultadoClassificacao(0, 0, sem_nichos=True)
    opcoes = {n.nome: n.descricao for n in nichos}
    if OUTROS not in opcoes:
        opcoes[OUTROS] = "Posts que não se encaixam nos outros nichos."

    pendentes = []
    for post in bib.pendentes("classificado"):
        if post.nicho_manual:
            post.etapas["classificado"] = True
            bib.salvar(post)
        else:
            pendentes.append(post)

    if modelo.startswith("typesafe/"):
        feitos, parado_por = _por_post(bib, ia, modelo, pendentes, opcoes)
    else:
        feitos, parado_por = _em_lote(bib, ia, modelo, pendentes, opcoes, max(1, tamanho_lote), reservas, progresso)
    return ResultadoClassificacao(
        classificados=feitos,
        em_outros=bib.contagem().get(OUTROS, 0),
        sem_nichos=False,
        parado_por=parado_por,
    )
