"""Login no Instagram: importa a sessão do Firefox ou faz login interativo."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .baixar import SessaoInvalida, arquivo_sessao, novo_instaloader
from .config import Config


def _perfis_firefox() -> list[Path]:
    bases = []
    if os.environ.get("APPDATA"):
        bases.append(Path(os.environ["APPDATA"]) / "Mozilla" / "Firefox" / "Profiles")
    bases.append(Path.home() / ".mozilla" / "firefox")
    bases.append(Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles")
    achados = [c for b in bases if b.exists() for c in b.glob("*/cookies.sqlite")]
    return sorted(achados, key=lambda c: c.stat().st_mtime, reverse=True)


def _ler_cookies(cookies_sqlite: Path) -> dict[str, str]:
    # O Firefox trava o arquivo enquanto está aberto: lemos uma cópia.
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "cookies.sqlite"
        shutil.copy2(cookies_sqlite, copia)
        con = sqlite3.connect(copia)
        try:
            linhas = con.execute(
                "SELECT name, value FROM moz_cookies WHERE host LIKE '%instagram.com'"
            ).fetchall()
        finally:
            con.close()
    return dict(linhas)


def _salvar(cfg: Config, L, usuario: str) -> str:
    cfg.pasta_app.mkdir(parents=True, exist_ok=True)
    L.context.username = usuario
    L.save_session_to_file(str(arquivo_sessao(cfg, usuario)))
    (cfg.pasta_app / "usuario.txt").write_text(usuario, encoding="utf-8")
    return usuario


def importar_firefox(cfg: Config) -> str:
    for cookies in _perfis_firefox():
        valores = _ler_cookies(cookies)
        if "sessionid" not in valores:
            continue
        L = novo_instaloader()
        L.context._session.cookies.update(valores)
        usuario = L.test_login()
        if usuario:
            return _salvar(cfg, L, usuario)
    raise SessaoInvalida("Nenhum login do Instagram encontrado no Firefox.")


def login_interativo(cfg: Config, usuario: str) -> str:
    L = novo_instaloader()
    L.interactive_login(usuario)
    return _salvar(cfg, L, usuario)
