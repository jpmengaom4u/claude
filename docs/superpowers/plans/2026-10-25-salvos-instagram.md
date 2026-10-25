# Salvos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ferramenta local (Windows) que baixa os posts salvos do Instagram, transcreve vídeos, agrupa por nicho com IA e mostra tudo numa página local com exportação por nicho.

**Architecture:** Pacote Python `salvos` com CLI (`argparse`). Os dados vivem em pastas por post (`post.json` + mídias + `transcricao.txt`) e num índice SQLite/FTS5 derivado; `biblioteca.py` é a única porta de acesso. Instaloader, faster-whisper e OpenRouter ficam atrás de interfaces injetáveis, para os testes rodarem sem rede. A página é FastAPI + HTML/JS puro.

**Tech Stack:** Python 3.11+, instaloader, faster-whisper, httpx, fastapi, uvicorn, tomli-w, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-salvos-instagram-design.md`

## Global Constraints

- Python 3.11+; alvo principal Windows (caminhos via `pathlib`, nunca separadores fixos).
- Projeto em `salvos/` na raiz do repo: `salvos/pyproject.toml`, código em `salvos/src/salvos/`, testes em `salvos/tests/`.
- Todo arquivo de texto é lido e gravado com `encoding="utf-8"`; JSON com `ensure_ascii=False`.
- Biblioteca padrão `%USERPROFILE%\Salvos` (`Path.home() / "Salvos"`); a variável `SALVOS_BIBLIOTECA` sobrepõe.
- Pasta do app (sessão, `.env`): `%APPDATA%\salvos` (`Path(os.environ["APPDATA"]) / "salvos"`, com fallback `Path.home() / ".salvos"` fora do Windows).
- A chave vem só de `OPENROUTER_API_KEY` ou de `<pasta do app>/.env`; nunca é impressa, gravada em log ou lida do toml.
- Servidor sempre em `127.0.0.1`, porta padrão `8000`.
- Ritmo: pausa aleatória de 4 a 10 s entre posts; limite padrão de 150 posts por `sync`; parada incremental após 5 posts conhecidos seguidos.
- Whisper: modelo `small`, `device="cpu"`, `compute_type="int8"`.
- Classificação: `typesafe/jev-1.13` em `https://openrouter.ai/api/alpha/decisions`; confiança < 0,5 marca `revisar = true`; `state` cortado em 4.000 caracteres.
- Descoberta de nichos: de 5 a 15 nichos + "Outros"; resumo por post = autor + 300 primeiros caracteres de legenda e de transcrição.
- Nicho padrão e de escape: `"Outros"`.
- Mensagens ao usuário em português.
- Testes nunca acessam a rede.

## Review Focus

1. **Emoji e acentos no Windows**: legendas e autores com emoji ou acento precisam sobreviver ao ciclo gravar → ler → exportar, e o terminal cp1252 do Windows não pode quebrar o `print` (a CLI reconfigura `stdout` para UTF-8). Teste na Task 2 e na Task 7.
2. **Nome de nicho com caracteres proibidos em arquivo no Windows** (`Saúde/Bem-estar`, `IA: ferramentas`): a exportação gera nome de arquivo válido. Teste na Task 7.
3. **Busca com caracteres especiais** (`"`, `-`, `c++`, `*`): a busca não pode dar erro 500; a consulta é escapada para o FTS5. Teste na Task 2.
4. **`sync` antes de `salvos nichos`**: sem `nichos.toml`, a classificação é pulada com a mensagem "Rode `salvos nichos` para definir seus nichos.", e as outras etapas seguem. Teste na Task 6.
5. **Post de imagem sem legenda**: o `state` enviado ao Jev nunca é vazio (contém ao menos o autor) e o post é classificado. Teste na Task 6.

---

## File Structure

```
salvos/
  pyproject.toml
  README.md
  src/salvos/
    __init__.py
    config.py        # Config + carregar_config + chave_openrouter
    modelos.py       # dataclasses Post, Nicho
    biblioteca.py    # pastas, post.json, nichos.toml, índice SQLite/FTS5
    ia.py            # cliente OpenRouter (chat + decisions)
    baixar.py        # FonteSalvos, FonteInstaloader, sincronizar_downloads
    login.py         # importar sessão do Firefox / login interativo
    transcrever.py   # transcrever_pendentes
    nichos.py        # propor_nichos, revisar_nichos
    classificar.py   # classificar_pendentes
    exportar.py      # exportar_md, exportar_zip, nome_arquivo
    web/
      app.py         # criar_app(biblioteca) -> FastAPI
      static/index.html, app.js, estilo.css
    cli.py           # main()
  tests/
    conftest.py      # fixtures: biblioteca temporária, posts de exemplo, fakes
    test_config.py, test_biblioteca.py, test_ia.py, test_baixar.py,
    test_transcrever.py, test_nichos.py, test_classificar.py,
    test_exportar.py, test_web.py, test_cli.py
```

