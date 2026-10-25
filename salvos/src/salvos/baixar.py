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
) -> ResultadoDownload:
    maximo = limite or cfg.limite
    novos = 0
    conhecidos_seguidos = 0
    try:
        for remoto in fonte.iterar():
            if bib.existe(remoto.shortcode):
                conhecidos_seguidos += 1
                if not completo and conhecidos_seguidos >= cfg.parada_conhecidos:
                    break
                continue
            conhecidos_seguidos = 0
            if novos:
                espera(random.uniform(cfg.pausa_min, cfg.pausa_max))
            _gravar(bib, fonte, remoto)
            novos += 1
            if novos >= maximo:
                break
    except PausaInstagram:
        return ResultadoDownload(novos=novos, pausado=True)
    return ResultadoDownload(novos=novos, pausado=False)


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


def _eh_pausa(erro: BaseException) -> bool:
    import instaloader

    atual: BaseException | None = erro
    while atual is not None:
        if isinstance(atual, (PausaInstagram, instaloader.TooManyRequestsException, instaloader.AbortDownloadException)):
            return True
        texto = str(atual).lower()
        if "please wait a few minutes" in texto or re.search(r"\b429\b", texto):
            return True
        atual = atual.__cause__ or atual.__context__
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
        if _eh_pausa(erro):
            return PausaInstagram(str(erro))
        if isinstance(erro, (self._il.LoginRequiredException, self._il.LoginException)):
            return SessaoInvalida(str(erro))
        return erro

    def iterar(self) -> Iterator[PostRemoto]:
        il = self._il
        try:
            perfil = il.Profile.from_username(self.L.context, self.usuario)
            for p in perfil.get_saved_posts():
                yield self._converter(p)
        except (il.InstaloaderException, PausaInstagram) as e:
            raise self._traduzir(e) from e

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
        except (self._il.InstaloaderException, PausaInstagram) as e:
            raise self._traduzir(e) from e
