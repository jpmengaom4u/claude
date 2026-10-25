import pytest

from salvos.config import carregar_config
from salvos.modelos import Post


def _post(**alteracoes) -> Post:
    dados = dict(
        shortcode="ABC123",
        url="https://www.instagram.com/p/ABC123/",
        autor="autor_teste",
        data="2026-09-12T10:00:00",
        legenda="Uma legenda qualquer",
        hashtags=[],
        tipo="imagem",
        arquivos=["01.jpg"],
        etapas={"baixado": True, "transcrito": True, "classificado": False},
    )
    dados.update(alteracoes)
    return Post(**dados)


@pytest.fixture
def post_exemplo():
    return _post


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("SALVOS_BIBLIOTECA", str(tmp_path / "Salvos"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return carregar_config()


@pytest.fixture
def bib(cfg):
    from salvos.biblioteca import Biblioteca

    return Biblioteca(cfg.biblioteca)


@pytest.fixture
def adicionar():
    import json

    def _adicionar(bib, post, transcricao=None):
        with bib.preparar(post.shortcode) as pasta:
            for nome in post.arquivos:
                (pasta / nome).write_bytes(b"x")
            (pasta / "post.json").write_text(json.dumps(post.para_dict(), ensure_ascii=False), encoding="utf-8")
        if transcricao is not None:
            bib.gravar_transcricao(post.shortcode, transcricao)

    return _adicionar


class IAFalsa:
    def __init__(self, chat=None, escolhas=None):
        self.respostas_chat = list(chat or [])
        self.escolhas = escolhas or {}
        self.chamadas_chat = []
        self.chamadas_escolher = []

    def chat(self, modelo, mensagens):
        self.chamadas_chat.append((modelo, mensagens))
        return self.respostas_chat.pop(0)

    def escolher(self, state, opcoes, instrucoes, modelo="typesafe/jev-1.13"):
        self.chamadas_escolher.append((state, opcoes, instrucoes))
        for chave, resposta in self.escolhas.items():
            if chave in state:
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        return ("Outros", 0.9)


@pytest.fixture
def ia_falsa():
    return IAFalsa