Raiz do repo: `.gitignore` com `Salvos/`, `*.db`, `.env`, `session-*`, `__pycache__/`, `.venv/`.

---

### Task 1: Projeto, configuração e modelos

**Files:**
- Create: `salvos/pyproject.toml`, `salvos/src/salvos/__init__.py`, `salvos/src/salvos/config.py`, `salvos/src/salvos/modelos.py`, `salvos/tests/conftest.py`, `salvos/tests/test_config.py`, `.gitignore`

**Interfaces:**
- Produces:
  - `@dataclass Config`: `biblioteca: Path`, `pasta_app: Path`, `modelo_nichos: str`, `modelo_classificacao: str = "typesafe/jev-1.13"`, `modelo_whisper: str = "small"`, `limite: int = 150`, `pausa_min: float = 4`, `pausa_max: float = 10`, `parada_conhecidos: int = 5`, `porta: int = 8000`
  - `carregar_config() -> Config`: biblioteca de `SALVOS_BIBLIOTECA` ou `Path.home()/"Salvos"`; sobrepõe os campos com `<biblioteca>/salvos.toml`, se existir.
  - `chave_openrouter(cfg: Config) -> str | None`: `OPENROUTER_API_KEY`, senão a linha `OPENROUTER_API_KEY=...` de `cfg.pasta_app/".env"`, senão `None`.
  - `@dataclass Post`: `shortcode: str`, `url: str`, `autor: str`, `data: str` (ISO 8601), `legenda: str`, `hashtags: list[str]`, `tipo: Literal["imagem","carrossel","video"]`, `arquivos: list[str]` (nomes relativos à pasta do post), `etapas: dict[str,bool]` (chaves `baixado`, `transcrito`, `classificado`), `nicho: str | None = None`, `nicho_manual: bool = False`, `revisar: bool = False`, `confianca: float | None = None`, `indisponivel: bool = False`; métodos `para_dict() -> dict` e `@classmethod de_dict(d) -> Post`. A transcrição não faz parte do `Post`: fica em `transcricao.txt`.
  - `@dataclass Nicho`: `nome: str`, `descricao: str`.
  - Fixture `post_exemplo(**alteracoes) -> Post` em `conftest.py` (factory) e fixture `cfg(tmp_path, monkeypatch) -> Config` com a biblioteca em `tmp_path`.

- [ ] **Step 1:** Criar `pyproject.toml` (setuptools, layout `src`, `requires-python = ">=3.11"`, dependências `instaloader`, `faster-whisper`, `httpx`, `fastapi`, `uvicorn`, `tomli-w`; extra `dev = ["pytest"]`; script `salvos = "salvos.cli:main"`; `package-data` incluindo `web/static/*`) e o `.gitignore` da raiz.
- [ ] **Step 2:** Confirmar no OpenRouter o slug atual do modelo Claude Sonnet mais recente (`GET https://openrouter.ai/api/v1/models`, filtrar `anthropic/claude-sonnet`) e usá-lo como padrão de `modelo_nichos`.
- [ ] **Step 3: Testes que falham** em `test_config.py`:
  - `test_biblioteca_padrao_e_variavel`: sem `SALVOS_BIBLIOTECA`, `carregar_config().biblioteca == Path.home()/"Salvos"`; com ela, é o valor dado.
  - `test_toml_sobrepoe`: `salvos.toml` com `limite = 20` e `porta = 9000` → `cfg.limite == 20`, `cfg.porta == 9000`, demais campos nos padrões.
  - `test_chave_env_tem_prioridade` e `test_chave_do_arquivo_env`: o `.env` na `pasta_app` é lido quando a variável não existe; `None` quando nenhum dos dois existe.
  - `test_post_ida_e_volta`: `Post.de_dict(p.para_dict()) == p` para um post com legenda `"Olá 🤖 ação"`.
