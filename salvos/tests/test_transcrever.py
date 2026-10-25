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
