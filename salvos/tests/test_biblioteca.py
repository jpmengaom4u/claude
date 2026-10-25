import json

import pytest

from salvos.biblioteca import Biblioteca
from salvos.modelos import Nicho


@pytest.fixture
def bib(tmp_path):
    return Biblioteca(tmp_path / "Salvos")


def adicionar(bib, post):
    with bib.preparar(post.shortcode) as pasta:
        for nome in post.arquivos:
            (pasta / nome).write_bytes(b"x")
        (pasta / "post.json").write_text(json.dumps(post.para_dict(), ensure_ascii=False), encoding="utf-8")


def test_preparar_publica_so_ao_final(bib, post_exemplo):
    p = post_exemplo()
    with bib.preparar(p.shortcode) as pasta:
        (pasta / "post.json").write_text(json.dumps(p.para_dict()), encoding="utf-8")
        assert not bib.existe(p.shortcode)
    assert bib.existe(p.shortcode)
    assert bib.obter(p.shortcode) == p


def test_preparar_com_erro_nao_deixa_rastro(bib, post_exemplo):
    p = post_exemplo()
    with pytest.raises(RuntimeError):
        with bib.preparar(p.shortcode) as pasta:
            (pasta / "01.jpg").write_bytes(b"x")
            raise RuntimeError("queda")
    assert not bib.existe(p.shortcode)
    assert list((bib.raiz / "posts").iterdir()) == []


def test_listar_filtra_por_nicho_e_revisar(bib, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA", data="2026-01-01"))
    adicionar(bib, post_exemplo(shortcode="B", nicho="IA", revisar=True, data="2026-02-01"))
    adicionar(bib, post_exemplo(shortcode="C", nicho="Saúde"))
    assert [p.shortcode for p in bib.listar(nicho="IA")] == ["B", "A"]
    assert [p.shortcode for p in bib.listar(revisar=True)] == ["B"]
    assert len(bib.listar()) == 3


def test_busca_encontra_legenda_e_transcricao(bib, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A", legenda="dicas de produtividade"))
    adicionar(bib, post_exemplo(shortcode="B", legenda="vídeo", tipo="video", arquivos=["01.mp4"]))
    bib.gravar_transcricao("B", "hoje vamos falar de embeddings")
    assert [p.shortcode for p in bib.listar(q="embeddings")] == ["B"]
    assert [p.shortcode for p in bib.listar(q="produtividade")] == ["A"]


def test_busca_com_caracteres_especiais(bib, post_exemplo):
    adicionar(bib, post_exemplo(legenda="aprenda c++ hoje"))
    for s in ['"', "c++", "-ia", "*", "a OR", "", "   "]:
        bib.listar(q=s)


def test_emoji_ida_e_volta(bib, post_exemplo):
    adicionar(bib, post_exemplo(legenda="Saúde 💪 já"))
    assert bib.obter("ABC123").legenda == "Saúde 💪 já"
    bruto = (bib.pasta("ABC123") / "post.json").read_bytes().decode("utf-8")
    assert "Saúde 💪 já" in bruto


def test_reindexar_reproduz_o_indice(bib, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA"))
    adicionar(bib, post_exemplo(shortcode="B", tipo="video", arquivos=["01.mp4"]))
    bib.gravar_transcricao("B", "palavra rara xilofone")
    antes = ([p.shortcode for p in bib.listar()], bib.contagem())
    bib.fechar()
    (bib.raiz / "biblioteca.db").unlink()
    novo = Biblioteca(bib.raiz)
    assert novo.reindexar() == 2
    assert ([p.shortcode for p in novo.listar()], novo.contagem()) == antes
    assert [p.shortcode for p in novo.listar(q="xilofone")] == ["B"]


def test_apagar_nicho_move_para_outros(bib, post_exemplo):
    bib.salvar_nichos([Nicho("IA", "ia"), Nicho("Saúde", "s"), Nicho("Outros", "o")])
    adicionar(bib, post_exemplo(shortcode="A", nicho="Saúde"))
    bib.apagar_nicho("Saúde")
    assert bib.obter("A").nicho == "Outros"
    assert [n.nome for n in bib.nichos()] == ["IA", "Outros"]
    assert bib.contagem() == {"Outros": 1}


def test_juntar_nichos(bib, post_exemplo):
    bib.salvar_nichos([Nicho("IA", "ia"), Nicho("ChatGPT", "c"), Nicho("Outros", "o")])
    adicionar(bib, post_exemplo(shortcode="A", nicho="ChatGPT"))
    adicionar(bib, post_exemplo(shortcode="B", nicho="IA"))
    bib.juntar_nichos("ChatGPT", "IA")
    assert bib.contagem() == {"IA": 2}
    assert [n.nome for n in bib.nichos()] == ["IA", "Outros"]


def test_renomear_nicho(bib, post_exemplo):
    bib.salvar_nichos([Nicho("IA", "ia"), Nicho("Outros", "o")])
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA"))
    bib.renomear_nicho("IA", "Inteligência Artificial")
    assert bib.obter("A").nicho == "Inteligência Artificial"
    assert bib.nichos()[0].nome == "Inteligência Artificial"


def test_nichos_none_sem_arquivo(bib):
    assert bib.nichos() is None


def test_pendentes_ignora_indisponiveis(bib, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A"))
    adicionar(bib, post_exemplo(shortcode="B", indisponivel=True))
    assert [p.shortcode for p in bib.pendentes("classificado")] == ["A"]


def test_contagem_sem_classificacao(bib, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A"))
    assert bib.contagem() == {"Sem classificação": 1}


def test_preparar_tenta_de_novo_se_windows_travar_rename(bib, post_exemplo, monkeypatch):
    from pathlib import Path

    original = Path.rename
    tentativas = []

    def rename_travado(self, alvo):
        tentativas.append(1)
        if len(tentativas) < 3:
            raise PermissionError("[WinError 5] Acesso negado")
        return original(self, alvo)

    monkeypatch.setattr(Path, "rename", rename_travado)
    monkeypatch.setattr("salvos.biblioteca.time.sleep", lambda s: None)
    adicionar(bib, post_exemplo())
    assert bib.existe("ABC123")
    assert len(tentativas) == 3


def test_nichos_toml_com_bom(bib):
    (bib.raiz / "nichos.toml").write_bytes('﻿[[nicho]]\nnome = "IA"\ndescricao = "x"\n'.encode("utf-8"))
    assert [n.nome for n in bib.nichos()] == ["IA"]


def test_estado_padrao_e_gravacao(bib):
    assert bib.estado() == {"varredura_completa": False}
    bib.salvar_estado({"varredura_completa": True})
    assert bib.estado()["varredura_completa"] is True
