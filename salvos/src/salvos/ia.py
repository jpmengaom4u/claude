"""Cliente OpenRouter: chat (LLM generativo) e decisions (Jev)."""
from __future__ import annotations

import time
from typing import Callable

import httpx

URL_CHAT = "https://openrouter.ai/api/v1/chat/completions"
URL_DECISIONS = "https://openrouter.ai/api/alpha/decisions"
ESPERAS = (2, 4, 8)


class ErroIA(Exception):
    """Falha temporária: as tentativas se esgotaram."""


class ErroFatalIA(ErroIA):
    """Falha que não adianta repetir (chave inválida, sem créditos)."""


class ClienteIA:
    def __init__(
        self,
        chave: str | None,
        http: httpx.Client | None = None,
        espera: Callable[[float], None] = time.sleep,
    ):
        self._chave = chave
        self._http = http or httpx.Client(timeout=120)
        self._espera = espera

    def _post(self, url: str, corpo: dict) -> dict:
        headers = {"X-OpenRouter-Title": "salvos"}
        if self._chave:
            headers["Authorization"] = f"Bearer {self._chave}"
        ultimo = ""
        for tentativa in range(len(ESPERAS) + 1):
            if tentativa:
                self._espera(ESPERAS[tentativa - 1])
            try:
                resp = self._http.post(url, json=corpo, headers=headers)
            except httpx.HTTPError as e:
                ultimo = f"erro de rede ({type(e).__name__})"
                continue
            if resp.status_code == 401:
                raise ErroFatalIA("Chave da OpenRouter inválida (HTTP 401).")
            if resp.status_code == 402:
                raise ErroFatalIA("Sem créditos na OpenRouter (HTTP 402).")
            if resp.status_code == 429 or resp.status_code >= 500:
                ultimo = f"HTTP {resp.status_code}"
                continue
            if resp.status_code >= 400:
                raise ErroIA(f"OpenRouter recusou a requisição (HTTP {resp.status_code}).")
            return resp.json()
        raise ErroIA(f"OpenRouter indisponível após {len(ESPERAS) + 1} tentativas: {ultimo}.")

    def chat(self, modelo: str, mensagens: list[dict]) -> str:
        dados = self._post(URL_CHAT, {"model": modelo, "messages": mensagens})
        try:
            return dados["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ErroIA("Resposta inesperada da OpenRouter (chat).") from e

    def escolher(
        self,
        state: str,
        opcoes: dict[str, str],
        instrucoes: str,
        modelo: str = "typesafe/jev-1.13",
    ) -> tuple[str, float]:
        corpo = {
            "model": modelo,
            "state": state,
            "questions": {"nicho": {"type": "choice", "instructions": instrucoes, "criteria": opcoes}},
        }
        dados = self._post(URL_DECISIONS, corpo)
        try:
            resposta = dados["answers"]["nicho"]
            return resposta["choice"], float(resposta["confidence"])
        except (KeyError, TypeError, ValueError) as e:
            raise ErroIA("Resposta inesperada da OpenRouter (decisions).") from e
