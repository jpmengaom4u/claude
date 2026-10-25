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
