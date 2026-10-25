import pytest

from salvos.baixar import PausaInstagram, PostRemoto, sincronizar_downloads
from salvos.biblioteca import Biblioteca


def remoto(sc, tipo="imagem", midias=None):
    return PostRemoto(
        shortcode=sc,
        url=f"https://www.instagram.com/p/{sc}/",
        autor="autor",
        data=f"2026-01-01T00:00:{sc[-2:]}" if sc[-2:].isdigit() else "2026-01-01T00:00:00",
        legenda=f"legenda {sc}",
        hashtags=["tag"],
        tipo=tipo,
        midias=midias or [(f"https://cdn/{sc}.jpg", "jpg")],
    )


class FonteFalsa:
    def __init__(self, posts, falhar_em=None, erro=None):
        self.posts = posts
        self.falhar_em = falhar_em
        self.erro = erro
        self.baixadas = []

    def iterar(self):
        for i, p in enumerate(self.posts, start=1):
            if i == self.falhar_em:
                raise self.erro
            yield p

    def baixar_midia(self, url, destino):
        self.baixadas.append(url)
        destino.write_bytes(b"conteudo")


@pytest.fixture
def bib(cfg):
    return Biblioteca(cfg.biblioteca)


def rodar(bib, fonte, cfg, **kw):
    esperas = []
    r = sincronizar_downloads(bib, fonte, cfg, espera=esperas.append, **kw)
    return r, esperas


def test_baixa_novos_com_midias_e_post_json(bib, cfg):
    car = remoto("CAR01", "carrossel", [("https://cdn/a.jpg", "jpg"), ("https://cdn/b.mp4", "mp4")])
    r, _ = rodar(bib, FonteFalsa([car, remoto("IMG02")]), cfg)
    assert r.novos == 2 and r.pausado is False
    p = bib.obter("CAR01")
    assert p.tipo == "carrossel"
    assert p.arquivos == ["01.jpg", "02.mp4"]
    assert (bib.pasta("CAR01") / "02.mp4").read_bytes() == b"conteudo"
    assert p.etapas == {"baixado": True, "transcrito": False, "classificado": False}
    assert p.hashtags == ["tag"]


def test_para_apos_cinco_conhecidos_seguidos(bib, cfg):
    conhecidos = [remoto(f"K{i:02d}") for i in range(7)]
    rodar(bib, FonteFalsa(conhecidos), cfg)
    novos = [remoto(f"N{i:02d}") for i in range(3)]
    fonte = FonteFalsa(conhecidos + novos)
    r, _ = rodar(bib, fonte, cfg)
    assert r.novos == 0
    assert not any(bib.existe(p.shortcode) for p in novos)
    r, _ = rodar(bib, fonte, cfg, completo=True)
    assert r.novos == 3


def test_conhecido_isolado_nao_interrompe(bib, cfg):
    rodar(bib, FonteFalsa([remoto("K01")]), cfg)
    r, _ = rodar(bib, FonteFalsa([remoto("N01"), remoto("K01"), remoto("N02")]), cfg)
    assert r.novos == 2


def test_respeita_limite(bib, cfg):
    r, _ = rodar(bib, FonteFalsa([remoto(f"P{i:02d}") for i in range(10)]), cfg, limite=4)
    assert r.novos == 4
    assert len(bib.listar()) == 4


def test_pausa_preserva_progresso(bib, cfg):
    posts = [remoto(f"P{i:02d}") for i in range(5)]
    r, _ = rodar(bib, FonteFalsa(posts, falhar_em=3, erro=PausaInstagram("429")), cfg)
    assert r.pausado is True and r.novos == 2
    assert not [p for p in (bib.raiz / "posts").iterdir() if p.name.startswith(".tmp-")]


def test_pausa_durante_download_de_midia_nao_deixa_parcial(bib, cfg):
    class FonteQueCai(FonteFalsa):
        def baixar_midia(self, url, destino):
            if "P01" in url:
                raise PausaInstagram("429")
            super().baixar_midia(url, destino)

    r, _ = rodar(bib, FonteQueCai([remoto("P00"), remoto("P01")]), cfg)
    assert r.pausado and r.novos == 1
    assert not bib.existe("P01")
    assert sorted(p.name for p in (bib.raiz / "posts").iterdir()) == ["P00"]


def test_interrupcao_e_retomada_sem_duplicar(bib, cfg):
    posts = [remoto(f"P{i:02d}") for i in range(5)]
    with pytest.raises(KeyboardInterrupt):
        rodar(bib, FonteFalsa(posts, falhar_em=3, erro=KeyboardInterrupt()), cfg)
    r, _ = rodar(bib, FonteFalsa(posts), cfg)
    assert r.novos == 3
    codigos = [p.shortcode for p in bib.listar()]
    assert sorted(codigos) == sorted(p.shortcode for p in posts)


def test_espera_entre_posts_no_intervalo(bib, cfg):
    _, esperas = rodar(bib, FonteFalsa([remoto(f"P{i:02d}") for i in range(6)]), cfg)
    assert len(esperas) >= 5
    assert all(4 <= e <= 10 for e in esperas)


def test_imagem_ja_marcada_como_transcrita(bib, cfg):
    car = remoto("CAR01", "carrossel", [("https://cdn/a.jpg", "jpg"), ("https://cdn/b.jpg", "jpg")])
    rodar(bib, FonteFalsa([remoto("IMG01"), car]), cfg)
    assert bib.obter("IMG01").etapas["transcrito"] is True
    assert bib.obter("CAR01").etapas["transcrito"] is True
