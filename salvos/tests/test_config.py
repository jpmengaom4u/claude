from pathlib import Path

from salvos.config import carregar_config, chave_openrouter
from salvos.modelos import Post


def test_biblioteca_padrao_e_variavel(monkeypatch, tmp_path):
    monkeypatch.delenv("SALVOS_BIBLIOTECA", raising=False)
    assert carregar_config().biblioteca == Path.home() / "Salvos"
    monkeypatch.setenv("SALVOS_BIBLIOTECA", str(tmp_path / "x"))
    assert carregar_config().biblioteca == tmp_path / "x"


def test_toml_sobrepoe(cfg):
    cfg.biblioteca.mkdir(parents=True)
    (cfg.biblioteca / "salvos.toml").write_text("limite = 20\nporta = 9000\n", encoding="utf-8")
    novo = carregar_config()
    assert novo.limite == 20
    assert novo.porta == 9000
    assert novo.pausa_min == 4
    assert novo.modelo_classificacao == "typesafe/jev-1.13"


def test_chave_env_tem_prioridade(cfg, monkeypatch):
    cfg.pasta_app.mkdir(parents=True)
    (cfg.pasta_app / ".env").write_text("OPENROUTER_API_KEY=do-arquivo\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "da-variavel")
    assert chave_openrouter(cfg) == "da-variavel"


def test_chave_do_arquivo_env(cfg):
    assert chave_openrouter(cfg) is None
    cfg.pasta_app.mkdir(parents=True)
    (cfg.pasta_app / ".env").write_text("# comentario\nOPENROUTER_API_KEY=do-arquivo\n", encoding="utf-8")
    assert chave_openrouter(cfg) == "do-arquivo"


def test_post_ida_e_volta(post_exemplo):
    p = post_exemplo(legenda="Olá 🤖 ação", hashtags=["ia"])
    assert Post.de_dict(p.para_dict()) == p
