import json

import pytest

from salvos.biblioteca import Biblioteca
from salvos.transcrever import transcrever_pendentes


@pytest.fixture
def bib(cfg, post_exemplo):
    b = Biblioteca(cfg.biblioteca)
    for sc in ("V1", "V2"):
        p = post_exemplo(shortcode=sc, tipo="carrossel", arquivos=["01.mp4", "02.jpg", "03.mp4"],
                         etapas={"baixado": True, "transcrito": False, "classificado": False})
        with b.preparar(sc) as pasta:
            for a in p.arquivos:
                (pasta / a).write_bytes(b"x")
            (pasta / "post.json").write_text(json.dumps(p.para_dict()), encoding="utf-8")
    return b


def test_transcreve_videos_pendentes(bib):
    vistos = []

    def falso(caminho):
        vistos.append(caminho.name)
        return f"texto de {caminho.name}"

    assert transcrever_pendentes(bib, falso, aviso=lambda m: None) == 2
    assert bib.transcricao("V1") == "texto de 01.mp4\n\ntexto de 03.mp4"
    assert bib.obter("V1").etapas["transcrito"] is True
    assert "02.jpg" not in vistos


def test_falha_num_post_nao_trava_os_outros(bib):
    avisos = []

    def falso(caminho):
        if caminho.parent.name == "V1":
            raise RuntimeError("arquivo corrompido")
        return "ok"

    assert transcrever_pendentes(bib, falso, aviso=avisos.append) == 1
    assert bib.obter("V2").etapas["transcrito"] is True
    assert bib.obter("V1").etapas["transcrito"] is False
    assert avisos == ["Falha ao transcrever V1: arquivo corrompido"]


def test_video_sem_fala_marca_transcrito(bib):
    transcrever_pendentes(bib, lambda c: "", aviso=lambda m: None)
    assert bib.obter("V1").etapas["transcrito"] is True
    assert bib.transcricao("V1") == ""


# --- leitura do áudio (sem o decode_audio do faster-whisper) ------------------


def _mp4(caminho, com_audio=True, com_video=False, segundos=2):
    import av
    import numpy as np

    c = av.open(str(caminho), "w")
    v = a = None
    if com_video:
        v = c.add_stream("mpeg4", rate=10)
        v.width, v.height, v.pix_fmt = 64, 64, "yuv420p"
    if com_audio:
        a = c.add_stream("aac", rate=44100)
    if v:
        for _ in range(10 * segundos):
            for pacote in v.encode(av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), np.uint8), format="rgb24")):
                c.mux(pacote)
        for pacote in v.encode(None):
            c.mux(pacote)
    if a:
        quadro = av.AudioFrame.from_ndarray(
            (np.random.randn(1, 44100 * segundos) * 0.01).astype("float32"), format="flt", layout="mono"
        )
        quadro.sample_rate = 44100
        for pacote in a.encode(quadro):
            c.mux(pacote)
        for pacote in a.encode(None):
            c.mux(pacote)
    c.close()
    return caminho


def test_decodificar_audio_16khz_mono(tmp_path):
    from salvos.transcrever import decodificar_audio

    audio = decodificar_audio(_mp4(tmp_path / "a.mp4", com_video=True))
    assert audio.dtype.name == "float32" and audio.ndim == 1
    assert 1.5 * 16000 < len(audio) < 2.5 * 16000


def test_video_sem_trilha_de_audio_vira_vazio(tmp_path):
    from salvos.transcrever import decodificar_audio

    assert len(decodificar_audio(_mp4(tmp_path / "mudo.mp4", com_audio=False, com_video=True))) == 0


def test_transcritor_whisper_passa_array_e_nao_caminho(tmp_path, monkeypatch, cfg):
    import sys
    import types

    recebidos = []

    class ModeloFalso:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio, **k):
            recebidos.append(audio)
            return iter([types.SimpleNamespace(text=" olá ")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=ModeloFalso))
    from salvos.transcrever import transcritor_whisper

    t = transcritor_whisper(cfg)
    assert t(_mp4(tmp_path / "a.mp4")) == "olá"
    assert not isinstance(recebidos[0], (str, bytes)) and len(recebidos[0]) > 0
    assert t(_mp4(tmp_path / "mudo.mp4", com_audio=False, com_video=True)) == ""
    assert len(recebidos) == 1  # vídeo mudo nem chega ao modelo
