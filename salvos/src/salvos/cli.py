"""Linha de comando: salvos login | sync | nichos | abrir | reindexar."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import tomllib
import webbrowser

import uvicorn

from .baixar import FonteInstaloader, SessaoInvalida, sincronizar_downloads
from .biblioteca import OUTROS, Biblioteca, gravar_nichos_toml, ler_nichos_toml
from .classificar import classificar_pendentes
from .config import Config, carregar_config, chave_openrouter
from .ia import ClienteIA, ErroFatalIA, ErroIA
from .modelos import Nicho
from .nichos import propor_nichos, revisar_nichos
from .transcrever import transcrever_pendentes, transcritor_whisper
from .web.app import criar_app

MSG_PAUSA = "O Instagram pediu uma pausa. O progresso foi salvo; tente de novo daqui a algumas horas."
MSG_SESSAO = "Sessão do Instagram inválida ou expirada. Rode: salvos login"
MSG_SEM_NICHOS = "Rode `salvos nichos` para definir seus nichos."
MSG_REVISAR = "Há {n} posts em Outros. Rode `salvos nichos --revisar` para sugerir nichos novos."
LIMIAR_OUTROS = 10


class _Linha:
    """Contador que se reescreve na mesma linha do terminal."""

    def __init__(self):
        self._largura = 0

    def atualizar(self, texto: str) -> None:
        print("\r" + texto.ljust(self._largura), end="", flush=True)
        self._largura = len(texto)

    def aviso(self, texto: str) -> None:
        self.fechar()
        print(texto)

    def fechar(self) -> None:
        if self._largura:
            print()
            self._largura = 0


def _usuario(cfg: Config) -> str:
    arq = cfg.pasta_app / "usuario.txt"
    if not arq.exists():
        raise SessaoInvalida("Nenhum usuário salvo.")
    return arq.read_text(encoding="utf-8-sig").strip().lstrip("@").lower()


def _ia(cfg: Config) -> ClienteIA:
    return ClienteIA(chave_openrouter(cfg))


def _classificar(bib: Biblioteca, cfg: Config) -> tuple[int, int]:
    """Classifica os pendentes e imprime os avisos. Retorna (classificados, código de saída)."""
    linha = _Linha()
    r = classificar_pendentes(
        bib, _ia(cfg), cfg.modelo_classificacao, cfg.tamanho_lote, cfg.modelos_reserva, progresso=linha.atualizar
    )
    linha.fechar()
    if r.sem_nichos:
        print(MSG_SEM_NICHOS)
        return 0, 0
    if r.parado_por:
        print(r.parado_por)
        return r.classificados, 1
    if r.em_outros >= LIMIAR_OUTROS:
        print(MSG_REVISAR.format(n=r.em_outros))
    return r.classificados, 0


def cmd_login(cfg: Config, args) -> int:
    from .login import importar_firefox, login_interativo

    try:
        if args.interativo:
            usuario = login_interativo(cfg, args.interativo)
        else:
            usuario = importar_firefox(cfg)
    except SessaoInvalida as e:
        print(e)
        print("Faça login no Instagram pelo Firefox e tente de novo, ou use: salvos login --interativo SEU_USUARIO")
        return 1
    except Exception as e:  # erros do Instaloader (senha errada, 2FA, rede)
        print(f"Não foi possível entrar: {e}")
        return 1
    print(f"Sessão salva para @{usuario}.")
    return 0


def cmd_sync(cfg: Config, args) -> int:
    bib = Biblioteca(cfg.biblioteca)
    novos = 0
    try:
        fonte = FonteInstaloader(cfg, _usuario(cfg))
        print("Baixando salvos…")
        linha = _Linha()
        try:
            r = sincronizar_downloads(
                bib, fonte, cfg, completo=args.completo, limite=args.limite,
                aviso=linha.aviso, progresso=linha.atualizar,
            )
        finally:
            linha.fechar()
        novos = r.novos
        if r.pausado:
            print(MSG_PAUSA)
    except SessaoInvalida:
        print(MSG_SESSAO)
        return 1
    except Exception as e:
        # Erro inesperado na listagem: o que já foi baixado ainda é processado.
        print(f"O download parou por um erro: {e}")

    transcritos = 0
    if bib.pendentes("transcrito"):
        print("Transcrevendo vídeos… (na primeira vez, o modelo do Whisper é baixado)")
        try:
            linha = _Linha()
            try:
                transcritos = transcrever_pendentes(
                    bib, transcritor_whisper(cfg), aviso=linha.aviso, progresso=linha.atualizar
                )
            finally:
                linha.fechar()
        except Exception as e:
            print(f"Não foi possível transcrever agora ({e}). Os vídeos ficam para o próximo sync.")

    print("Classificando…")
    classificados, codigo = _classificar(bib, cfg)
    print(f"Novos: {novos} · Transcritos: {transcritos} · Classificados: {classificados}")
    return codigo


def _mostrar(nichos: list[Nicho]) -> None:
    for i, n in enumerate(nichos, start=1):
        print(f"  {i}. {n.nome} — {n.descricao}")


def _abrir_editor(arquivo) -> None:
    if os.name == "nt":
        subprocess.call(["notepad.exe", str(arquivo)])
    elif os.environ.get("EDITOR"):
        subprocess.call([os.environ["EDITOR"], str(arquivo)])


def _editar(bib: Biblioteca, proposta: list[Nicho]) -> list[Nicho]:
    arquivo = bib.raiz / "nichos-proposta.toml"
    gravar_nichos_toml(arquivo, proposta)
    while True:
        _abrir_editor(arquivo)
        print(f"Edite o arquivo {arquivo}, salve e pressione Enter aqui.")
        input()
        try:
            editados = ler_nichos_toml(arquivo) or []
        except (tomllib.TOMLDecodeError, KeyError) as e:
            print(f"Erro no arquivo: {e}. Corrija e tente de novo.")
            continue
        arquivo.unlink(missing_ok=True)
        return editados


def cmd_nichos(cfg: Config, args) -> int:
    bib = Biblioteca(cfg.biblioteca)
    if not bib.listar():
        print("Nenhum post baixado ainda. Rode primeiro: salvos sync --limite 5")
        return 1
    ia = _ia(cfg)
    existentes = bib.nichos() or []
    try:
        while True:
            print("Pedindo à IA uma proposta de nichos…")
            if args.revisar:
                proposta = revisar_nichos(bib, ia, cfg.modelo_nichos, cfg.modelos_reserva)
            else:
                proposta = propor_nichos(bib, ia, cfg.modelo_nichos, reservas=cfg.modelos_reserva)
            _mostrar(proposta)
            escolha = input("[a]ceitar / [e]ditar / [n]ova proposta: ").strip().lower()
            if escolha.startswith("e"):
                proposta = _editar(bib, proposta)
                _mostrar(proposta)
                escolha = "a"
            if escolha.startswith("a"):
                break
    except ErroIA as e:
        print(e)
        return 1

    if args.revisar:
        sem_outros = [n for n in existentes if n.nome != OUTROS]
        outros = [n for n in existentes if n.nome == OUTROS] or [Nicho(OUTROS, "Posts que não se encaixam nos outros nichos.")]
        final = sem_outros + [n for n in proposta if n.nome != OUTROS] + outros
        # Os posts em Outros voltam para a fila, para serem reavaliados com os nichos novos.
        for post in bib.listar(nicho=OUTROS):
            if not post.nicho_manual:
                post.etapas["classificado"] = False
                bib.salvar(post)
    else:
        final = proposta
        # Posts em nichos que deixaram de existir voltam para a fila.
        nomes = {n.nome for n in final} | {OUTROS}
        for post in bib.listar():
            if post.nicho and post.nicho not in nomes and not post.nicho_manual:
                post.etapas["classificado"] = False
                bib.salvar(post)
    if not any(n.nome == OUTROS for n in final):
        final.append(Nicho(OUTROS, "Posts que não se encaixam nos outros nichos."))
    bib.salvar_nichos(final)
    print(f"Nichos salvos ({len(final)}).")

    if bib.pendentes("classificado") and input("Classificar os posts agora? [S/n] ").strip().lower() in ("", "s", "sim"):
        classificados, codigo = _classificar(bib, cfg)
        print(f"Classificados: {classificados}")
        return codigo
    return 0


def cmd_abrir(cfg: Config, args) -> int:
    bib = Biblioteca(cfg.biblioteca)
    porta = args.porta or cfg.porta
    url = f"http://127.0.0.1:{porta}"
    print(f"Abrindo {url} (Ctrl+C para encerrar)")
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(criar_app(bib), host="127.0.0.1", port=porta, log_level="warning")
    return 0


def cmd_reindexar(cfg: Config, args) -> int:
    print(f"Índice recriado: {Biblioteca(cfg.biblioteca).reindexar()} posts.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="salvos", description="Organiza seus posts salvos do Instagram por nicho.")
    sub = p.add_subparsers(dest="comando", required=True)
    s = sub.add_parser("login", help="importa a sessão do Instagram do Firefox")
    s.add_argument("--interativo", metavar="USUARIO", help="faz login digitando usuário e senha no terminal")
    s = sub.add_parser("sync", help="baixa, transcreve e classifica os salvos novos")
    s.add_argument("--limite", type=int, help="máximo de posts novos nesta execução")
    s.add_argument("--completo", action="store_true", help="varre todos os salvos, não só os mais recentes")
    s = sub.add_parser("nichos", help="propõe e salva a lista de nichos")
    s.add_argument("--revisar", action="store_true", help="sugere nichos novos a partir dos posts em Outros")
    s = sub.add_parser("abrir", help="abre a página local")
    s.add_argument("--porta", type=int)
    sub.add_parser("reindexar", help="recria o índice a partir das pastas")
    args = p.parse_args(argv)

    cfg = carregar_config()
    cfg.biblioteca.mkdir(parents=True, exist_ok=True)
    comandos = {
        "login": cmd_login, "sync": cmd_sync, "nichos": cmd_nichos,
        "abrir": cmd_abrir, "reindexar": cmd_reindexar,
    }
    try:
        return comandos[args.comando](cfg, args)
    except ErroFatalIA as e:
        print(e)
        return 1
    except KeyboardInterrupt:
        print("\nInterrompido. O progresso foi salvo.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
