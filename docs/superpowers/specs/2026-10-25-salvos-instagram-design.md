# Salvos: organizador local dos posts salvos do Instagram

**Data:** 2026-10-25
**Status:** em revisão pelo usuário

## 1. Objetivo

O usuário salva no Instagram algumas centenas de posts sobre vários assuntos
(estudo, saúde, IA etc.). A ferramenta deve:

1. baixar os posts salvos, com mídias, legenda e metadados;
2. transcrever o áudio dos vídeos e reels;
3. agrupar os posts em **nichos** descobertos pela IA e aprovados pelo usuário;
4. mostrar tudo numa página local, organizada por nicho;
5. exportar o conteúdo de um nicho (texto e mídias).

**Sucesso:** o usuário roda `salvos sync`, abre `salvos abrir`, vê seus salvos
separados por nicho, corrige o que estiver errado e exporta um nicho inteiro
num `.md` pronto para ler ou colar numa IA.

### Fora do escopo (v1)

Tags múltiplas por post, anotações pessoais, acesso pelo celular ou
hospedagem, posts de outras contas que não sejam os salvos do usuário,
sincronização automática agendada.

## 2. Ambiente do usuário

- **Windows**, Python 3.11+.
- Navegador logado no Instagram (Firefox recomendado, ver §4.1).
- Quantidade: algumas centenas de posts no máximo.
- Chave da OpenRouter (`OPENROUTER_API_KEY`).

## 3. Arquitetura

Um único pacote Python (`salvos/`, na raiz deste repositório), instalado com
`pip install -e .`, que expõe o comando `salvos`.

| Comando | Função |
|---|---|
| `salvos login` | Importa a sessão do Instagram do navegador e salva o arquivo de sessão do Instaloader. |
| `salvos sync [--limite N]` | Executa as etapas baixar → transcrever → classificar. |
| `salvos nichos` | Propõe a lista de nichos (IA) e pede aprovação/edição ao usuário. |
| `salvos abrir` | Sobe o servidor local em `127.0.0.1:8000` e abre o navegador. |
| `salvos reindexar` | Recria `biblioteca.db` a partir das pastas dos posts. |

### Módulos (cada um com uma responsabilidade)

| Módulo | Responsabilidade | Depende de |
|---|---|---|
| `config.py` | Caminhos da biblioteca, chave, limites, modelos. Lê `salvos.toml` + variáveis de ambiente. | — |
| `biblioteca.py` | Pastas dos posts + índice SQLite (ler/gravar post, nicho, estado das etapas). Única porta de acesso aos dados. | config |
| `baixar.py` | Instaloader: itera `:saved`, baixa mídias e metadados, aplica ritmo e para no primeiro post já baixado. | biblioteca |
| `transcrever.py` | faster-whisper sobre os vídeos sem transcrição. | biblioteca |
| `nichos.py` | Descoberta da lista de nichos (LLM generativo). | biblioteca, ia |
| `classificar.py` | Atribui nicho aos posts pendentes (Jev `choice`). | biblioteca, ia |
| `ia.py` | Cliente OpenRouter (chat completions + `alpha/decisions`), com retry e backoff. | config |
| `exportar.py` | Gera `.md` e `.zip` de um nicho. | biblioteca |
| `web/` | Servidor (FastAPI) + uma página HTML/JS/CSS sem etapa de build. | biblioteca, exportar |
| `cli.py` | Comandos acima. | todos |

## 4. Fluxo de dados

```
Instagram (:saved)
  │ baixar.py       → posts/<shortcode>/ (mídias + post.json)
  │ transcrever.py  → posts/<shortcode>/transcricao.txt
  │ classificar.py  → nicho no post.json
  ▼
biblioteca.db (índice SQLite + FTS5 para busca)
  ▼
web/ (lê o índice, serve as mídias)
```

### 4.1 Login (Windows)

- **Caminho principal:** importar os cookies do **Firefox** (o mesmo método do
  script `615_import_firefox_session.py` do Instaloader). No Windows, o Chrome
  127+ cifra os cookies com "app-bound encryption", e ler esses cookies de fora
  do navegador não é confiável.
- **Alternativa:** login interativo do próprio Instaloader (usuário, senha e
  2FA digitados no terminal). A senha nunca é gravada; só o arquivo de sessão.
- A sessão fica em `%APPDATA%\salvos\session-<usuario>`, fora da biblioteca e
  do git.

### 4.2 Baixar

- Itera `Profile.get_saved_posts()`, do mais novo para o mais antigo.
- **Incremental:** para ao encontrar `N=5` posts seguidos que já existem
  (tolera reordenação). `--completo` ignora essa regra e varre tudo.
- **Ritmo:** pausa aleatória de 4 a 10 s entre posts; limite padrão de 150
  posts por execução (`--limite`).
- Por post, grava em `posts/<shortcode>/`: as mídias (imagens/vídeos, na ordem
  do carrossel) e `post.json` com shortcode, url, autor, data do post,
  legenda, hashtags, tipo (imagem/carrossel/vídeo), lista de arquivos e
  `etapas: {baixado, transcrito, classificado}`.
- Grava primeiro numa pasta temporária e renomeia ao final: um post
  interrompido no meio nunca aparece como baixado.

### 4.3 Transcrever

- `faster-whisper`, modelo `small` em CPU com `int8` (configurável), idioma
  automático. Não precisa de ffmpeg instalado à parte (usa PyAV).
