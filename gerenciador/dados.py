"""Acesso ao Supabase para o Gerenciador de Dados: listar edições, ler e
editar linhas das tabelas (por edição), e (mais adiante) exportar/importar
planilhas. Todas as consultas usam a service role key (bypassa RLS) - o
mesmo padrão das outras 3 ferramentas do pipeline."""

from __future__ import annotations

import os
from typing import Any, Optional

from supabase import Client, create_client

_supabase_cliente: Optional[Client] = None


def _supabase_client() -> Client:
    global _supabase_cliente
    if _supabase_cliente is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _supabase_cliente = create_client(url, key)
    return _supabase_cliente


# As 5 primeiras sao totalmente editaveis (consulta, edicao de linha,
# exportar/importar planilha); as 2 ultimas sao so' leitura (auditoria) -
# decisão confirmada com o usuário na definição do escopo desta ferramenta.
TABELAS_EDITAVEIS = [
    "edicoes",
    "erro_amostral",
    "respostas_padrao",
    "respostas_especifico",
    "respostas_brutas",
]
TABELAS_SOMENTE_LEITURA = ["remapeamentos", "processing_log"]
TODAS_TABELAS = TABELAS_EDITAVEIS + TABELAS_SOMENTE_LEITURA

# "edicoes" nao tem coluna edicao_id - ela E' a edição, entao o filtro por
# edição usa a propria coluna "id". Todas as outras tabelas se relacionam
# com a edição through "edicao_id".
_COLUNA_FILTRO_PADRAO = "edicao_id"
_COLUNAS_FILTRO_ESPECIAIS = {"edicoes": "id"}

# Colunas de cada tabela, na ordem em que devem aparecer nas grades/planilha
# (id e edicao_id ficam de fora aqui - sao tratados a parte, nao sao
# editaveis pelo usuario). None = "descobrir dinamicamente" (nao usado por
# enquanto, todas as tabelas tem esquema fixo conhecido).
COLUNAS_POR_TABELA: dict[str, list[str]] = {
    "edicoes": ["sistema", "ano", "semestre", "criado_em"],
    "erro_amostral": [
        "cat_subpop", "categoria_variavel", "variavel", "tipo_var",
        "media", "erro_padrao", "erro", "li", "ls",
    ],
    "respostas_padrao": [
        "modulo", "grupo", "pergunta_prefixo", "pergunta_descricao", "pergunta_grafico",
        "resposta_prefixo", "resposta_descricao", "resposta_grafico",
        "resposta_quantidade", "resposta_proporcional", "resposta_valida_proporcional",
        "nota_5pontos", "nota_5pontos_normalizada", "nota_10pontos", "nota_10pontos_normalizada",
        "erro",
    ],
    "respostas_especifico": [
        "subpopulacao", "modulo", "grupo", "pergunta_prefixo", "pergunta_descricao", "pergunta_grafico",
        "resposta_prefixo", "resposta_descricao", "resposta_grafico",
        "resposta_quantidade", "resposta_proporcional", "resposta_valida_proporcional",
        "nota_5pontos", "nota_5pontos_normalizada", "nota_10pontos", "nota_10pontos_normalizada",
        "erro",
    ],
    "respostas_brutas": ["subpopulacao", "respostas"],
    "remapeamentos": [
        "registrado_em", "usuario", "pergunta_prefixo", "pergunta_descricao",
        "codigo_especifico", "resposta_especifica_descricao", "quantidade_respondentes",
        "codigo_padrao", "resposta_padrao_descricao",
    ],
    "processing_log": ["processado_em", "usuario", "base", "registro"],
}

# Colunas que a linha editada por linha ("editar uma linha especifica direto
# na aplicacao") pode alterar - as mesmas de COLUNAS_POR_TABELA, exceto
# onde a edicao manual nao faz sentido: campos de auditoria automatica
# (registrado_em/criado_em/processado_em) e a propria chave de agrupamento
# (edicao/subpopulacao) que, se mudada, "moveria" a linha pra outro grupo -
# mais seguro exigir excluir+recriar (via importar planilha) pra isso.
COLUNAS_EDITAVEIS_POR_TABELA: dict[str, list[str]] = {
    "edicoes": ["sistema", "ano", "semestre"],
    "erro_amostral": [
        "cat_subpop", "categoria_variavel", "variavel", "tipo_var",
        "media", "erro_padrao", "erro", "li", "ls",
    ],
    "respostas_padrao": [
        "modulo", "grupo", "pergunta_prefixo", "pergunta_descricao", "pergunta_grafico",
        "resposta_prefixo", "resposta_descricao", "resposta_grafico",
        "resposta_quantidade", "resposta_proporcional", "resposta_valida_proporcional",
        "nota_5pontos", "nota_5pontos_normalizada", "nota_10pontos", "nota_10pontos_normalizada",
        "erro",
    ],
    "respostas_especifico": [
        "modulo", "grupo", "pergunta_prefixo", "pergunta_descricao", "pergunta_grafico",
        "resposta_prefixo", "resposta_descricao", "resposta_grafico",
        "resposta_quantidade", "resposta_proporcional", "resposta_valida_proporcional",
        "nota_5pontos", "nota_5pontos_normalizada", "nota_10pontos", "nota_10pontos_normalizada",
        "erro",
    ],
    "respostas_brutas": ["respostas"],
}