- [ ] **Step 4:** `cd salvos && pip install -e .[dev] && pytest tests/test_config.py -v` → FAIL (módulo não existe).
- [ ] **Step 5:** Implementar `config.py` e `modelos.py`.
- [ ] **Step 6:** `pytest tests/test_config.py -v` → PASS.
- [ ] **Step 7:** Commit `feat(salvos): projeto, configuração e modelos`.

---

### Task 2: Biblioteca (pastas + índice SQLite/FTS5)

**Files:**
- Create: `salvos/src/salvos/biblioteca.py`, `salvos/tests/test_biblioteca.py`

**Interfaces:**
- Consumes: `Config`, `Post`, `Nicho` (Task 1).
- Produces: `class Biblioteca(raiz: Path)`, que cria `raiz/"posts"` e `raiz/"biblioteca.db"`:
  - `existe(shortcode) -> bool`
  - `pasta(shortcode) -> Path`
  - `@contextmanager preparar(shortcode) -> Iterator[Path]`: entrega `raiz/"posts"/f".tmp-{shortcode}"` vazia; ao sair sem exceção, a pasta deve conter `post.json` e é renomeada para `posts/<shortcode>` e indexada; com exceção, é apagada.
  - `salvar(post: Post) -> None`: grava `post.json` e atualiza o índice.
  - `obter(shortcode) -> Post`, `transcricao(shortcode) -> str` (`""` se não houver)
  - `gravar_transcricao(shortcode, texto) -> None`: grava o arquivo, marca `etapas["transcrito"]` e reindexa o post.
  - `listar(nicho: str | None = None, q: str | None = None, revisar: bool = False) -> list[Post]`, por `data` decrescente.
  - `pendentes(etapa: str) -> list[Post]`: posts com `etapas[etapa] is False` e `indisponivel is False`.
  - `contagem() -> dict[str, int]`: por nicho; posts sem nicho em `"Sem classificação"`.
  - `nichos() -> list[Nicho] | None` (`None` se `nichos.toml` não existe) e `salvar_nichos(lista: list[Nicho])`. Formato do toml: `[[nicho]]` com `nome` e `descricao`.
  - `renomear_nicho(antigo, novo)`, `juntar_nichos(origem, destino)`, `apagar_nicho(nome)`: atualizam `nichos.toml` e todos os posts afetados; apagar move os posts para `"Outros"`.
  - `reindexar() -> int`: apaga e recria o índice a partir das pastas (ignora `.tmp-*`); retorna o número de posts.
- Índice: tabela `posts` (colunas do `Post` + `transcricao`) e tabela virtual FTS5 `busca(shortcode UNINDEXED, autor, legenda, transcricao)`. A consulta de busca é escapada: cada termo vira `"termo"` (aspas internas duplicadas), unidos por espaço.

- [ ] **Step 1: Testes que falham** em `test_biblioteca.py`:
  - `test_preparar_publica_so_ao_final`: dentro do `with`, `existe()` é `False`; depois, `True` e `obter()` devolve o post.
  - `test_preparar_com_erro_nao_deixa_rastro`: exceção dentro do `with` → nenhuma pasta `.tmp-*` nem `posts/<shortcode>`; `existe()` é `False`.
  - `test_listar_filtra_por_nicho_e_revisar`
  - `test_busca_encontra_legenda_e_transcricao`: termo só na transcrição é encontrado; termo só na legenda também.
  - `test_busca_com_caracteres_especiais`: `listar(q=s)` para `s` em `['"', 'c++', '-ia', '*', "a OR"]` não levanta exceção.
  - `test_emoji_ida_e_volta`: `obter()` devolve a legenda `"Saúde 💪 já"` intacta e o `post.json` está em UTF-8.
  - `test_reindexar_reproduz_o_indice`: depois de apagar `biblioteca.db`, `reindexar()` retorna o total e `listar()`/`contagem()` são iguais aos de antes.
  - `test_apagar_nicho_move_para_outros` e `test_juntar_nichos`: contagens e `nichos()` refletem a operação.
  - `test_nichos_none_sem_arquivo`
- [ ] **Step 2:** `pytest tests/test_biblioteca.py -v` → FAIL.
- [ ] **Step 3:** Implementar `biblioteca.py`.
- [ ] **Step 4:** `pytest tests/test_biblioteca.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(salvos): biblioteca com índice e busca`.

---

### Task 3: Cliente OpenRouter

**Files:**
- Create: `salvos/src/salvos/ia.py`, `salvos/tests/test_ia.py`

