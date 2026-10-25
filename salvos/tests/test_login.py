import sqlite3

import pytest

from salvos import login
from salvos.baixar import SessaoInvalida


def criar_firefox(appdata, cookies):
    perfil = appdata / "Mozilla" / "Firefox" / "Profiles" / "abc.default-release"
    perfil.mkdir(parents=True)
    con = sqlite3.connect(perfil / "cookies.sqlite")
    con.execute("CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT)")
    con.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?)", cookies)
    con.commit()
    con.close()


class LFalso:
    def __init__(self):
        import requests

        self.context = type("C", (), {})()
        self.context._session = requests.Session()
        self.salvo = None

    def test_login(self):
        return "joao" if self.context._session.cookies.get("sessionid") == "s1" else None

    def save_session_to_file(self, caminho):
        self.salvo = caminho
        open(caminho, "w").write("sessao")


def test_importar_firefox_salva_sessao(cfg, monkeypatch):
    criar_firefox(cfg.pasta_app.parent, [("sessionid", "s1", ".instagram.com"), ("x", "y", ".google.com")])
    monkeypatch.setattr(login, "novo_instaloader", LFalso)
    assert login.importar_firefox(cfg) == "joao"
    assert (cfg.pasta_app / "session-joao").exists()
    assert (cfg.pasta_app / "usuario.txt").read_text(encoding="utf-8") == "joao"


def test_importar_firefox_sem_login(cfg, monkeypatch):
    criar_firefox(cfg.pasta_app.parent, [("csrftoken", "c", ".instagram.com")])
    monkeypatch.setattr(login, "novo_instaloader", LFalso)
    with pytest.raises(SessaoInvalida, match="Nenhum login do Instagram encontrado no Firefox"):
        login.importar_firefox(cfg)


def test_novo_instaloader_nao_insiste_em_429():
    from salvos.baixar import PausaInstagram, novo_instaloader

    L = novo_instaloader()
    assert L.context.max_connection_attempts == 1
    with pytest.raises(PausaInstagram):
        L.context._rate_controller.handle_429("other")


def test_importar_firefox_le_cookie_ainda_no_wal(cfg, monkeypatch):
    perfil = cfg.pasta_app.parent / "Mozilla" / "Firefox" / "Profiles" / "abc.default-release"
    perfil.mkdir(parents=True)
    con = sqlite3.connect(perfil / "cookies.sqlite")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT)")
    con.commit()
    con.execute("INSERT INTO moz_cookies VALUES ('sessionid', 's1', '.instagram.com')")
    con.commit()  # fica no -wal enquanto o Firefox (esta conexão) está aberto
    monkeypatch.setattr(login, "novo_instaloader", LFalso)
    try:
        assert login.importar_firefox(cfg) == "joao"
    finally:
        con.close()


def test_login_interativo_salva_usuario_canonico(cfg, monkeypatch):
    class LInterativo(LFalso):
        def interactive_login(self, usuario):
            self.context._session.cookies.set("sessionid", "s1")

    monkeypatch.setattr(login, "novo_instaloader", LInterativo)
    assert login.login_interativo(cfg, "JoaoP") == "joao"
    assert (cfg.pasta_app / "usuario.txt").read_text(encoding="utf-8") == "joao"


def test_firefox_da_microsoft_store(cfg, monkeypatch, tmp_path):
    local = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    roaming = local / "Packages" / "Mozilla.Firefox_n80bbvh6b1yt2" / "LocalCache" / "Roaming"
    criar_firefox(roaming, [("sessionid", "s1", ".instagram.com")])
    monkeypatch.setattr(login, "novo_instaloader", LFalso)
    assert login.importar_firefox(cfg) == "joao"


def test_mensagem_sem_firefox(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "vazio"))
    monkeypatch.setattr(login.Path, "home", lambda: tmp_path / "home")
    with pytest.raises(SessaoInvalida, match="Não encontrei o Firefox"):
        login.importar_firefox(cfg)


def test_mensagem_instagram_recusou(cfg, monkeypatch):
    criar_firefox(cfg.pasta_app.parent, [("sessionid", "outro", ".instagram.com")])
    monkeypatch.setattr(login, "novo_instaloader", LFalso)
    with pytest.raises(SessaoInvalida, match="o Instagram não aceitou"):
        login.importar_firefox(cfg)