TAMANHO_PAGINA_PADRAO = 200


def listar_edicoes() -> list[dict]:
    """Todas as edições, mais recentes primeiro - alimenta o seletor de
    edição no topo da ferramenta."""
    sb = _supabase_client()
    resp = (
        sb.table("edicoes")
        .select("id, sistema, ano, semestre, criado_em")
        .order("ano", desc=True)
        .order("semestre", desc=True)
        .order("sistema")
        .execute()
    )
    return resp.data or []


def _coluna_filtro(nome_tabela: str) -> str:
    return _COLUNAS_FILTRO_ESPECIAIS.get(nome_tabela, _COLUNA_FILTRO_PADRAO)


def contar_linhas(nome_tabela: str, edicao_id: int) -> int:
    if nome_tabela not in TODAS_TABELAS:
        raise ValueError(f"Tabela desconhecida: {nome_tabela}")
    sb = _supabase_client()
    coluna = _coluna_filtro(nome_tabela)
    valor = edicao_id if coluna == "edicao_id" else int(edicao_id)
    resp = sb.table(nome_tabela).select("id", count="exact").eq(coluna, valor).limit(1).execute()
    return resp.count or 0


def ler_pagina_tabela(
    nome_tabela: str, edicao_id: int, pagina: int = 0, tamanho_pagina: int = TAMANHO_PAGINA_PADRAO
) -> dict[str, Any]:
    """Uma página de linhas de `nome_tabela` para `edicao_id`, mais o total
    de linhas (pra a interface montar a paginação) - usado tanto pra
    mostrar a grade na tela quanto, paginando até o fim, pra montar a
    planilha de exportação."""
    if nome_tabela not in TODAS_TABELAS:
        raise ValueError(f"Tabela desconhecida: {nome_tabela}")
    sb = _supabase_client()
    coluna = _coluna_filtro(nome_tabela)
    total = contar_linhas(nome_tabela, edicao_id)
    inicio = pagina * tamanho_pagina
    fim = inicio + tamanho_pagina - 1
    resp = (
        sb.table(nome_tabela)
        .select("*")
        .eq(coluna, edicao_id)
        .order("id")
        .range(inicio, fim)
        .execute()
    )
    return {
        "linhas": resp.data or [],
        "total": total,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "colunas": COLUNAS_POR_TABELA.get(nome_tabela, []),
        "colunasEditaveis": COLUNAS_EDITAVEIS_POR_TABELA.get(nome_tabela, []),
    }


def atualizar_linha(nome_tabela: str, linha_id: int, valores: dict[str, Any]) -> dict:
    """Atualiza (por `id`) só as colunas em `COLUNAS_EDITAVEIS_POR_TABELA`
    pra essa tabela - qualquer outra chave em `valores` é ignorada, tanto
    pra nao deixar editar campos de auditoria/chave quanto pra bloquear
    tentativa de sobrescrever `id`/`edicao_id`."""
    if nome_tabela not in COLUNAS_EDITAVEIS_POR_TABELA:
        raise ValueError(f"Tabela nao editavel: {nome_tabela}")
    colunas_permitidas = set(COLUNAS_EDITAVEIS_POR_TABELA[nome_tabela])
    valores_filtrados = {k: v for k, v in valores.items() if k in colunas_permitidas}
    if not valores_filtrados:
        raise ValueError("Nenhum campo editável foi informado.")
    sb = _supabase_client()
    resp = sb.table(nome_tabela).update(valores_filtrados).eq("id", linha_id).execute()
    if not resp.data:
        raise ValueError("Linha não encontrada (id pode ter mudado ou já ter sido removida).")
    return resp.data[0]
