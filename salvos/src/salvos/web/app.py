"""Servidor local: API JSON + página + mídias."""
from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..biblioteca import OUTROS, SEM_CLASSIFICACAO, Biblioteca
from ..exportar import exportar_md, exportar_zip, nome_arquivo
from ..modelos import Nicho

ESTATICOS = Path(__file__).parent / "static"


class NovoNicho(BaseModel):
    nome: str
    descricao: str = ""


class AlterarNicho(BaseModel):
    novo_nome: str | None = None
    descricao: str | None = None
    juntar_em: str | None = None


class MoverPost(BaseModel):
    nicho: str


def _download(conteudo: bytes, nome: str, tipo: str) -> Response:
    disposicao = f"attachment; filename*=UTF-8''{quote(nome)}"
    return Response(conteudo, media_type=tipo, headers={"Content-Disposition": disposicao})


def criar_app(bib: Biblioteca) -> FastAPI:
    app = FastAPI(title="Salvos", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    def nomes_nichos() -> list[str]:
        return [n.nome for n in bib.nichos() or []]

    def exigir_nicho(nome: str) -> None:
        if nome not in nomes_nichos():
            raise HTTPException(404, f"Nicho não encontrado: {nome}")

    @app.get("/")
    def pagina():
        return FileResponse(ESTATICOS / "index.html")

    @app.get("/api/nichos")
    def listar_nichos():
        contagem = bib.contagem()
        saida = [{"nome": n.nome, "descricao": n.descricao, "total": contagem.get(n.nome, 0)} for n in bib.nichos() or []]
        listados = {n["nome"] for n in saida} | {SEM_CLASSIFICACAO}
        # Nichos que só existem nos posts (toml editado à mão, proposta nova etc.).
        for nome, total in sorted(contagem.items()):
            if nome not in listados:
                saida.append({"nome": nome, "descricao": "(fora da lista de nichos)", "total": total})
        if contagem.get(SEM_CLASSIFICACAO):
            saida.append({"nome": SEM_CLASSIFICACAO, "descricao": "", "total": contagem[SEM_CLASSIFICACAO]})
        return saida

    @app.post("/api/nichos", status_code=201)
    def criar_nicho(dados: NovoNicho):
        nome = dados.nome.strip()
        if not nome:
            raise HTTPException(400, "Nome vazio")
        if nome in nomes_nichos() or nome == SEM_CLASSIFICACAO:
            raise HTTPException(409, "Esse nicho já existe")
        lista = [n for n in bib.nichos() or [] if n.nome != OUTROS] + [Nicho(nome, dados.descricao)]
        outros = [n for n in bib.nichos() or [] if n.nome == OUTROS] or [
            Nicho(OUTROS, "Posts que não se encaixam nos outros nichos.")
        ]
        bib.salvar_nichos(lista + outros)
        return {"nome": nome}

    @app.patch("/api/nichos/{nome:path}")
    def alterar_nicho(nome: str, dados: AlterarNicho):
        exigir_nicho(nome)
        if dados.juntar_em:
            exigir_nicho(dados.juntar_em)
            if nome == OUTROS:
                raise HTTPException(400, "O nicho Outros não pode ser removido")
            bib.juntar_nichos(nome, dados.juntar_em)
            return {"ok": True}
        if dados.descricao is not None:
            lista = bib.nichos() or []
            for n in lista:
                if n.nome == nome:
                    n.descricao = dados.descricao
            bib.salvar_nichos(lista)
        if dados.novo_nome and dados.novo_nome.strip() != nome:
            novo = dados.novo_nome.strip()
            if nome == OUTROS:
                raise HTTPException(400, "O nicho Outros não pode ser renomeado")
            if novo in nomes_nichos():
                raise HTTPException(409, "Esse nicho já existe")
            bib.renomear_nicho(nome, novo)
        return {"ok": True}

    @app.delete("/api/nichos/{nome:path}")
    def apagar_nicho(nome: str):
        if nome == OUTROS:
            raise HTTPException(400, "O nicho Outros não pode ser apagado")
        exigir_nicho(nome)
        bib.apagar_nicho(nome)
        return {"ok": True}

    @app.get("/api/posts")
    def listar_posts(nicho: str | None = None, q: str | None = None, revisar: bool = False):
        return [
            {**p.para_dict(), "capa": p.arquivos[0] if p.arquivos else None}
            for p in bib.listar(nicho=nicho or None, q=q, revisar=revisar)
        ]

    @app.get("/api/posts/{shortcode}")
    def detalhe(shortcode: str):
        if not bib.existe(shortcode):
            raise HTTPException(404, "Post não encontrado")
        return {**bib.obter(shortcode).para_dict(), "transcricao": bib.transcricao(shortcode)}

    @app.patch("/api/posts/{shortcode}")
    def mover(shortcode: str, dados: MoverPost):
        if not bib.existe(shortcode):
            raise HTTPException(404, "Post não encontrado")
        if dados.nicho not in nomes_nichos():
            raise HTTPException(400, f"Nicho não encontrado: {dados.nicho}")
        post = bib.obter(shortcode)
        post.nicho, post.nicho_manual, post.revisar = dados.nicho, True, False
        post.etapas["classificado"] = True
        bib.salvar(post)
        return post.para_dict()

    @app.get("/api/exportar/{arquivo:path}")
    def exportar(arquivo: str):
        nicho, _, ext = arquivo.rpartition(".")
        if ext not in ("md", "zip") or not nicho:
            raise HTTPException(404, "Formato inválido")
        if nicho not in nomes_nichos() and nicho not in bib.contagem():
            raise HTTPException(404, f"Nicho não encontrado: {nicho}")
        base = nome_arquivo(nicho)
        if ext == "md":
            return _download(exportar_md(bib, nicho).encode("utf-8"), f"{base}.md", "text/markdown; charset=utf-8")
        buf = io.BytesIO()
        exportar_zip(bib, nicho, buf)
        return _download(buf.getvalue(), f"{base}.zip", "application/zip")

    @app.get("/midia/{shortcode}/{arquivo:path}")
    def midia(shortcode: str, arquivo: str):
        raiz = bib.posts.resolve()
        pasta = (bib.posts / shortcode).resolve()
        alvo = (pasta / arquivo).resolve()
        if pasta.parent != raiz or alvo.parent != pasta or not alvo.is_file():
            raise HTTPException(404, "Arquivo não encontrado")
        return FileResponse(alvo)

    return app