**Interfaces:**
- Consumes: `chave_openrouter` (Task 1).
- Produces:
  - `class ErroIA(Exception)` (temporário: esgotou as tentativas) e `class ErroFatalIA(ErroIA)` (401/402; a mensagem diz "Chave da OpenRouter inválida" ou "Sem créditos na OpenRouter").
  - `class ClienteIA(chave: str | None, http: httpx.Client | None = None, espera: Callable[[float], None] = time.sleep)`
  - `chat(modelo: str, mensagens: list[dict]) -> str`: `POST https://openrouter.ai/api/v1/chat/completions`; retorna `choices[0].message.content`.
  - `escolher(state: str, opcoes: dict[str, str], instrucoes: str, modelo: str = "typesafe/jev-1.13") -> tuple[str, float]`: `POST https://openrouter.ai/api/alpha/decisions` com `{"model", "state", "questions": {"nicho": {"type": "choice", "instructions", "criteria": opcoes}}}`; retorna `(answers["nicho"]["choice"], answers["nicho"]["confidence"])`.
  - Os dois métodos: header `Authorization: Bearer <chave>` só se houver chave; 429/5xx/erro de rede → até 3 tentativas com espera de 2, 4 e 8 s, depois `ErroIA`; 401/402 → `ErroFatalIA` na hora.

- [ ] **Step 1: Testes que falham** em `test_ia.py`, com `httpx.MockTransport`:
  - `test_escolher_envia_pergunta_choice_e_le_resposta`: confere o corpo enviado e o retorno `("IA", 0.91)`.
  - `test_chat_retorna_conteudo`
  - `test_retry_em_429_depois_sucesso`: duas respostas 429 e depois 200 → sucesso; `espera` chamada com `[2, 4]`.
  - `test_erro_apos_tres_tentativas`: só 500 → `ErroIA`.
  - `test_401_e_402_sao_fatais_sem_retry`: `ErroFatalIA`, uma única requisição.
  - `test_chave_nunca_aparece_na_mensagem_de_erro`: `str(erro)` não contém a chave.
- [ ] **Step 2:** `pytest tests/test_ia.py -v` → FAIL.
- [ ] **Step 3:** Implementar `ia.py`.
- [ ] **Step 4:** `pytest tests/test_ia.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(salvos): cliente OpenRouter com retry`.

---

### Task 4: Baixar salvos (Instaloader) e login

**Files:**
- Create: `salvos/src/salvos/baixar.py`, `salvos/src/salvos/login.py`, `salvos/tests/test_baixar.py`

**Interfaces:**
- Consumes: `Biblioteca`, `Post`, `Config`.
- Produces:
  - `@dataclass PostRemoto`: `shortcode`, `url`, `autor`, `data: str`, `legenda`, `hashtags: list[str]`, `tipo`, `midias: list[tuple[str, str]]` (url, extensão `"jpg"`/`"mp4"`).
  - `class PausaInstagram(Exception)` e `class SessaoInvalida(Exception)`.
  - `class FonteSalvos(Protocol)`: `iterar() -> Iterator[PostRemoto]` e `baixar_midia(url: str, destino: Path) -> None`.
  - `class FonteInstaloader(cfg: Config, usuario: str)`: carrega a sessão de `cfg.pasta_app / f"session-{usuario}"`; `iterar()` usa `Profile.get_saved_posts()`; carrossel via `get_sidecar_nodes()`; `baixar_midia` via `context.get_raw` gravando em `destino`. Usa uma subclasse de `instaloader.RateController` cujo `handle_429` levanta `PausaInstagram` (sem esperar), e `max_connection_attempts=1`. Converte `TooManyRequestsException` e as respostas "Please wait a few minutes" em `PausaInstagram`; `LoginRequiredException` e sessão ausente em `SessaoInvalida`.
  - `@dataclass ResultadoDownload`: `novos: int`, `pausado: bool`.
  - `sincronizar_downloads(bib: Biblioteca, fonte: FonteSalvos, cfg: Config, completo: bool = False, limite: int | None = None, espera: Callable[[float], None] = time.sleep) -> ResultadoDownload`: para cada post remoto, pula os que já existem (zera a contagem de conhecidos quando aparece um novo); para após `cfg.parada_conhecidos` conhecidos seguidos (exceto `completo`) ou após `limite or cfg.limite` novos. Cada novo é gravado dentro de `bib.preparar()` com mídias `01.jpg`, `02.mp4`… e `post.json` (`etapas = {"baixado": True, "transcrito": tipo == "imagem", "classificado": False}`; carrossel sem vídeo também conta como transcrito). Entre posts novos, `espera(random.uniform(cfg.pausa_min, cfg.pausa_max))`. `PausaInstagram` → retorna `pausado=True` com o que já foi salvo.
  - `login.py`: `importar_firefox(cfg: Config) -> str` (procura `cookies.sqlite` em `%APPDATA%\Mozilla\Firefox\Profiles\*`, copia para um arquivo temporário antes de ler, carrega os cookies de `instagram.com` na sessão do Instaloader, `test_login()`, `save_session_to_file`; retorna o usuário ou levanta `SessaoInvalida("Nenhum login do Instagram encontrado no Firefox.")`) e `login_interativo(cfg: Config, usuario: str) -> str` (`interactive_login`, depois salva a sessão).

