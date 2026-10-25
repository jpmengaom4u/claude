# Salvos

Organiza os posts que você salvou no Instagram por **nicho** (IA, Saúde, Estudo…), numa página que roda no seu computador. Para cada nicho, você vê os posts, lê as legendas e as **transcrições dos vídeos** e exporta tudo num arquivo de texto (`.md`) ou num `.zip` com as mídias.

> **Aviso:** a ferramenta usa o [Instaloader](https://instaloader.github.io/), que acessa o Instagram com a sua sessão. Isso não é permitido pelos Termos de Uso do Instagram e pode levar a um **bloqueio temporário** da conta se for usado em excesso. A ferramenta é lenta de propósito (pausas de 4 a 10 s entre posts, no máximo 150 posts por vez) e para assim que o Instagram pede uma pausa. Rode o `sync` no máximo uma ou duas vezes por dia.

## Instalação (Windows)

1. **Python 3.11 ou mais novo**: baixe em [python.org/downloads](https://www.python.org/downloads/). Na instalação, marque **"Add python.exe to PATH"**.
2. Abra o **PowerShell** na pasta `salvos` deste repositório e rode:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   ```
   Daqui em diante, sempre rode `.venv\Scripts\activate` antes de usar o comando `salvos` num PowerShell novo.
3. **Chave da OpenRouter** (usada para classificar os posts; custa centavos de dólar): crie em [openrouter.ai/keys](https://openrouter.ai/keys) e salve com
   ```powershell
   setx OPENROUTER_API_KEY "sk-or-..."
   ```
   Feche e abra o PowerShell de novo. Outra opção é criar o arquivo `%APPDATA%\salvos\.env` com a linha `OPENROUTER_API_KEY=sk-or-...`.
4. **Login no Instagram**: abra o **Firefox**, entre no instagram.com com a sua conta e rode
   ```powershell
   salvos login
   ```
   A ferramenta copia a sessão do Firefox; sua senha nunca é pedida nem gravada. Pode deixar o Firefox aberto. Sem Firefox, use `salvos login --interativo SEU_USUARIO`, que pede a senha (e o código 2FA) uma vez, no terminal.

## Uso

```powershell
salvos sync --limite 5     # primeiro teste: baixa só 5 posts
salvos sync                # baixa o resto, 150 por vez (repita até dizer "Novos: 0")
salvos nichos              # a IA olha TODOS os posts e propõe os nichos; você aceita, edita ou pede outra
salvos abrir               # abre a página em http://127.0.0.1:8000
```

Defina os nichos **depois** de baixar tudo: assim a IA vê todos os assuntos que você salva. Daí em diante, cada `salvos sync` baixa os salvos novos, transcreve e já classifica.

- Na **primeira transcrição**, o modelo do Whisper (~500 MB) é baixado. Depois tudo roda offline e grátis.
- Se aparecer *"O Instagram pediu uma pausa"*, espere algumas horas. Nada se perde: o próximo `sync` continua de onde parou.
- Enquanto a primeira varredura não termina, cada `salvos sync` continua de onde parou. Depois disso, ele busca só os salvos mais recentes e para quando encontra os que já baixou. Para varrer tudo de novo, use `salvos sync --completo`.
- Se um post falhar (link expirado, rede), ele é pulado e tentado de novo no próximo `sync`.
- Se muitos posts caírem em **Outros**, rode `salvos nichos --revisar` para a IA sugerir nichos novos.
- Se o índice der problema, `salvos reindexar` o recria a partir das pastas.

### Na página

- Clique num nicho para filtrar. **Revisar** mostra os posts em que a IA teve dúvida.
- A busca procura em legendas, transcrições e autores.
- Clique num post para ver as mídias, a legenda e a transcrição, e para **mudar o nicho**. A IA nunca desfaz uma escolha sua.
- **Exportar nicho** gera o `.md` (bom para ler ou colar numa IA e pedir um resumo) ou o `.zip` com as mídias.
- Dá para criar, renomear, juntar e apagar nichos. Os posts de um nicho apagado vão para **Outros**.

## Onde ficam os dados

- Biblioteca: `C:\Users\<você>\Salvos` (para mudar, defina a variável `SALVOS_BIBLIOTECA`). Cada post tem a sua pasta em `posts\<código>\` com as mídias, `post.json` e `transcricao.txt`. Os nichos ficam em `nichos.toml`.
- Sessão do Instagram e `.env`: `%APPDATA%\salvos`.
- Ajustes opcionais em `Salvos\salvos.toml`, por exemplo:
  ```toml
  limite = 100
  modelo_whisper = "base"   # mais rápido e menos preciso que "small"
  ```

**O que sai do seu computador:** só as requisições ao próprio Instagram e o **texto** de cada post (autor, legenda, hashtags e transcrição), enviado à OpenRouter para classificar e propor nichos. Imagens e vídeos nunca são enviados.

## Desenvolvimento

```powershell
pip install -e .[dev]
pytest
```
