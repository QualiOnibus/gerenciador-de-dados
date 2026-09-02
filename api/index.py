"""Ponto de entrada da função serverless da Vercel - ver o comentário
equivalente em `api/index.py` do Gerador de Relatório pra entender por que
é uma subclasse vazia reexportando `Handler` em vez de um alias direto."""

from __future__ import annotations

import sys
from pathlib import Path

PASTA_RAIZ = Path(__file__).resolve().parent.parent
if str(PASTA_RAIZ / "app_web") not in sys.path:
    sys.path.insert(0, str(PASTA_RAIZ / "app_web"))

from servidor import Handler as _Handler  # noqa: E402


class handler(_Handler):  # noqa: N801 - nome exigido pela Vercel
    pass