- [ ] **Step 1: Testes que falham** em `test_baixar.py`, com uma `FonteFalsa` que serve uma lista de `PostRemoto`, grava bytes fixos em `baixar_midia` e pode levantar `PausaInstagram` ou `KeyboardInterrupt` no N-ésimo post:
  - `test_baixa_novos_com_midias_e_post_json`: o carrossel gera `01.jpg`, `02.mp4` e `post.tipo == "carrossel"`.
  - `test_para_apos_cinco_conhecidos_seguidos`: com 7 conhecidos seguidos de 3 novos, nenhum dos 3 é baixado; com `completo=True`, os 3 são baixados.
  - `test_respeita_limite`
  - `test_pausa_preserva_progresso`: `PausaInstagram` no 3º post → 2 salvos, `pausado is True`, nenhuma pasta `.tmp-*`.
  - `test_interrupcao_e_retomada_sem_duplicar`: `KeyboardInterrupt` no 3º; uma segunda chamada com fonte normal termina e cada shortcode aparece uma vez.
  - `test_espera_entre_posts_no_intervalo`: todos os valores passados a `espera` estão em `[4, 10]`.
  - `test_imagem_ja_marcada_como_transcrita`
- [ ] **Step 2:** `pytest tests/test_baixar.py -v` → FAIL.
- [ ] **Step 3:** Implementar `baixar.py` e `login.py`. `FonteInstaloader` e `login.py` não têm teste automático (dependem da conta real); revisar contra a documentação da versão instalada do Instaloader (`RateController`, `get_saved_posts`, `get_sidecar_nodes`, `save_session_to_file`).
- [ ] **Step 4:** `pytest tests/test_baixar.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(salvos): download incremental dos salvos`.

---

### Task 5: Transcrição

**Files:**
- Create: `salvos/src/salvos/transcrever.py`, `salvos/tests/test_transcrever.py`

**Interfaces:**
- Consumes: `Biblioteca.pendentes("transcrito")`, `Biblioteca.gravar_transcricao`.
- Produces:
  - `Transcritor = Callable[[Path], str]`
  - `transcritor_whisper(cfg: Config) -> Transcritor`: carrega `WhisperModel(cfg.modelo_whisper, device="cpu", compute_type="int8")` uma vez e retorna uma função que junta o texto dos segmentos com espaços.
  - `transcrever_pendentes(bib: Biblioteca, transcrever: Transcritor, aviso: Callable[[str], None] = print) -> int`: para cada post pendente, transcreve seus arquivos `.mp4` em ordem e grava o texto unido por `"\n\n"`; uma exceção num post chama `aviso(f"Falha ao transcrever {shortcode}: {erro}")`, deixa o post pendente e segue para o próximo. Retorna o número de posts transcritos.

- [ ] **Step 1: Testes que falham**:
  - `test_transcreve_videos_pendentes`: texto gravado e `etapas["transcrito"] is True`.
  - `test_falha_num_post_nao_trava_os_outros`: o primeiro post levanta exceção; o segundo é transcrito; o primeiro continua pendente.
  - `test_video_sem_fala_marca_transcrito`: o transcritor retorna `""` → transcrito, texto vazio.
- [ ] **Step 2:** `pytest tests/test_transcrever.py -v` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `pytest tests/test_transcrever.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(salvos): transcrição com faster-whisper`.

---

### Task 6: Descoberta de nichos e classificação

**Files:**
- Create: `salvos/src/salvos/nichos.py`, `salvos/src/salvos/classificar.py`, `salvos/tests/test_nichos.py`, `salvos/tests/test_classificar.py`

