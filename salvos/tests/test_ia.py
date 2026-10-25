import json

import httpx
import pytest

from salvos.ia import ClienteIA, ErroFatalIA, ErroIA

CHAVE = "sk-or-segredo-123"


def cliente(respostas, chamadas):
    fila = list(respostas)

    def tratar(req: httpx.Request):
        chamadas.append(req)
        status, corpo = fila.pop(0)
        return httpx.Response(status, json=corpo)

    esperas = []
    c = ClienteIA(CHAVE, http=httpx.Client(transport=httpx.MockTransport(tratar)), espera=esperas.append)
    return c, esperas


def test_escolher_envia_pergunta_choice_e_le_resposta():
    chamadas = []
    resp = {"answers": {"nicho": {"type": "choice", "choice": "IA", "confidence": 0.91}}}
    c, _ = cliente([(200, resp)], chamadas)
    assert c.escolher("estado", {"IA": "inteligência artificial", "Outros": "resto"}, "Pick one") == ("IA", 0.91)
    req = chamadas[0]
    assert str(req.url) == "https://openrouter.ai/api/alpha/decisions"
    assert req.headers["Authorization"] == f"Bearer {CHAVE}"
    corpo = json.loads(req.content)
    assert corpo == {
        "model": "typesafe/jev-1.13",
        "state": "estado",
        "questions": {
            "nicho": {
                "type": "choice",
                "instructions": "Pick one",
                "criteria": {"IA": "inteligência artificial", "Outros": "resto"},
            }
        },
    }


def test_chat_retorna_conteudo():
    chamadas = []
    c, _ = cliente([(200, {"choices": [{"message": {"content": "olá"}}]})], chamadas)
    assert c.chat("anthropic/x", [{"role": "user", "content": "oi"}]) == "olá"
    assert str(chamadas[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert json.loads(chamadas[0].content)["model"] == "anthropic/x"


def test_retry_em_429_depois_sucesso():
    chamadas = []
    ok = {"choices": [{"message": {"content": "ok"}}]}
    c, esperas = cliente([(429, {}), (429, {}), (200, ok)], chamadas)
    assert c.chat("m", []) == "ok"
    assert esperas == [2, 4]


def test_erro_apos_tres_tentativas():
    chamadas = []
    c, esperas = cliente([(500, {})] * 4, chamadas)
    with pytest.raises(ErroIA) as e:
        c.chat("m", [])
    assert not isinstance(e.value, ErroFatalIA)
    assert len(chamadas) == 4
    assert esperas == [2, 4, 8]


@pytest.mark.parametrize("status,texto", [(401, "Chave da OpenRouter inválida"), (402, "Sem créditos na OpenRouter")])
def test_401_e_402_sao_fatais_sem_retry(status, texto):
    chamadas = []
    c, _ = cliente([(status, {"error": CHAVE})], chamadas)
    with pytest.raises(ErroFatalIA, match=texto):
        c.chat("m", [])
    assert len(chamadas) == 1


def test_chave_nunca_aparece_na_mensagem_de_erro():
    chamadas = []
    c, _ = cliente([(500, {"error": f"bad key {CHAVE}"})] * 4, chamadas)
    with pytest.raises(ErroIA) as e:
        c.chat("m", [])
    assert CHAVE not in str(e.value)


def test_sem_chave_nao_envia_authorization():
    chamadas = []

    def tratar(req):
        chamadas.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    c = ClienteIA(None, http=httpx.Client(transport=httpx.MockTransport(tratar)))
    c.chat("m", [])
    assert "Authorization" not in chamadas[0].headers


def test_429_persistente_vira_limite():
    from salvos.ia import LimiteIA

    chamadas = []
    c, _ = cliente([(429, {})] * 4, chamadas)
    with pytest.raises(LimiteIA, match="tente de novo amanhã"):
        c.chat("m", [])


def test_chat_envia_lista_de_reservas():
    chamadas = []
    c, _ = cliente([(200, {"choices": [{"message": {"content": "ok"}}]})], chamadas)
    c.chat("a:free", [], reservas=["b:free", "c:free"])
    corpo = json.loads(chamadas[0].content)
    assert corpo["model"] == "a:free"
    assert corpo["models"] == ["a:free", "b:free", "c:free"]


def test_chat_sem_reservas_nao_envia_models():
    chamadas = []
    c, _ = cliente([(200, {"choices": [{"message": {"content": "ok"}}]})], chamadas)
    c.chat("a", [])
    assert "models" not in json.loads(chamadas[0].content)


def test_429_upstream_diz_que_esta_congestionado():
    from salvos.ia import LimiteIA

    chamadas = []
    corpo = {"error": {"code": 429, "metadata": {"raw": "x:free is temporarily rate-limited upstream"}}}
    c, _ = cliente([(429, corpo)] * 4, chamadas)
    with pytest.raises(LimiteIA, match="congestionados"):
        c.chat("m", [])
