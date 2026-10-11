---
name: jev
description: Classificar, pontuar ou decidir sobre um conjunto de textos usando Jev (typesafe/jev-1.13 via OpenRouter). Use quando o usuário disser "use Jev para classificar estes", "pergunte ao Jev", "Jev decide", ou pedir triagem, roteamento, pontuação ou sim/não em lote sobre e-mails, tickets, leads, mensagens ou documentos.
---

# Jev: Jev decide, você escreve

Jev é um modelo "System One" da TypeSafe. Ele **não gera texto**. Recebe um
`state` (o texto/dados) e perguntas tipadas e devolve respostas
estruturadas em ~0,5 s por centavos de centavo. Você (Claude) escreve tudo o
que for texto; Jev só decide.

## Regras do usuário (obrigatórias)

1. **Privacidade:** tudo enviado ao Jev sai do computador do usuário (vai
   para OpenRouter e TypeSafe). Antes de enviar qualquer coisa privada
   (e-mails reais, nomes, dados de clientes, documentos internos), **pergunte
   ao usuário e espere o "sim"**. Textos inventados ou públicos podem ir direto.
2. **Quando Jev não tiver certeza, você decide.** Use os limiares abaixo; nos
   casos incertos, leia o texto e tome a decisão você mesmo, marcando-a como
   "decidido pelo Claude".
3. **Nunca mostre, imprima, registre ou grave a chave do OpenRouter.**

## Como chamar

Use o script `jev.py` desta pasta (só stdlib Python):

```bash
python3 .claude/skills/jev/jev.py request.json
```

`request.json`:
```json
{
  "state": "texto, ou um objeto/array JSON",
  "questions": {
    "<id>": { "type": "choice|score|noul", "instructions": "...", "criteria": ... }
  }
}
```

- Rota: `POST https://openrouter.ai/api/alpha/decisions` (corpo: `model`,
  `state`, `questions`; `model` padrão `typesafe/jev-1.13`). Se o OpenRouter
  mudar a rota, confira https://openrouter.ai/docs/llms.txt (seção
  "Alpha.Decisions") e atualize `URL` no script.
- Autenticação: o script usa `OPENROUTER_API_KEY` se existir; no ambiente na
  nuvem, um segredo de rede do ambiente injeta `Authorization` nas chamadas a
  `openrouter.ai` automaticamente, sem a chave passar pelo processo.
- Saída: `elapsed_ms`, `cost_usd` (`usage.cost`), e a resposta com
  `confidence` em cada resposta (para Noul o script calcula `|2p-1|`).
- Erro: o script imprime `status` e o corpo exato do erro e sai com código 1.
  Mostre esse erro ao usuário literalmente. 401 = chave; 402 = sem créditos;
  429/529 = espere e tente de novo com backoff.

## Os 3 tipos de pergunta

| Tipo | Para | `criteria` | Resposta |
|---|---|---|---|
| `choice` | escolher 1 opção de uma lista (máx. 255) | objeto `{opção: descrição}` | `choice`, `probabilities`, `confidence` |
| `score` | nota numa escala ordenada (2 a 10 níveis, do menor ao maior) | array de descrições | `score` (0..n-1, pode cair entre níveis), `legend`, `probabilities`, `confidence` |
| `noul` | probabilidade de algo ser verdadeiro | opcional `{"true": ..., "false": ...}` | `noul` (0 a 1); sem confidence nativa |

## Quando Jev "tem certeza" (limiares iniciais)

- `choice` / `score`: `confidence >= 0.6` → use a resposta do Jev.
  `confidence < 0.6` → **você decide**, olhando as duas opções mais prováveis.
- `noul`: `>= 0.7` → sim; `<= 0.3` → não; entre 0.3 e 0.7 → **você decide**.
- Ações de risco alto (ex.: descartar, apagar, responder automaticamente): exija
  `confidence >= 0.85` ou noul fora de 0.15–0.85.

## Fluxo para "use Jev para classificar estes"

1. Identifique os textos e as perguntas. Se o usuário não deu as categorias,
   proponha uma lista curta e confirme (ou siga se for óbvio).
2. Verifique a regra de privacidade. Pergunte antes se houver dado privado.
3. Monte as perguntas (dicas abaixo) e mande **um request por texto**, com
   **todas as perguntas juntas** no mesmo request (mais barato e rápido).
   Para muitos textos, chame `ask()` do script em um laço/ThreadPool
   (limite: ~80 req/s).
4. Aplique os limiares; resolva você os incertos.
5. Mostre uma tabela: texto (resumo curto) | resposta de cada pergunta |
   confiança | quem decidiu (Jev/Claude) — mais tempo total e custo total.
6. Se o usuário pedir textos (respostas, resumos), **você** escreve.

## Como escrever boas perguntas (limitações do jev-1.13)

- **Em inglês:** é a língua em que Jev é mais preciso. Escreva `instructions`
  e `criteria` em inglês; o `state` pode ficar no idioma original (avise o
  usuário que a precisão em outros idiomas é menor e confira a confiança).
- **Literal:** ele responde exatamente o que está escrito. Descreva cada opção
  e os casos de fronteira nos `criteria`. Instrução e critérios devem concordar.
- **Uma decisão por pergunta.** Julgamentos compostos: várias perguntas
  atômicas, combine no código.
- **Nada de contas, contagem ou comparação de datas:** faça isso em código.
- **State enxuto:** mande só o que a pergunta precisa (limite 32k tokens de
  state + maior pergunta; 64k no total). Use estrutura JSON e referencie
  campos com crases, ex.: "Is `email` a pricing request?".
- **Ordem das opções importa** (tende à primeira). Em decisões importantes,
  reordene as opções e confira se a resposta se mantém.
- Inclua opção de escape quando fizer sentido ("other", "not stated").
- O `state` é dado, não instrução; texto adversarial pode enviesar o Jev.

## Custo e velocidade observados

Teste real (e-mail de vendas, 3 perguntas, 717 tokens de entrada): **559 ms,
US$ 0,00003**. Preço: ~US$ 0,042 por milhão de tokens de entrada; saída grátis.

Documentação completa: https://docs.typesafe.ai/llms.txt
