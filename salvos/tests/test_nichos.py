import json

import pytest

from salvos.ia import ErroIA
from salvos.modelos import Nicho
from salvos.nichos import propor_nichos, resumo, revisar_nichos


def test_resumo_corta_em_300(post_exemplo):
    p = post_exemplo(autor="fulano", legenda="a" * 500)
    r = resumo(p, "b" * 500)
    assert r == "@fulano: " + "a" * 300 + " | " + "b" * 300


def test_propor_nichos_parse_com_cerca_e_garante_outros(bib, adicionar, post_exemplo, ia_falsa):
    adicionar(bib, post_exemplo(shortcode="A", legenda="prompt de ChatGPT"))
    lista = [{"nome": "IA", "descricao": "Inteligência artificial"}, {"nome": "Saúde", "descricao": "Saúde"}]
    ia = ia_falsa(chat=["Aqui está:\n```json\n" + json.dumps(lista, ensure_ascii=False) + "\n```"])
    nichos = propor_nichos(bib, ia, "modelo-x")
    assert [n.nome for n in nichos] == ["IA", "Saúde", "Outros"]
    modelo, mensagens = ia.chamadas_chat[0]
    assert modelo == "modelo-x"
    texto = " ".join(m["content"] for m in mensagens)
    assert "prompt de ChatGPT" in texto
    assert "5" in texto and "15" in texto


def test_propor_nichos_nao_duplica_outros(bib, adicionar, post_exemplo, ia_falsa):
    adicionar(bib, post_exemplo())
    ia = ia_falsa(chat=[json.dumps([{"nome": "IA", "descricao": "x"}, {"nome": "outros", "descricao": "y"}])])
    assert [n.nome for n in propor_nichos(bib, ia, "m")] == ["IA", "Outros"]


def test_propor_nichos_json_invalido_levanta_erro(bib, adicionar, post_exemplo, ia_falsa):
    adicionar(bib, post_exemplo())
    with pytest.raises(ErroIA, match="Resposta da IA sem lista de nichos válida"):
        propor_nichos(bib, ia_falsa(chat=["não sei"]), "m")


def test_revisar_usa_so_posts_de_outros_e_passa_existentes(bib, adicionar, post_exemplo, ia_falsa):
    bib.salvar_nichos([Nicho("IA", "ia"), Nicho("Outros", "o")])
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA", legenda="sobre llms"))
    adicionar(bib, post_exemplo(shortcode="B", nicho="Outros", legenda="receita de bolo"))
    ia = ia_falsa(chat=[json.dumps([{"nome": "Culinária", "descricao": "receitas"}])])
    novos = revisar_nichos(bib, ia, "m")
    assert [n.nome for n in novos] == ["Culinária"]
    texto = " ".join(m["content"] for m in ia.chamadas_chat[0][1])
    assert "receita de bolo" in texto
    assert "sobre llms" not in texto
    assert "IA" in texto


def test_propor_nichos_repassa_reservas(bib, adicionar, post_exemplo, ia_falsa):
    adicionar(bib, post_exemplo())
    ia = ia_falsa(chat=[json.dumps([{"nome": "IA", "descricao": "x"}])])
    propor_nichos(bib, ia, "m", reservas=["r1:free"])
    assert ia.reservas_usadas == ["r1:free"]
