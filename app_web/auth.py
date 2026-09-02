"""Autenticacao (senha de equipe compartilhada, sessao via cookie assinado)

Nao ha contas de usuario individuais - so uma senha unica (variavel de
ambiente APP_PASSWORD, configurada na Vercel) que da acesso a toda a
equipe. A sessao e' um cookie HttpOnly assinado (HMAC-SHA256, chave
derivada da propria senha) com validade de 30 dias - sem precisar de
tabela de sessoes no banco. Se APP_PASSWORD nao estiver configurada, o
login fica bloqueado para todo mundo (fail-closed).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

_COOKIE_SESSAO = "qualionibus_sessao"
_DURACAO_SESSAO_SEGUNDOS = 30 * 24 * 60 * 60  # 30 dias


def _chave_assinatura_sessao() -> bytes:
    senha = os.environ.get("APP_PASSWORD", "")
    return hashlib.sha256(f"qualionibus-auth::{senha}".encode("utf-8")).digest()


def _assinar_validade(validade: int) -> str:
    return hmac.new(
        _chave_assinatura_sessao(), str(validade).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def criar_cookie_sessao() -> str:
    validade = int(time.time()) + _DURACAO_SESSAO_SEGUNDOS
    token = f"{validade}.{_assinar_validade(validade)}"
    return (
        f"{_COOKIE_SESSAO}={token}; Path=/; Max-Age={_DURACAO_SESSAO_SEGUNDOS}; "
        "HttpOnly; Secure; SameSite=Lax"
    )


def cookie_logout() -> str:
    return f"{_COOKIE_SESSAO}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"


def _extrair_token_sessao(cabecalho_cookie):
    if not cabecalho_cookie:
        return None
    for parte in cabecalho_cookie.split(";"):
        parte = parte.strip()
        if parte.startswith(_COOKIE_SESSAO + "="):
            return parte[len(_COOKIE_SESSAO) + 1:]
    return None


def sessao_valida(cabecalho_cookie) -> bool:
    token = _extrair_token_sessao(cabecalho_cookie)
    if not token or "." not in token:
        return False
    validade_str, assinatura = token.split(".", 1)
    try:
        validade = int(validade_str)
    except ValueError:
        return False
    if validade < int(time.time()):
        return False
    return hmac.compare_digest(assinatura, _assinar_validade(validade))


def senha_correta(senha) -> bool:
    senha_configurada = os.environ.get("APP_PASSWORD", "")
    if not senha_configurada:
        return False
    return hmac.compare_digest(senha or "", senha_configurada)
