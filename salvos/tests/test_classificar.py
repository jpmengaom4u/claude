import json

from salvos.classificar import classificar_pendentes, state_do_post
from salvos.ia import ErroFatalIA, ErroIA
from salvos.modelos import Nicho

NICHOS = [Nicho("IA", "ia"), Nicho("Saúde", "saude"), Nicho("Outros", "resto")]


def preparar(bib, adicionar, post_exemplo, *posts):
    bib.salvar_nichos(NICHOS)
    for kw in posts:
        adicionar(bib, post_exemplo(**kw))


def test_classifica_e_marca_revisar_abaixo_de_05(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", legenda="xA"), dict(shortcode="B", legenda="xB"))
    ia = ia_falsa(escolhas={"xA": ("IA", 0.49), "xB": ("Saúde", 0.5)})
    r = classificar_pendentes(bib, ia, "typesafe/jev-1.13")
    assert r.classificados == 2
    a, b = bib.obter("A"), bib.obter("B")
    assert (a.nicho, a.revisar, a.confianca) == ("IA", True, 0.49)
    assert (b.nicho, b.revisar) == ("Saúde", False)
    assert a.etapas["classificado"] and b.etapas["classificado"]
    _, opcoes, instrucoes = ia.chamadas_escolher[0]
    assert opcoes == {"IA": "ia", "Saúde": "saude", "Outros": "resto"}
    assert "Outros" in instrucoes


def test_nicho_manual_nunca_sobrescrito(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", nicho="Saúde", nicho_manual=True))
    ia = ia_falsa()
    classificar_pendentes(bib, ia, "m")
    assert ia.chamadas_escolher == []
    assert bib.obter("A").nicho == "Saúde"
    assert bib.obter("A").etapas["classificado"] is True


def test_sem_nichos_toml_pula_classificacao(bib, adicionar, post_exemplo, ia_falsa):
    adicionar(bib, post_exemplo())
    ia = ia_falsa()
    r = classificar_pendentes(bib, ia, "m")
    assert r.sem_nichos is True
    assert ia.chamadas_escolher == []


def test_post_imagem_sem_legenda_tem_state_nao_vazio(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(autor="nutri_ana", legenda=""))
    ia = ia_falsa()
    classificar_pendentes(bib, ia, "m")
    state = ia.chamadas_escolher[0][0]
    assert "nutri_ana" in state
    assert bib.obter("ABC123").etapas["classificado"] is True


def test_state_corta_em_4000(post_exemplo):
    s = state_do_post(post_exemplo(legenda="a" * 3000), "b" * 3000)
    assert len(s) <= 4000
    assert json.loads(s)["legenda"].startswith("aaa")


def test_escolha_fora_da_lista_vira_outros(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(legenda="xA"))
    classificar_pendentes(bib, ia_falsa(escolhas={"xA": ("Inventado", 0.99)}), "m")
    p = bib.obter("ABC123")
    assert (p.nicho, p.revisar) == ("Outros", True)


def test_erro_temporario_deixa_pendente_e_segue(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", legenda="xA"), dict(shortcode="B", legenda="xB"))
    r = classificar_pendentes(bib, ia_falsa(escolhas={"xA": ErroIA("x"), "xB": ("IA", 0.9)}), "m")
    assert r.classificados == 1
    assert bib.obter("A").etapas["classificado"] is False
    assert bib.obter("B").nicho == "IA"


def test_erro_fatal_para_e_informa(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", legenda="xA", data="2026-02"), dict(shortcode="B", legenda="xB", data="2026-01"))
    ia = ia_falsa(escolhas={"xA": ErroFatalIA("Sem créditos na OpenRouter (HTTP 402)."), "xB": ("IA", 0.9)})
    r = classificar_pendentes(bib, ia, "m")
    assert r.parado_por == "Sem créditos na OpenRouter (HTTP 402)."
    assert r.classificados == 0
    assert bib.obter("B").etapas["classificado"] is False


def test_conta_em_outros(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"), dict(shortcode="B"))
    r = classificar_pendentes(bib, ia_falsa(), "m")
    assert r.em_outros == 2
