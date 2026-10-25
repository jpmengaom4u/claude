"""Biblioteca: pastas dos posts (fonte da verdade) + índice SQLite/FTS5.

Toda leitura e gravação de dados passa por aqui.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import tomli_w

from .modelos import Nicho, Post

OUTROS = "Outros"
SEM_CLASSIFICACAO = "Sem classificação"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS posts (
    shortcode TEXT PRIMARY KEY,
    dados TEXT NOT NULL,
    data TEXT NOT NULL,
    nicho TEXT,
    revisar INTEGER NOT NULL,
    indisponivel INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(
    shortcode UNINDEXED, autor, legenda, transcricao,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _consulta_fts(q: str) -> str | None:
    termos = q.split()
    if not termos:
        return None
    return " ".join('"' + t.replace('"', '""') + '"' for t in termos)


def ler_nichos_toml(arquivo: Path) -> list[Nicho] | None:
    if not arquivo.exists():
        return None
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    return [Nicho(n["nome"], n.get("descricao", "")) for n in dados.get("nicho", [])]


def gravar_nichos_toml(arquivo: Path, lista: list[Nicho]) -> None:
    dados = {"nicho": [{"nome": n.nome, "descricao": n.descricao} for n in lista]}
    arquivo.write_text(tomli_w.dumps(dados), encoding="utf-8")


class Biblioteca:
    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self.posts = self.raiz / "posts"
        self.posts.mkdir(parents=True, exist_ok=True)
        self._trava = threading.Lock()
        self._db = sqlite3.connect(self.raiz / "biblioteca.db", check_same_thread=False)
        self._db.executescript(_ESQUEMA)

    def fechar(self) -> None:
        self._db.close()

    # --- posts -------------------------------------------------------------

    def pasta(self, shortcode: str) -> Path:
        return self.posts / shortcode

    def existe(self, shortcode: str) -> bool:
        return (self.pasta(shortcode) / "post.json").exists()

    @contextmanager
    def preparar(self, shortcode: str) -> Iterator[Path]:
        tmp = self.posts / f".tmp-{shortcode}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            yield tmp
            if not (tmp / "post.json").exists():
                raise RuntimeError(f"post.json ausente em {tmp}")
            destino = self.pasta(shortcode)
            shutil.rmtree(destino, ignore_errors=True)
            tmp.rename(destino)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        self._indexar(self.obter(shortcode))

    def obter(self, shortcode: str) -> Post:
        texto = (self.pasta(shortcode) / "post.json").read_text(encoding="utf-8")
        return Post.de_dict(json.loads(texto))

    def transcricao(self, shortcode: str) -> str:
        arq = self.pasta(shortcode) / "transcricao.txt"
        return arq.read_text(encoding="utf-8") if arq.exists() else ""

    def salvar(self, post: Post) -> None:
        arq = self.pasta(post.shortcode) / "post.json"
        tmp = arq.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(post.para_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(arq)
        self._indexar(post)

    def gravar_transcricao(self, shortcode: str, texto: str) -> None:
        (self.pasta(shortcode) / "transcricao.txt").write_text(texto, encoding="utf-8")
        post = self.obter(shortcode)
        post.etapas["transcrito"] = True
        self.salvar(post)

    def _indexar(self, post: Post) -> None:
        transcricao = self.transcricao(post.shortcode)
        with self._trava, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    post.shortcode,
                    json.dumps(post.para_dict(), ensure_ascii=False),
                    post.data,
                    post.nicho,
                    int(post.revisar),
                    int(post.indisponivel),
                ),
            )
            self._db.execute("DELETE FROM busca WHERE shortcode = ?", (post.shortcode,))
            self._db.execute(
                "INSERT INTO busca VALUES (?, ?, ?, ?)",
                (post.shortcode, post.autor, post.legenda, transcricao),
            )

    def listar(self, nicho: str | None = None, q: str | None = None, revisar: bool = False) -> list[Post]:
        sql = "SELECT p.dados FROM posts p"
        cond, args = [], []
        fts = _consulta_fts(q) if q else None
        if fts:
            sql += " JOIN busca b ON b.shortcode = p.shortcode"
            cond.append("busca MATCH ?")
            args.append(fts)
        if nicho == SEM_CLASSIFICACAO:
            cond.append("p.nicho IS NULL")
        elif nicho:
            cond.append("p.nicho = ?")
            args.append(nicho)
        if revisar:
            cond.append("p.revisar = 1")
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY p.data DESC"
        with self._trava:
            linhas = self._db.execute(sql, args).fetchall()
        return [Post.de_dict(json.loads(d)) for (d,) in linhas]

    def pendentes(self, etapa: str) -> list[Post]:
        return [p for p in self.listar() if not p.etapas.get(etapa) and not p.indisponivel]

    def contagem(self) -> dict[str, int]:
        with self._trava:
            linhas = self._db.execute("SELECT nicho, COUNT(*) FROM posts GROUP BY nicho").fetchall()
        return {(n if n is not None else SEM_CLASSIFICACAO): c for n, c in linhas}

    def reindexar(self) -> int:
        with self._trava, self._db:
            self._db.execute("DELETE FROM posts")
            self._db.execute("DELETE FROM busca")
        total = 0
        for pasta in sorted(self.posts.iterdir()):
            if pasta.name.startswith(".tmp-") or not (pasta / "post.json").exists():
                continue
            self._indexar(self.obter(pasta.name))
            total += 1
        return total

    # --- nichos ------------------------------------------------------------

    @property
    def _arquivo_nichos(self) -> Path:
        return self.raiz / "nichos.toml"

    def nichos(self) -> list[Nicho] | None:
        return ler_nichos_toml(self._arquivo_nichos)

    def salvar_nichos(self, lista: list[Nicho]) -> None:
        gravar_nichos_toml(self._arquivo_nichos, lista)

    def _mover_posts(self, de: str, para: str) -> None:
        for post in self.listar(nicho=de):
            post.nicho = para
            self.salvar(post)

    def renomear_nicho(self, antigo: str, novo: str) -> None:
        lista = self.nichos() or []
        for n in lista:
            if n.nome == antigo:
                n.nome = novo
        self.salvar_nichos(lista)
        self._mover_posts(antigo, novo)

    def juntar_nichos(self, origem: str, destino: str) -> None:
        self.salvar_nichos([n for n in (self.nichos() or []) if n.nome != origem])
        self._mover_posts(origem, destino)

    def apagar_nicho(self, nome: str) -> None:
        lista = [n for n in (self.nichos() or []) if n.nome != nome]
        if not any(n.nome == OUTROS for n in lista):
            lista.append(Nicho(OUTROS, "Posts que não se encaixam nos outros nichos."))
        self.salvar_nichos(lista)
        self._mover_posts(nome, OUTROS)