- Só vídeos com `etapas.transcrito = false`. Grava `transcricao.txt`.
- Vídeo sem fala → transcrição vazia, marcado como transcrito.

### 4.4 Nichos

- `salvos nichos` envia um resumo de cada post (autor + 300 primeiros
  caracteres de legenda e transcrição) a um LLM generativo via OpenRouter
  (modelo configurável em `salvos.toml`). Pede de 5 a 15 nichos, cada um com
  nome curto e descrição de uma linha, mais "Outros".
- Mostra a lista no terminal; o usuário aceita, edita (abre o
  `nichos.toml` no editor padrão) ou pede outra proposta.
- A lista aprovada fica em `nichos.toml` na biblioteca.
- Se `classificar` deixar 10 posts ou mais em "Outros", o `sync` sugere rodar
  `salvos nichos --revisar`, que propõe nichos novos só a partir desses posts.

### 4.5 Classificar

- **Jev** (`typesafe/jev-1.13`, rota `alpha/decisions`), pergunta do tipo
  `choice` com os nichos aprovados como opções (nome → descrição).
- `state` = autor + legenda + transcrição (cortada em 4.000 caracteres).
- Confiança < 0,5 → o post recebe o nicho sugerido, mas é marcado
  `revisar = true` e aparece com um selo na página.
- Post com `nicho_manual = true` **nunca** é reclassificado.
- Só vai à IA o texto; imagens e vídeos nunca saem do computador.

### 4.6 Fonte da verdade

As pastas `posts/<shortcode>/` + `nichos.toml` são a fonte da verdade.
`biblioteca.db` é um índice derivado, recriado por `salvos reindexar`. Toda
gravação passa por `biblioteca.py`, que atualiza o `post.json` e o índice
juntos.

## 5. Página local

Servidor FastAPI em `127.0.0.1` (nunca `0.0.0.0`). Uma página com:

- **Barra lateral:** nichos com contagem; "Todos"; "Revisar"; criar,
  renomear, juntar e apagar nicho (os posts de um nicho apagado vão para
  "Outros").
- **Grade:** cards com miniatura, ícone de vídeo/carrossel, autor, data e o
  início da legenda. Busca (FTS5) em legenda, transcrição e autor, dentro do
  nicho atual ou em "Todos".
- **Detalhe:** carrossel ou player de vídeo, legenda completa, transcrição,
  seletor de nicho (grava `nicho_manual = true`), link "Abrir no Instagram".
- **Exportar nicho:**
  - `.md`: cabeçalho com nome do nicho e data; por post: autor, data, link,
    legenda e transcrição.
  - `.zip`: o `.md` + as pastas dos posts do nicho.

API interna: `GET /api/nichos`, `GET /api/posts?nicho=&q=`,
`GET /api/posts/{shortcode}`, `PATCH /api/posts/{shortcode}` (nicho),
`POST/PATCH/DELETE /api/nichos`, `GET /api/exportar/{nicho}.md|.zip`,
`GET /midia/{shortcode}/{arquivo}`.

## 6. Erros

| Situação | Comportamento |
|---|---|
| 429 / "Please wait a few minutes" | Para o `sync` na hora, salva o progresso e diz para tentar de novo em algumas horas. Sem retry automático. |
| Sessão inválida / login exigido | Mensagem pedindo `salvos login`. |
| Post apagado ou privado | `indisponivel = true` no post.json; o que já foi baixado é mantido. |
| Falha no Whisper | Etapa fica pendente; as outras seguem. |
| Falha na OpenRouter (401/402/429/5xx) | 401/402: mensagem clara e para a classificação. 429/5xx: 3 tentativas com backoff; depois deixa pendente. |
| `sync` interrompido (Ctrl+C, queda) | Nada corrompido (§4.2); o próximo `sync` retoma. |

## 7. Configuração e privacidade

- `salvos.toml` na biblioteca: caminho, modelos, limites. A chave vem só de
  `OPENROUTER_API_KEY` ou de `%APPDATA%\salvos\.env`, nunca do toml.
- Biblioteca padrão: `%USERPROFILE%\Salvos`. Fica fora do repositório;
  `.gitignore` cobre `Salvos/`, `*.db`, `.env` e arquivos de sessão.
- Só saem do computador: as requisições ao Instagram e o texto enviado à
  OpenRouter. As chaves nunca são impressas nem gravadas em log.

## 8. Testes

- `pytest`, sem rede: Instaloader, faster-whisper e OpenRouter substituídos
  por versões simuladas com posts de exemplo.
- Casos obrigatórios:
  - sync interrompido no meio retoma sem duplicar e sem pasta parcial;
  - parada incremental após N posts conhecidos;
  - 429 interrompe e preserva o progresso;
  - `nicho_manual` nunca é sobrescrito;
  - confiança baixa marca `revisar`;
  - `reindexar` recria o índice idêntico a partir das pastas;
  - busca FTS encontra texto da legenda e da transcrição;
  - conteúdo do `.md` e do `.zip` exportados;
  - endpoints da API (TestClient) e servidor preso a `127.0.0.1`.
- Teste real fica com o usuário: `salvos sync --limite 5`.

## 9. Entregáveis

- Pacote `salvos/` + `pyproject.toml` + testes.
- `README.md` em português com instalação passo a passo no Windows
  (Python, `pip install -e .`, chave da OpenRouter, `salvos login` via
  Firefox, primeiro `sync --limite 5`).
