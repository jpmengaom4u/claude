import json

import pytest

from salvos import cli
from salvos.baixar import PausaInstagram, PostRemoto, SessaoInvalida
from salvos.biblioteca import Biblioteca
from salvos.modelos import Nicho


def remoto(sc, tipo="imagem"):
    ext = "mp4" if tipo == "video" else "jpg"
    return PostRemoto(sc, f"https://www.instagram.com/p/{sc}/", "autor", "2026-01-01T00:00:00",
                      f"legenda {sc}", [], tipo, [(f"https://cdn/{sc}.{ext}", ext)])


class FonteFalsa:
    posts = []
    erro = None

    def __init__(self, cfg, usuario):
        if self.erro and isinstance(self.erro, SessaoInvalida):
            raise self.erro
        self.usuario = usuario

    def iterar(self):
        yield from self.posts
        if self.erro:
            raise self.erro

    def baixar_midia(self, url, destino):
        destino.write_bytes(b"x")


@pytest.fixture
def ambiente(cfg, monkeypatch, ia_falsa):
    cfg.pasta_app.mkdir(parents=True)
    (cfg.pasta_app / "usuario.txt").write_text("joao", encoding="utf-8")
    FonteFalsa.posts, FonteFalsa.erro = [], None
    ia = ia_falsa(escolhas={"legenda": ("IA", 0.9)})
    monkeypatch.setattr(cli, "FonteInstaloader", FonteFalsa)
    monkeypatch.setattr(cli, "transcritor_whisper", lambda cfg: (lambda caminho: "fala transcrita"))
    monkeypatch.setattr(cli, "ClienteIA", lambda *a, **k: ia)
    original = cli.sincronizar_downloads
    monkeypatch.setattr(cli, "sincronizar_downloads", lambda *a, **k: original(*a, espera=lambda s: None, **k))
    return cfg, ia


def com_nichos(cfg, *extras):
    Biblioteca(cfg.biblioteca).salvar_nichos([Nicho("IA", "ia"), *extras, Nicho("Outros", "o")])


def test_sync_completo_com_fakes(ambiente, capsys):
    cfg, _ = ambiente
    com_nichos(cfg)
    FonteFalsa.posts = [remoto("A"), remoto("B", "video"), remoto("C")]
    assert cli.main(["sync"]) == 0
    bib = Biblioteca(cfg.biblioteca)
    assert all(p.nicho == "IA" for p in bib.listar())
    assert bib.transcricao("B") == "fala transcrita"
    assert "Novos: 3 · Transcritos: 1 · Classificados: 3" in capsys.readouterr().out


def test_sync_pausa_mostra_mensagem_e_segue_etapas(ambiente, capsys):
    cfg, _ = ambiente
    com_nichos(cfg)
    FonteFalsa.posts, FonteFalsa.erro = [remoto("A")], PausaInstagram("429")
    assert cli.main(["sync"]) == 0
    out = capsys.readouterr().out
    assert "O Instagram pediu uma pausa. O progresso foi salvo; tente de novo daqui a algumas horas." in out
    assert Biblioteca(cfg.biblioteca).obter("A").nicho == "IA"


def test_sync_sessao_invalida(ambiente, capsys):
    FonteFalsa.erro = SessaoInvalida("expirou")
    assert cli.main(["sync"]) == 1
    assert "Sessão do Instagram inválida ou expirada. Rode: salvos login" in capsys.readouterr().out


def test_sync_sem_usuario_pede_login(ambiente, capsys):
    cfg, _ = ambiente
    (cfg.pasta_app / "usuario.txt").unlink()
    assert cli.main(["sync"]) == 1
    assert "salvos login" in capsys.readouterr().out


def test_sync_sem_nichos_avisa(ambiente, capsys):
    FonteFalsa.posts = [remoto("A")]
    assert cli.main(["sync"]) == 0
    assert "Rode `salvos nichos` para definir seus nichos." in capsys.readouterr().out


def test_sync_sugere_revisar_com_10_em_outros(ambiente, capsys):
    cfg, ia = ambiente
    com_nichos(cfg)
    ia.escolhas = {}
    FonteFalsa.posts = [remoto(f"P{i:02d}") for i in range(10)]
    cli.main(["sync"])
    assert "Há 10 posts em Outros. Rode `salvos nichos --revisar` para sugerir nichos novos." in capsys.readouterr().out


