import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from salvos.modelos import Nicho
from salvos.web.app import criar_app


@pytest.fixture
def cliente(bib, adicionar, post_exemplo):
    bib.salvar_nichos([Nicho("IA", "ia"), Nicho("Saúde/Bem-estar", "s"), Nicho("Outros", "o")])
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA", legenda="prompts úteis", data="2026-02-01"))
    adicionar(bib, post_exemplo(shortcode="B", nicho="IA", legenda="agentes", data="2026-01-01",
                                tipo="video", arquivos=["01.mp4"]), transcricao="falando de embeddings")
    adicionar(bib, post_exemplo(shortcode="C", nicho="Saúde/Bem-estar", revisar=True))
    adicionar(bib, post_exemplo(shortcode="D"))
    return TestClient(criar_app(bib))


def test_pagina_inicial(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_lista_nichos_com_total(cliente):
    r = cliente.get("/api/nichos").json()
    assert [(n["nome"], n["total"]) for n in r] == [
        ("IA", 2), ("Saúde/Bem-estar", 1), ("Outros", 0), ("Sem classificação", 1)
    ]


def test_filtra_posts_por_nicho_e_busca(cliente):
    assert [p["shortcode"] for p in cliente.get("/api/posts", params={"nicho": "IA"}).json()] == ["A", "B"]
    assert [p["shortcode"] for p in cliente.get("/api/posts", params={"q": "embeddings"}).json()] == ["B"]
    assert [p["shortcode"] for p in cliente.get("/api/posts", params={"revisar": "true"}).json()] == ["C"]
    assert cliente.get("/api/posts", params={"nicho": "IA"}).json()[1]["capa"] == "01.mp4"


def test_busca_com_aspas_nao_da_500(cliente):
    for q in ['"', "c++", "-", "*"]:
        assert cliente.get("/api/posts", params={"q": q}).status_code == 200


def test_detalhe_do_post(cliente):
    r = cliente.get("/api/posts/B").json()
    assert r["transcricao"] == "falando de embeddings"
    assert cliente.get("/api/posts/ZZZ").status_code == 404


def test_mover_post_marca_manual(cliente, bib):
    r = cliente.patch("/api/posts/C", json={"nicho": "IA"})
    assert r.status_code == 200
    p = bib.obter("C")
    assert (p.nicho, p.nicho_manual, p.revisar) == ("IA", True, False)


def test_mover_para_nicho_inexistente_400(cliente):
    assert cliente.patch("/api/posts/C", json={"nicho": "Nada"}).status_code == 400


def test_criar_renomear_juntar_apagar_nicho(cliente, bib):
    assert cliente.post("/api/nichos", json={"nome": "Finanças", "descricao": "dinheiro"}).status_code == 201
    assert cliente.post("/api/nichos", json={"nome": "Finanças", "descricao": "x"}).status_code == 409
    assert cliente.patch("/api/nichos/IA", json={"novo_nome": "Inteligência Artificial"}).status_code == 200
    assert bib.obter("A").nicho == "Inteligência Artificial"
    assert cliente.patch("/api/nichos/Finanças", json={"descricao": "grana"}).status_code == 200
    assert [n.descricao for n in bib.nichos() if n.nome == "Finanças"] == ["grana"]
    assert cliente.patch("/api/nichos/Saúde%2FBem-estar", json={"juntar_em": "Inteligência Artificial"}).status_code == 200
    assert bib.obter("C").nicho == "Inteligência Artificial"
    assert cliente.delete("/api/nichos/Inteligência Artificial").status_code == 200
    assert bib.obter("A").nicho == "Outros"
    assert cliente.delete("/api/nichos/Outros").status_code == 400
    assert cliente.delete("/api/nichos/Inexistente").status_code == 404


def test_exportar_md_e_zip(cliente):
    r = cliente.get("/api/exportar/Saúde%2FBem-estar.md")
    assert r.status_code == 200
    assert "Sa%C3%BAde-Bem-estar.md" in r.headers["content-disposition"]
    assert r.text.startswith("# Saúde/Bem-estar")
    r = cliente.get("/api/exportar/IA.zip")
    assert r.status_code == 200
    assert "IA.md" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()


def test_midia(cliente):
    assert cliente.get("/midia/B/01.mp4").content == b"x"
    assert cliente.get("/midia/B/99.mp4").status_code == 404


def test_midia_bloqueia_path_traversal(cliente):
    assert cliente.get("/midia/B/..%2F..%2Fbiblioteca.db").status_code == 404
    assert cliente.get("/midia/..%2F..%2F/biblioteca.db").status_code == 404
    assert cliente.get("/midia/B/..%5C..%5Cbiblioteca.db").status_code == 404


def test_nicho_fora_do_toml_aparece_na_lista(cliente, bib, adicionar, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="Z", nicho="Antigo"))
    nomes = {n["nome"]: n["total"] for n in cliente.get("/api/nichos").json()}
    assert nomes["Antigo"] == 1
    assert cliente.get("/api/exportar/Antigo.md").status_code == 200


def test_criar_nicho_garante_outros(bib, tmp_path):
    from salvos.biblioteca import Biblioteca

    b = Biblioteca(tmp_path / "nova")
    c = TestClient(criar_app(b))
    assert c.post("/api/nichos", json={"nome": "IA", "descricao": "ia"}).status_code == 201
    assert [n.nome for n in b.nichos()] == ["IA", "Outros"]
