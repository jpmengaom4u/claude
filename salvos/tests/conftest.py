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
