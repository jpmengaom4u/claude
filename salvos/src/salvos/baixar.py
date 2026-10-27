"""Download incremental dos posts salvos (Instaloader)."""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .biblioteca import Biblioteca
from .config import Config
from .modelos import Post


@dataclass
class PostRemoto:
    shortcode: str
    url: str
    autor: str
    data: str
    legenda: str
    hashtags: list[str]
    tipo: str
    midias: list[tuple[str, str]]


class PausaInstagram(Exception):
    """O Instagram pediu para esperar (429 / "Please wait a few minutes")."""


class SessaoInvalida(Exception):
    """Sessão ausente, expirada ou sem login."""


class FonteSalvos(Protocol):
    def iterar(self) -> Iterator[PostRemoto]: ...

    def baixar_midia(self, url: str, destino: Path) -> None: ...


@dataclass
class ResultadoDownload:
    novos: int
    pausado: bool
    falhas: int = 0


MAX_FALHAS_SEGUIDAS = 3


def _gravar(bib: Biblioteca, fonte: FonteSalvos, remoto: PostRemoto) -> None:
    with bib.preparar(remoto.shortcode) as pasta:
        arquivos = []
        for i, (url, ext) in enumerate(remoto.midias, start=1):
            nome = f"{i:02d}.{ext}"
            fonte.baixar_midia(url, pasta / nome)
            arquivos.append(nome)
        tem_video = any(a.endswith(".mp4") for a in arquivos)
        post = Post(
            shortcode=remoto.shortcode,
            url=remoto.url,
            autor=remoto.autor,
            data=remoto.data,
            legenda=remoto.legenda,
            hashtags=remoto.hashtags,
            tipo=remoto.tipo,
            arquivos=arquivos,
            etapas={"baixado": True, "transcrito": not tem_video, "classificado": False},
        )
        (pasta / "post.json").write_text(
            json.dumps(post.para_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def sincronizar_downloads(
    bib: Biblioteca,
    fonte: FonteSalvos,
    cfg: Config,
    completo: bool = False,
    limite: int | None = None,
    espera: Callable[[float], None] = time.sleep,
    aviso: Callable[[str], None] = print,
    progresso: Callable[[str], None] = lambda texto: None,
) -> ResultadoDownload:
    """Baixa os salvos novos.

    A parada após N posts conhecidos só vale depois que uma varredura chegou ao
    fim da lista de salvos; antes disso, cada execução continua o backlog.
    """
    maximo = limite or cfg.limite
    estado = bib.estado()
    parar_em_conhecidos = estado["varredura_completa"] and not completo
    novos = falhas = falhas_seguidas = conhecidos_seguidos = 0
    try:
        for remoto in fonte.iterar():
            if bib.existe(remoto.shortcode):
                conhecidos_seguidos += 1
                if parar_em_conhecidos and conhecidos_seguidos >= cfg.parada_conhecidos:
                    break
                continue
            conhecidos_seguidos = 0
            if novos or falhas:
                espera(random.uniform(cfg.pausa_min, cfg.pausa_max))
            try:
                _gravar(bib, fonte, remoto)
            except (PausaInstagram, SessaoInvalida):
                raise
            except Exception as erro:
                falhas += 1
                falhas_seguidas += 1
                aviso(f"Falha ao baixar {remoto.shortcode}, pulando: {erro}")
                if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                    aviso("Muitas falhas seguidas; parando o download por agora.")
                    break
                continue
            falhas_seguidas = 0
            novos += 1
            progresso(f"Baixando {novos}/{maximo}…")
            if novos >= maximo:
                break
        else:
            # Chegou ao fim da lista de salvos sem interrupção.
            bib.salvar_estado({**estado, "varredura_completa": True})
    except PausaInstagram:
        return ResultadoDownload(novos=novos, pausado=True, falhas=falhas)
    return ResultadoDownload(novos=novos, pausado=False, falhas=falhas)


# --- Instaloader -------------------------------------------------------------


def arquivo_sessao(cfg: Config, usuario: str) -> Path:
    return cfg.pasta_app / f"session-{usuario}"


def novo_instaloader():
    """Instaloader configurado para nunca insistir quando o Instagram pede pausa."""
    import instaloader

    class SemInsistir(instaloader.RateController):
        def handle_429(self, query_type: str) -> None:
            raise PausaInstagram("O Instagram respondeu 429 (muitas requisições).")

    return instaloader.Instaloader(
        quiet=True,
        max_connection_attempts=1,
        rate_controller=lambda ctx: SemInsistir(ctx),
        fatal_status_codes=[429],
        download_comments=False,
        save_metadata=False,
    )


def _cadeia(erro: BaseException) -> Iterator[BaseException]:
    vistos = set()
    atual: BaseException | None = erro
    while atual is not None and id(atual) not in vistos:
        vistos.add(id(atual))
        yield atual
        atual = atual.__cause__ or atual.__context__


def _eh_deslogado(erro: BaseException) -> bool:
    return any("logged out" in str(e).lower() or "redirected to login" in str(e).lower() for e in _cadeia(erro))


def _eh_pausa(erro: BaseException) -> bool:
    import instaloader

    for e in _cadeia(erro):
        if isinstance(e, (PausaInstagram, instaloader.TooManyRequestsException)):
            return True
        texto = str(e).lower()
        if "please wait a few minutes" in texto or re.search(r"\b429\b", texto):
            return True
    return False


class FonteInstaloader:
    def __init__(self, cfg: Config, usuario: str):
        import instaloader

        self._il = instaloader
        self.L = novo_instaloader()
        sessao = arquivo_sessao(cfg, usuario)
        if not sessao.exists():
            raise SessaoInvalida("Nenhuma sessão salva. Rode: salvos login")
        self.L.load_session_from_file(usuario, str(sessao))
        self.usuario = usuario

    def _traduzir(self, erro: BaseException) -> BaseException:
        if _eh_deslogado(erro) or isinstance(erro, (self._il.LoginRequiredException, self._il.LoginException)):
            return SessaoInvalida(str(erro))
        if _eh_pausa(erro):
            return PausaInstagram(str(erro))
        return erro

    def _erros(self) -> tuple[type[BaseException], ...]:
        return (self._il.InstaloaderException, self._il.AbortDownloadException, PausaInstagram)

    def iterar(self) -> Iterator[PostRemoto]:
        il = self._il
        try:
            perfil = il.Profile.from_username(self.L.context, self.usuario)
            for p in perfil.get_saved_posts():
                yield self._converter(p)
        except self._erros() as e:
            traduzido = self._traduzir(e)
            if traduzido is e:
                raise
            raise traduzido from e

    def _converter(self, p) -> PostRemoto:
        if p.typename == "GraphSidecar":
            tipo = "carrossel"
            midias = [
                (n.video_url, "mp4") if n.is_video else (n.display_url, "jpg")
                for n in p.get_sidecar_nodes()
            ]
        elif p.is_video:
            tipo = "video"
            midias = [(p.video_url, "mp4")]
        else:
            tipo = "imagem"
            midias = [(p.url, "jpg")]
        return PostRemoto(
            shortcode=p.shortcode,
            url=f"https://www.instagram.com/p/{p.shortcode}/",
            autor=p.owner_username,
            data=p.date_utc.isoformat(),
            legenda=p.caption or "",
            hashtags=list(p.caption_hashtags),
            tipo=tipo,
            midias=midias,
        )

    def baixar_midia(self, url: str, destino: Path) -> None:
        try:
            resp = self.L.context.get_raw(url)
            with open(destino, "wb") as f:
                for bloco in resp.iter_content(chunk_size=1 << 16):
                    f.write(bloco)
        except self._erros() as e:
            traduzido = self._traduzir(e)
            if traduzido is e:
                raise
            raise traduzido from e