def test_sync_erro_fatal_ia(ambiente, capsys):
    from salvos.ia import ErroFatalIA

    cfg, ia = ambiente
    com_nichos(cfg)
    ia.escolhas = {"legenda": ErroFatalIA("Sem créditos na OpenRouter (HTTP 402).")}
    FonteFalsa.posts = [remoto("A")]
    assert cli.main(["sync"]) == 1
    assert "Sem créditos na OpenRouter (HTTP 402)." in capsys.readouterr().out


def test_nichos_aceitar_grava_toml(ambiente, monkeypatch, capsys):
    cfg, ia = ambiente
    FonteFalsa.posts = [remoto("A")]
    cli.main(["sync"])
    ia.respostas_chat = [json.dumps([{"nome": "IA", "descricao": "ia"}, {"nome": "Saúde", "descricao": "s"}])]
    respostas = iter(["a", "s"])
    monkeypatch.setattr("builtins.input", lambda _="": next(respostas))
    assert cli.main(["nichos"]) == 0
    bib = Biblioteca(cfg.biblioteca)
    assert [n.nome for n in bib.nichos()] == ["IA", "Saúde", "Outros"]
    assert bib.obter("A").nicho == "IA"
    out = capsys.readouterr().out
    assert "1. IA — ia" in out


def test_nichos_revisar_soma_aos_existentes(ambiente, monkeypatch):
    cfg, ia = ambiente
    com_nichos(cfg)
    ia.respostas_chat = [json.dumps([{"nome": "Culinária", "descricao": "c"}])]
    respostas = iter(["a", "n"])
    monkeypatch.setattr("builtins.input", lambda _="": next(respostas))
    FonteFalsa.posts = [remoto("A")]
    cli.main(["sync"])
    assert cli.main(["nichos", "--revisar"]) == 0
    assert [n.nome for n in Biblioteca(cfg.biblioteca).nichos()] == ["IA", "Culinária", "Outros"]


def test_nichos_sem_posts(ambiente, capsys):
    assert cli.main(["nichos"]) == 1
    assert "salvos sync --limite 5" in capsys.readouterr().out


def test_reindexar_imprime_total(ambiente, capsys):
    FonteFalsa.posts = [remoto("A"), remoto("B")]
    cli.main(["sync"])
    assert cli.main(["reindexar"]) == 0
    assert "Índice recriado: 2 posts." in capsys.readouterr().out


def test_abrir_usa_127_0_0_1(ambiente, monkeypatch):
    chamadas = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: chamadas.update(kw))
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: chamadas.update(url=url))

    class TimerImediato:
        def __init__(self, atraso, funcao, args=()):
            self.funcao, self.args = funcao, args

        def start(self):
            self.funcao(*self.args)

    monkeypatch.setattr(cli.threading, "Timer", TimerImediato)
    assert cli.main(["abrir", "--porta", "9001"]) == 0
    assert chamadas["host"] == "127.0.0.1" and chamadas["port"] == 9001
    assert chamadas["url"] == "http://127.0.0.1:9001"


def test_nichos_editar_rele_arquivo(ambiente, monkeypatch):
    cfg, ia = ambiente
    FonteFalsa.posts = [remoto("A")]
    cli.main(["sync"])
    ia.respostas_chat = [json.dumps([{"nome": "IA", "descricao": "ia"}])]
    monkeypatch.delattr(cli.os, "startfile", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    arquivo = cfg.biblioteca / "nichos-proposta.toml"

    def responder(prompt=""):
        if prompt.startswith("[a]"):
            return "e"
        if prompt.startswith("Classificar"):
            return "n"
        arquivo.write_text('[[nicho]]\nnome = "Tecnologia"\ndescricao = "tech"\n', encoding="utf-8")
        return ""

    monkeypatch.setattr("builtins.input", responder)
    assert cli.main(["nichos"]) == 0
    assert [n.nome for n in Biblioteca(cfg.biblioteca).nichos()] == ["Tecnologia", "Outros"]
    assert not arquivo.exists()