**Interfaces:**
- Consumes: `ClienteIA.chat`, `ClienteIA.escolher`, `ErroIA`, `ErroFatalIA`, `Biblioteca`.
- Produces:
  - `resumo(post: Post, transcricao: str) -> str`: `f"@{autor}: {legenda[:300]} | {transcricao[:300]}"`.
  - `propor_nichos(bib: Biblioteca, ia: ClienteIA, modelo: str, posts: list[Post] | None = None, existentes: list[Nicho] | None = None) -> list[Nicho]`: envia os resumos (todos os posts, ou só `posts`) pedindo **somente** JSON `[{"nome": ..., "descricao": ...}]` com 5 a 15 nichos (com `existentes`, pede apenas nichos novos que não repitam os existentes). Faz o parse tolerando cercas ```json; garante `"Outros"` no fim; levanta `ErroIA("Resposta da IA sem lista de nichos válida")` se o JSON for inválido.
  - `revisar_nichos(bib, ia, modelo) -> list[Nicho]`: `propor_nichos` só com os posts do nicho `"Outros"` e `existentes = bib.nichos()`.
  - `LIMIAR_CONFIANCA = 0.5`
  - `state_do_post(post: Post, transcricao: str) -> str`: JSON `{"autor", "legenda", "hashtags", "transcricao"}` cortado em 4.000 caracteres; nunca vazio.
  - `@dataclass ResultadoClassificacao`: `classificados: int`, `em_outros: int`, `sem_nichos: bool`, `parado_por: str | None` (mensagem de `ErroFatalIA`).
  - `classificar_pendentes(bib: Biblioteca, ia: ClienteIA, modelo: str) -> ResultadoClassificacao`: sem `bib.nichos()` → `sem_nichos=True` sem chamar a IA. Para cada post em `pendentes("classificado")` com `nicho_manual is False`: `escolher(state, {n.nome: n.descricao}, instrucoes)`, com instruções em inglês: `"Pick the niche that best matches the main subject of this saved Instagram post. Use 'Outros' when none fits."`. Grava `nicho`, `confianca`, `revisar = confianca < LIMIAR_CONFIANCA` e `etapas["classificado"] = True`. Escolha fora da lista vira `"Outros"` com `revisar=True`. `ErroIA` num post o deixa pendente e segue; `ErroFatalIA` para tudo e preenche `parado_por`. Posts com `nicho_manual` só recebem `etapas["classificado"] = True`.

- [ ] **Step 1: Testes que falham** (ClienteIA falso com respostas programadas):
  - `test_propor_nichos_parse_com_cerca_e_garante_outros`
  - `test_propor_nichos_json_invalido_levanta_erro`
  - `test_revisar_usa_so_posts_de_outros_e_passa_existentes`
  - `test_classifica_e_marca_revisar_abaixo_de_05`: confiança 0,49 → `revisar`; 0,5 → não.
  - `test_nicho_manual_nunca_sobrescrito`: `escolher` não é chamado para esse post e o nicho continua.
  - `test_sem_nichos_toml_pula_classificacao`: `sem_nichos is True`, nenhuma chamada.
  - `test_post_imagem_sem_legenda_tem_state_nao_vazio`: o `state` enviado contém o autor.
  - `test_escolha_fora_da_lista_vira_outros`
  - `test_erro_fatal_para_e_informa`: `parado_por` preenchido e os posts restantes pendentes.
- [ ] **Step 2:** `pytest tests/test_nichos.py tests/test_classificar.py -v` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar de novo → PASS.
- [ ] **Step 5:** Commit `feat(salvos): descoberta de nichos e classificação com Jev`.

---

### Task 7: Exportação

**Files:**
- Create: `salvos/src/salvos/exportar.py`, `salvos/tests/test_exportar.py`

**Interfaces:**
- Consumes: `Biblioteca.listar`, `Biblioteca.transcricao`, `Biblioteca.pasta`.
- Produces:
  - `nome_arquivo(nicho: str) -> str`: troca `<>:"/\|?*` e caracteres de controle por `-`, remove espaços e pontos no fim e evita nomes reservados do Windows (`CON`, `NUL`, `COM1`…, com prefixo `_`); vazio vira `"nicho"`.
  - `exportar_md(bib: Biblioteca, nicho: str) -> str`: `# {nicho}`, a linha `Exportado em {AAAA-MM-DD} · {n} posts`; por post, `## @{autor} — {data[:10]}`, `{url}`, `### Legenda`, a legenda, e `### Transcrição` com o texto (seção omitida se a transcrição for vazia); posts separados por `---`.
  - `exportar_zip(bib: Biblioteca, nicho: str, destino: BinaryIO) -> None`: `f"{nome_arquivo(nicho)}.md"` na raiz do zip + `posts/<shortcode>/…` de cada post do nicho.

