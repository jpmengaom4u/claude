"""Transcrição do áudio dos vídeos com faster-whisper (local, CPU)."""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Callable

import numpy as np

from .biblioteca import Biblioteca
from .config import Config

Transcritor = Callable[[Path], str]


TAXA = 16000


def decodificar_audio(caminho: Path) -> np.ndarray:
    """Áudio do arquivo em 16 kHz mono float32; vazio se não houver trilha de áudio.

    Feito aqui, e não pelo decode_audio do faster-whisper, porque ele usa uma opção
    que o PyAV 19 removeu.
    """
    import av

    partes = []
    with av.open(str(caminho)) as container:
        if not container.streams.audio:
            return np.zeros(0, dtype=np.float32)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TAXA)
        trilha = container.streams.audio[0]
        try:
            quadros = list(container.decode(trilha))
        except av.error.InvalidDataError:
            quadros = []  # fica com o que deu para ler
        for quadro in [*quadros, None]:
            for saida in resampler.resample(quadro):
                partes.append(saida.to_ndarray().reshape(-1))
    if not partes:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(partes).astype(np.float32) / 32768.0


def transcritor_whisper(cfg: Config) -> Transcritor:
    # Avisos do Hugging Face no Windows (symlinks, download sem conta) não são erros.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    warnings.filterwarnings("ignore", module="huggingface_hub")
    try:
        from huggingface_hub.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
    except ImportError:
        pass
    from faster_whisper import WhisperModel

    modelo = WhisperModel(cfg.modelo_whisper, device="cpu", compute_type="int8")

    def transcrever(caminho: Path) -> str:
        audio = decodificar_audio(caminho)
        if len(audio) == 0:
            return ""
        segmentos, _ = modelo.transcribe(audio)
        return " ".join(s.text.strip() for s in segmentos).strip()

    return transcrever


def transcrever_pendentes(
    bib: Biblioteca,
    transcrever: Transcritor,
    aviso: Callable[[str], None] = print,
    progresso: Callable[[str], None] = lambda texto: None,
) -> int:
    feitos = 0
    pendentes = bib.pendentes("transcrito")
    for n, post in enumerate(pendentes, start=1):
        progresso(f"Transcrevendo {n}/{len(pendentes)}…")
        videos = [bib.pasta(post.shortcode) / a for a in post.arquivos if a.endswith(".mp4")]
        try:
            partes = [transcrever(v) for v in videos]
        except Exception as erro:
            aviso(f"Falha ao transcrever {post.shortcode}: {erro}")
            continue
        bib.gravar_transcricao(post.shortcode, "\n\n".join(p for p in partes if p))
        feitos += 1
    return feitos
