"""Transcrição do áudio dos vídeos com faster-whisper (local, CPU)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .biblioteca import Biblioteca
from .config import Config

Transcritor = Callable[[Path], str]


def transcritor_whisper(cfg: Config) -> Transcritor:
    from faster_whisper import WhisperModel

    modelo = WhisperModel(cfg.modelo_whisper, device="cpu", compute_type="int8")

    def transcrever(caminho: Path) -> str:
        segmentos, _ = modelo.transcribe(str(caminho))
        return " ".join(s.text.strip() for s in segmentos).strip()

    return transcrever


def transcrever_pendentes(
    bib: Biblioteca,
    transcrever: Transcritor,
    aviso: Callable[[str], None] = print,
) -> int:
    feitos = 0
    for post in bib.pendentes("transcrito"):
        videos = [bib.pasta(post.shortcode) / a for a in post.arquivos if a.endswith(".mp4")]
        try:
            partes = [transcrever(v) for v in videos]
        except Exception as erro:
            aviso(f"Falha ao transcrever {post.shortcode}: {erro}")
            continue
        bib.gravar_transcricao(post.shortcode, "\n\n".join(p for p in partes if p))
        feitos += 1
    return feitos