- [ ] **Step 1: Testes que falham**:
  - `test_md_contem_autor_link_legenda_transcricao`, incluindo legenda com emoji.
  - `test_md_omite_transcricao_vazia`
  - `test_zip_tem_md_e_midias`
  - `test_nome_arquivo_windows`: `nome_arquivo("Saúde/Bem-estar") == "Saúde-Bem-estar"`, `nome_arquivo("IA: ferramentas") == "IA- ferramentas"`, `nome_arquivo("CON") == "_CON"`, `nome_arquivo("Estudo.") == "Estudo"`.
- [ ] **Step 2:** `pytest tests/test_exportar.py -v` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(salvos): exportação de nicho em md e zip`.

---

### Task 8: API web

**Files:**
- Create: `salvos/src/salvos/web/__init__.py`, `salvos/src/salvos/web/app.py`, `salvos/tests/test_web.py`

**Interfaces:**
- Consumes: `Biblioteca`, `exportar_md`, `exportar_zip`, `nome_arquivo`.
- Produces: `criar_app(bib: Biblioteca) -> FastAPI` com:
  - `GET /` → `static/index.html`; `/static/*` → arquivos estáticos.
  - `GET /api/nichos` → `[{"nome", "descricao", "total"}]`, com os nichos de `nichos.toml` e mais `"Sem classificação"` se houver posts sem nicho.
  - `POST /api/nichos` `{nome, descricao}` → 201 (409 se já existir); `PATCH /api/nichos/{nome}` `{novo_nome?, descricao?, juntar_em?}`; `DELETE /api/nichos/{nome}` (400 para `"Outros"`).
  - `GET /api/posts?nicho=&q=&revisar=` → lista de `para_dict()` + `"capa"` (primeiro arquivo).
  - `GET /api/posts/{shortcode}` → `para_dict()` + `"transcricao"`; 404 se não existir.
  - `PATCH /api/posts/{shortcode}` `{nicho}` → grava `nicho`, `nicho_manual=True`, `revisar=False`; 400 se o nicho não existir.
  - `GET /api/exportar/{nicho}.md` e `.zip` → download com `Content-Disposition` usando `nome_arquivo`.
  - `GET /midia/{shortcode}/{arquivo}` → o arquivo do post; 404 se o caminho resolvido sair da pasta do post.

- [ ] **Step 1: Testes que falham** com `fastapi.testclient.TestClient`:
  - `test_lista_nichos_com_total`
  - `test_filtra_posts_por_nicho_e_busca`
  - `test_busca_com_aspas_nao_da_500`: `q='"'` → 200.
  - `test_mover_post_marca_manual`
  - `test_mover_para_nicho_inexistente_400`
  - `test_criar_renomear_juntar_apagar_nicho`, incluindo `DELETE /api/nichos/Outros` → 400.
  - `test_exportar_md_e_zip`: status 200 e `Content-Disposition` com o nome sanitizado.
  - `test_midia_bloqueia_path_traversal`: `/midia/ABC/..%2F..%2Fbiblioteca.db` → 404.
- [ ] **Step 2:** `pytest tests/test_web.py -v` → FAIL.
- [ ] **Step 3:** Implementar `app.py` (o `index.html` pode ser um placeholder nesta task).
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(salvos): API web local`.

---

### Task 9: Página (HTML/JS/CSS)

**Files:**
- Create: `salvos/src/salvos/web/static/index.html`, `app.js`, `estilo.css`

**Interfaces:**
- Consumes: a API da Task 8 (só `fetch`, sem bibliotecas externas e sem build).

Layout conforme a spec §5:
- barra lateral com "Todos", "Revisar" (com selo de contagem), os nichos com totais e "+ Novo nicho"; ações renomear, juntar e apagar num menu por nicho;
- campo de busca com debounce de 300 ms;
- grade de cards com `capa` (`<img>`, ou `<video muted preload="metadata">` para mp4), ícone de vídeo/carrossel, `@autor`, data e duas linhas de legenda; selo "revisar" quando `revisar`;
- painel de detalhe com carrossel/player, legenda, transcrição, `<select>` de nicho (o `PATCH` atualiza a contagem na barra) e "Abrir no Instagram";
- botão "Exportar nicho ▾" com as opções `.md` e `.zip`;
- tema claro/escuro via `prefers-color-scheme`.

- [ ] **Step 1:** Implementar os três arquivos.
- [ ] **Step 2:** Verificar no navegador: criar uma biblioteca de demonstração com 6 posts falsos (script de teste ou fixture), subir `criar_app` com uvicorn e, com Playwright, abrir a página, filtrar por nicho, buscar, mover um post de nicho e exportar o `.md`. Tirar screenshots em largura desktop e 390 px para conferir o layout.
- [ ] **Step 3:** Commit `feat(salvos): página local`.

---

### Task 10: CLI, README e teste de ponta a ponta

**Files:**
- Create: `salvos/src/salvos/cli.py`, `salvos/README.md`, `salvos/tests/test_cli.py`

**Interfaces:**
- Consumes: todas as anteriores.
- Produces: `main(argv: list[str] | None = None) -> int`, com `sys.stdout.reconfigure(encoding="utf-8")` no início. Subcomandos:
  - `login [--interativo USUARIO]`: Firefox por padrão; grava o usuário em `cfg.pasta_app/"usuario.txt"`.
  - `sync [--limite N] [--completo]`: download → transcrição → classificação, com um resumo final (`Novos: X · Transcritos: Y · Classificados: Z`). Mensagens fixas:
    - pausa: `"O Instagram pediu uma pausa. O progresso foi salvo; tente de novo daqui a algumas horas."`
    - sessão: `"Sessão do Instagram inválida ou expirada. Rode: salvos login"`
    - sem nichos: `"Rode \`salvos nichos\` para definir seus nichos."`
    - 10 ou mais em "Outros": `"Há {n} posts em Outros. Rode \`salvos nichos --revisar\` para sugerir nichos novos."`
    - `ErroFatalIA`: a mensagem do erro.
    - Pausa e sessão inválida pulam o download, mas transcrição e classificação rodam mesmo assim, sobre o que já existe.
  - `nichos [--revisar]`: mostra a proposta numerada; `[a]ceitar / [e]ditar / [n]ova proposta`. Editar grava um `nichos.toml` provisório e abre com `os.startfile` (Windows) ou `$EDITOR`, e depois relê. No modo `--revisar`, os aceitos são somados aos existentes. Depois de aceitar, oferece classificar os pendentes na hora.
  - `abrir [--porta N]`: `uvicorn.run(criar_app(bib), host="127.0.0.1", port=...)` e abre o navegador com `webbrowser.open`.
  - `reindexar`: imprime `"Índice recriado: {n} posts."`.
  - Código de saída 0 em sucesso, 1 em erro.

- [ ] **Step 1: Testes que falham** em `test_cli.py` (fakes injetados via monkeypatch nos construtores):
  - `test_sync_completo_com_fakes`: fonte com 3 posts (1 vídeo) + nichos.toml → os 3 classificados, o vídeo transcrito, resumo impresso, código 0.
  - `test_sync_pausa_mostra_mensagem_e_segue_etapas`
  - `test_sync_sessao_invalida`
  - `test_sync_sem_nichos_avisa`
  - `test_sync_sugere_revisar_com_10_em_outros`
  - `test_nichos_aceitar_grava_toml` (entrada simulada `"a"`)
  - `test_reindexar_imprime_total`
  - `test_abrir_usa_127_0_0_1` (uvicorn.run simulado)
- [ ] **Step 2:** `pytest tests/test_cli.py -v` → FAIL.
- [ ] **Step 3:** Implementar `cli.py`.
- [ ] **Step 4:** `pytest -v` (suíte inteira) → PASS.
- [ ] **Step 5:** Escrever `README.md` em português para o Windows: instalar o Python 3.11+ (marcando "Add to PATH"); `python -m venv .venv` e `.venv\Scripts\activate`; `pip install -e .`; configurar a chave (`setx OPENROUTER_API_KEY ...` ou o arquivo `%APPDATA%\salvos\.env`); logar no Instagram pelo Firefox e rodar `salvos login`; `salvos sync --limite 5`; `salvos nichos`; `salvos sync`; `salvos abrir`. Incluir os avisos de risco (Termos de Uso, bloqueio temporário, não rodar várias vezes por dia), o que sai do computador e a nota de que a primeira transcrição baixa o modelo Whisper (~500 MB).
- [ ] **Step 6:** Commit `feat(salvos): CLI e README`.
