import io
import zipfile

from salvos.exportar import exportar_md, exportar_zip, nome_arquivo


def test_md_contem_autor_link_legenda_transcricao(bib, adicionar, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA", autor="techguy", legenda="Prompts 🤖 úteis",
                                data="2026-09-12T10:00:00"), transcricao="fala do vídeo")
    md = exportar_md(bib, "IA")
    assert md.startswith("# IA\n")
    assert "· 1 posts" in md
    assert "## @techguy — 2026-09-12" in md
    assert "https://www.instagram.com/p/ABC123/" in md
    assert "### Legenda\n\nPrompts 🤖 úteis" in md
    assert "### Transcrição\n\nfala do vídeo" in md


def test_md_separa_posts_e_omite_transcricao_vazia(bib, adicionar, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A", nicho="IA", data="2026-02-01"))
    adicionar(bib, post_exemplo(shortcode="B", nicho="IA", data="2026-01-01"))
    md = exportar_md(bib, "IA")
    assert "### Transcrição" not in md
    assert md.count("\n---\n") == 1


def test_zip_tem_md_e_midias(bib, adicionar, post_exemplo):
    adicionar(bib, post_exemplo(shortcode="A", nicho="Saúde/Bem-estar", arquivos=["01.jpg", "02.mp4"]))
    adicionar(bib, post_exemplo(shortcode="B", nicho="IA"))
    buf = io.BytesIO()
    exportar_zip(bib, "Saúde/Bem-estar", buf)
    nomes = set(zipfile.ZipFile(buf).namelist())
    assert {"Saúde-Bem-estar.md", "posts/A/01.jpg", "posts/A/02.mp4", "posts/A/post.json"} <= nomes
    assert not any(n.startswith("posts/B/") for n in nomes)


def test_nome_arquivo_windows():
    assert nome_arquivo("Saúde/Bem-estar") == "Saúde-Bem-estar"
    assert nome_arquivo("IA: ferramentas") == "IA- ferramentas"
    assert nome_arquivo("CON") == "_CON"
    assert nome_arquivo("com1") == "_com1"
    assert nome_arquivo("Estudo.") == "Estudo"
    assert nome_arquivo("  ") == "nicho"
    assert nome_arquivo('a<b>c"d|e?f*g\\h') == "a-b-c-d-e-f-g-h"
