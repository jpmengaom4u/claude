import json

from salvos.classificar import classificar_pendentes, state_do_post
from salvos.ia import ErroFatalIA, ErroIA
from salvos.modelos import Nicho

JEV = "typesafe/jev-1.13"
NICHOS = [Nicho("IA", "ia"), Nicho("Saúde", "saude"), Nicho("Outros", "resto")]


def preparar(bib, adicionar, post_exemplo, *posts):
    bib.salvar_nichos(NICHOS)
    for kw in posts:
        adicionar(bib, post_exemplo(**kw))


def test_classifica_e_marca_revisar_abaixo_de_05(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", legenda="xA"), dict(shortcode="B", legenda="xB"))
    ia = ia_falsa(escolhas={"xA": ("IA", 0.49), "xB": ("Saúde", 0.5)})
    r = classificar_pendentes(bib, ia, JEV)
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
    classificar_pendentes(bib, ia, JEV)
    assert ia.chamadas_escolher == []
    assert bib.obter("A").nicho == "Saúde"
    assert bib.obter("A").etapas["classificado"] is True


def test_sem_nichos_toml_pula_classificacao(bib, adicionar, post_exemplo, ia_falsa):
    adicionar(bib, post_exemplo())
    ia = ia_falsa()
    r = classificar_pendentes(bib, ia, JEV)
    assert r.sem_nichos is True
    assert ia.chamadas_escolher == []


def test_post_imagem_sem_legenda_tem_state_nao_vazio(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(autor="nutri_ana", legenda=""))
    ia = ia_falsa()
    classificar_pendentes(bib, ia, JEV)
    state = ia.chamadas_escolher[0][0]
    assert "nutri_ana" in state
    assert bib.obter("ABC123").etapas["classificado"] is True


def test_state_corta_em_4000(post_exemplo):
    s = state_do_post(post_exemplo(legenda="a" * 3000), "b" * 3000)
    assert len(s) <= 4000
    assert json.loads(s)["legenda"].startswith("aaa")


def test_escolha_fora_da_lista_vira_outros(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(legenda="xA"))
    classificar_pendentes(bib, ia_falsa(escolhas={"xA": ("Inventado", 0.99)}), JEV)
    p = bib.obter("ABC123")
    assert (p.nicho, p.revisar) == ("Outros", True)


def test_erro_temporario_deixa_pendente_e_segue(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", legenda="xA"), dict(shortcode="B", legenda="xB"))
    r = classificar_pendentes(bib, ia_falsa(escolhas={"xA": ErroIA("x"), "xB": ("IA", 0.9)}), JEV)
    assert r.classificados == 1
    assert bib.obter("A").etapas["classificado"] is False
    assert bib.obter("B").nicho == "IA"


def test_erro_fatal_para_e_informa(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", legenda="xA", data="2026-02"), dict(shortcode="B", legenda="xB", data="2026-01"))
    ia = ia_falsa(escolhas={"xA": ErroFatalIA("Sem créditos na OpenRouter (HTTP 402)."), "xB": ("IA", 0.9)})
    r = classificar_pendentes(bib, ia, JEV)
    assert r.parado_por == "Sem créditos na OpenRouter (HTTP 402)."
    assert r.classificados == 0
    assert bib.obter("B").etapas["classificado"] is False


def test_conta_em_outros(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"), dict(shortcode="B"))
    r = classificar_pendentes(bib, ia_falsa(), JEV)
    assert r.em_outros == 2


def test_escolha_manual_feita_durante_classificacao_nao_e_sobrescrita(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(legenda="xA"))

    class IAQueDemora(ia_falsa):
        def escolher(self, state, opcoes, instrucoes, modelo="m"):
            # Enquanto a IA pensa, o usuário move o post na página.
            p = bib.obter("ABC123")
            p.nicho, p.nicho_manual = "Saúde", True
            bib.salvar(p)
            return ("IA", 0.9)

    classificar_pendentes(bib, IAQueDemora(), JEV)
    p = bib.obter("ABC123")
    assert (p.nicho, p.nicho_manual) == ("Saúde", True)


# --- modo em lote (modelos gratuitos) ---------------------------------------

LIVRE = "google/gemma-4-31b-it:free"


def resposta_lote(mapa):
    return json.dumps(mapa, ensure_ascii=False)


def ids_enviados(mensagens):
    texto = mensagens[-1]["content"]
    return [p["id"] for p in json.loads(texto[texto.index("["):])]


def test_lote_classifica_varios_posts_por_chamada(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, *[dict(shortcode=f"P{i}", data=f"2026-01-0{i}") for i in range(1, 4)])
    responder = lambda msgs: resposta_lote({i: {"nicho": "IA", "certeza": "alta"} for i in ids_enviados(msgs)})
    ia = ia_falsa(chat=[responder, responder])
    r = classificar_pendentes(bib, ia, LIVRE, tamanho_lote=2)
    assert r.classificados == 3
    assert len(ia.chamadas_chat) == 2 and ia.chamadas_escolher == []
    assert all(bib.obter(f"P{i}").nicho == "IA" for i in range(1, 4))
    sistema = ia.chamadas_chat[0][1][0]["content"]
    assert "IA: ia" in sistema and "Outros" in sistema


def test_lote_post_esquecido_fica_pendente(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"), dict(shortcode="B"))
    ia = ia_falsa(chat=[resposta_lote({"A": {"nicho": "Saúde", "certeza": "alta"}})])
    r = classificar_pendentes(bib, ia, LIVRE)
    assert r.classificados == 1
    assert bib.obter("B").etapas["classificado"] is False


def test_lote_nicho_inventado_vira_outros_e_revisar(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"))
    classificar_pendentes(bib, ia_falsa(chat=[resposta_lote({"A": {"nicho": "Culinária", "certeza": "alta"}})]), LIVRE)
    p = bib.obter("A")
    assert (p.nicho, p.revisar) == ("Outros", True)


def test_lote_certeza_baixa_marca_revisar_e_aceita_texto_simples(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"), dict(shortcode="B"))
    resposta = "Claro!\n```json\n" + resposta_lote({"A": {"nicho": "IA", "certeza": "baixa"}, "B": "Saúde"}) + "\n```"
    classificar_pendentes(bib, ia_falsa(chat=[resposta]), LIVRE)
    assert (bib.obter("A").nicho, bib.obter("A").revisar) == ("IA", True)
    assert (bib.obter("B").nicho, bib.obter("B").revisar) == ("Saúde", False)


def test_lote_resposta_invalida_deixa_lote_pendente_e_segue(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A", data="2026-02"), dict(shortcode="B", data="2026-01"))
    ia = ia_falsa(chat=["não entendi", resposta_lote({"B": {"nicho": "IA", "certeza": "alta"}})])
    r = classificar_pendentes(bib, ia, LIVRE, tamanho_lote=1)
    assert r.classificados == 1
    assert bib.obter("A").etapas["classificado"] is False
    assert bib.obter("B").nicho == "IA"


def test_lote_nao_envia_posts_manuais(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="M", nicho="Saúde", nicho_manual=True), dict(shortcode="A"))
    ia = ia_falsa(chat=[lambda msgs: resposta_lote({i: "IA" for i in ids_enviados(msgs)})])
    classificar_pendentes(bib, ia, LIVRE)
    assert ids_enviados(ia.chamadas_chat[0][1]) == ["A"]
    assert bib.obter("M").nicho == "Saúde"


def test_lote_limite_diario_para_com_mensagem(bib, adicionar, post_exemplo, ia_falsa):
    from salvos.ia import LimiteIA

    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"), dict(shortcode="B"))
    ia = ia_falsa(chat=[LimiteIA("Limite dos modelos gratuitos atingido.")])
    r = classificar_pendentes(bib, ia, LIVRE, tamanho_lote=1)
    assert r.parado_por == "Limite dos modelos gratuitos atingido."
    assert len(ia.chamadas_chat) == 1


def test_lote_repassa_reservas(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, dict(shortcode="A"))
    ia = ia_falsa(chat=[resposta_lote({"A": "IA"})])
    classificar_pendentes(bib, ia, LIVRE, reservas=["r1:free"])
    assert ia.reservas_usadas == ["r1:free"]


def test_progresso_da_classificacao_em_lote(bib, adicionar, post_exemplo, ia_falsa):
    preparar(bib, adicionar, post_exemplo, *[dict(shortcode=f"P{i}", data=f"2026-01-0{i}") for i in range(1, 4)])
    responder = lambda msgs: resposta_lote({i: "IA" for i in ids_enviados(msgs)})
    passos = []
    classificar_pendentes(bib, ia_falsa(chat=[responder, responder]), LIVRE, tamanho_lote=2, progresso=passos.append)
    assert passos == ["Classificando lote 1/2…", "Classificando lote 2/2…"]
