"""Acesso ao Supabase para o Gerenciador de Dados: listar edições, ler e
editar linhas das tabelas (por edição), e (mais adiante) exportar/importar
planilhas. Todas as consultas usam a service role key (bypassa RLS) - o
mesmo padrão das outras 3 ferramentas do pipeline."""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
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

# Colunas por onde da pra filtrar a consulta (dropdowns na interface) -
# so' as que fazem sentido pra "estreitar" uma tabela grande (ex.: uma
# subpopulacao ou pergunta especifica), nao qualquer coluna.
COLUNAS_FILTRAVEIS_POR_TABELA: dict[str, list[str]] = {
    "erro_amostral": ["cat_subpop", "categoria_variavel", "variavel"],
    "respostas_padrao": ["modulo", "grupo", "pergunta_prefixo"],
    "respostas_especifico": ["subpopulacao", "modulo", "grupo", "pergunta_prefixo"],
    "respostas_brutas": ["subpopulacao"],
    "remapeamentos": ["pergunta_prefixo"],
}

TAMANHO_PAGINA_PADRAO = 200
TAMANHO_LOTE_EXPORTACAO = 1000


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


def _aplicar_filtros(query, nome_tabela: str, filtros: Optional[dict[str, str]]):
    """Acrescenta um .eq() por filtro valido em `filtros` - ignora
    silenciosamente qualquer coluna que nao esteja em
    COLUNAS_FILTRAVEIS_POR_TABELA (nunca deixa filtrar por coluna
    arbitraria vinda da query string) e qualquer valor vazio."""
    if not filtros:
        return query
    permitidas = set(COLUNAS_FILTRAVEIS_POR_TABELA.get(nome_tabela, []))
    for coluna, valor in filtros.items():
        if coluna not in permitidas or valor in (None, ""):
            continue
        query = query.eq(coluna, valor)
    return query


def contar_linhas(nome_tabela: str, edicao_id: int, filtros: Optional[dict[str, str]] = None) -> int:
    if nome_tabela not in TODAS_TABELAS:
        raise ValueError(f"Tabela desconhecida: {nome_tabela}")
    sb = _supabase_client()
    coluna = _coluna_filtro(nome_tabela)
    query = sb.table(nome_tabela).select("id", count="exact").eq(coluna, edicao_id)
    query = _aplicar_filtros(query, nome_tabela, filtros)
    resp = query.limit(1).execute()
    return resp.count or 0


def ler_pagina_tabela(
    nome_tabela: str,
    edicao_id: int,
    pagina: int = 0,
    tamanho_pagina: int = TAMANHO_PAGINA_PADRAO,
    filtros: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Uma página de linhas de `nome_tabela` para `edicao_id` (com os
    filtros opcionais aplicados), mais o total de linhas que batem com o
    filtro (pra a interface montar a paginação)."""
    if nome_tabela not in TODAS_TABELAS:
        raise ValueError(f"Tabela desconhecida: {nome_tabela}")
    sb = _supabase_client()
    coluna = _coluna_filtro(nome_tabela)
    total = contar_linhas(nome_tabela, edicao_id, filtros)
    inicio = pagina * tamanho_pagina
    fim = inicio + tamanho_pagina - 1
    query = sb.table(nome_tabela).select("*").eq(coluna, edicao_id)
    query = _aplicar_filtros(query, nome_tabela, filtros)
    resp = query.order("id").range(inicio, fim).execute()
    return {
        "linhas": resp.data or [],
        "total": total,
        "pagina": pagina,
        "tamanhoPagina": tamanho_pagina,
        "colunas": COLUNAS_POR_TABELA.get(nome_tabela, []),
        "colunasEditaveis": COLUNAS_EDITAVEIS_POR_TABELA.get(nome_tabela, []),
        "colunasFiltraveis": COLUNAS_FILTRAVEIS_POR_TABELA.get(nome_tabela, []),
    }


def listar_valores_distintos(nome_tabela: str, coluna: str, edicao_id: int) -> list[str]:
    """Valores distintos de `coluna` (uma das listadas em
    COLUNAS_FILTRAVEIS_POR_TABELA) pra esta edição - alimenta os dropdowns
    de filtro na interface. A API REST do Supabase nao tem um DISTINCT
    direto, entao a deduplicacao e' feita aqui, paginando a tabela
    inteira - as tabelas em questao cabem tranquilamente em memoria por
    edição (nunca mais que baixas dezenas de milhares de linhas)."""
    if coluna not in COLUNAS_FILTRAVEIS_POR_TABELA.get(nome_tabela, []):
        raise ValueError(f"Coluna nao filtravel: {nome_tabela}.{coluna}")
    sb = _supabase_client()
    coluna_filtro = _coluna_filtro(nome_tabela)
    valores: set[str] = set()
    pagina = 0
    while True:
        inicio = pagina * TAMANHO_LOTE_EXPORTACAO
        resp = (
            sb.table(nome_tabela)
            .select(coluna)
            .eq(coluna_filtro, edicao_id)
            .range(inicio, inicio + TAMANHO_LOTE_EXPORTACAO - 1)
            .execute()
        )
        linhas = resp.data or []
        for linha in linhas:
            valor = linha.get(coluna)
            if valor not in (None, ""):
                valores.add(valor)
        if len(linhas) < TAMANHO_LOTE_EXPORTACAO:
            break
        pagina += 1
    return sorted(valores, key=str)


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


def _slug_arquivo(texto: str) -> str:
    """minúsculo, sem acentuação, espaços/pontuação viram "_" - mesma
    convenção usada pelo Gerador de Relatório pros nomes de arquivo
    exportados, aqui usada pro nome da pasta de cada edição dentro do
    .zip da base completa."""
    import re
    import unicodedata

    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def _colunas_exportacao(nome_tabela: str) -> list[str]:
    """Colunas do CSV, na ordem: id, edicao_id (exceto pra "edicoes", que
    nao tem essa coluna - "id" ja' e' a própria edição), e depois as
    colunas de conteúdo de COLUNAS_POR_TABELA."""
    base = ["id"] if nome_tabela == "edicoes" else ["id", "edicao_id"]
    return base + COLUNAS_POR_TABELA.get(nome_tabela, [])


def _gerar_linhas_completas(nome_tabela: str, edicao_id: int, filtros: Optional[dict[str, str]] = None):
    """Gera, em lotes de TAMANHO_LOTE_EXPORTACAO, todas as linhas de
    `nome_tabela` para `edicao_id` que batem com `filtros` - usado pra
    exportar CSV sem carregar a tabela inteira de uma vez na memória."""
    sb = _supabase_client()
    coluna_filtro = _coluna_filtro(nome_tabela)
    pagina = 0
    while True:
        inicio = pagina * TAMANHO_LOTE_EXPORTACAO
        query = sb.table(nome_tabela).select("*").eq(coluna_filtro, edicao_id)
        query = _aplicar_filtros(query, nome_tabela, filtros)
        resp = query.order("id").range(inicio, inicio + TAMANHO_LOTE_EXPORTACAO - 1).execute()
        linhas = resp.data or []
        for linha in linhas:
            yield linha
        if len(linhas) < TAMANHO_LOTE_EXPORTACAO:
            break
        pagina += 1


def gerar_csv_tabela(nome_tabela: str, edicao_id: int, filtros: Optional[dict[str, str]] = None) -> bytes:
    """CSV (UTF-8 com BOM, pra abrir certo com acentuação no Excel) de
    todas as linhas de `nome_tabela` para `edicao_id`, com os filtros
    opcionais aplicados. Campos jsonb (ex.: `respostas_brutas.respostas`)
    viram uma string JSON numa única célula."""
    if nome_tabela not in TODAS_TABELAS:
        raise ValueError(f"Tabela desconhecida: {nome_tabela}")
    colunas = _colunas_exportacao(nome_tabela)
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=colunas, extrasaction="ignore")
    escritor.writeheader()
    for linha in _gerar_linhas_completas(nome_tabela, edicao_id, filtros):
        linha_formatada = {}
        for c in colunas:
            valor = linha.get(c)
            if isinstance(valor, (dict, list)):
                valor = json.dumps(valor, ensure_ascii=False)
            linha_formatada[c] = valor
        escritor.writerow(linha_formatada)
    return buffer.getvalue().encode("utf-8-sig")


def gerar_zip_edicao(edicao_id: int) -> bytes:
    """Um .zip com um .csv por tabela (as 7), todas as linhas dessa
    edição - "baixar tudo desta edição", sem filtro nenhum."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome_tabela in TODAS_TABELAS:
            zf.writestr(f"{nome_tabela}.csv", gerar_csv_tabela(nome_tabela, edicao_id))
    return buffer.getvalue()


def gerar_zip_completo() -> bytes:
    """Toda a base: um .zip com uma pasta por edição, e dentro dela um
    .csv por tabela (as 7) - "baixar a base de dados completa". Pode
    demorar/pesar dependendo de quantas edições existirem (respostas
    específico/brutas são as tabelas mais pesadas por edição) - ainda
    assim cabe tranquilamente no limite de 60s da função serverless com
    o número de edições que a pesquisa acumula hoje (uma a duas por
    semestre)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for edicao in listar_edicoes():
            pasta = _slug_arquivo(f"{edicao['sistema']}_{edicao['ano']}_{edicao['semestre']}_id{edicao['id']}")
            for nome_tabela in TODAS_TABELAS:
                zf.writestr(f"{pasta}/{nome_tabela}.csv", gerar_csv_tabela(nome_tabela, edicao["id"]))
    return buffer.getvalue()

# --- Gerenciamento dos modelos (relatório/síntese) no Supabase Storage ---
# Mesmo bucket e mesmos nomes de arquivo que o Gerador de Relatório lê
# (`BUCKET_MODELOS`/`NOME_TEMPLATE_STORAGE`/`NOME_SINTESE_STORAGE` em
# app_web/servidor.py de lá) - atualizar aqui é o que "publica" um modelo
# novo pras próximas gerações de relatório/síntese, sem precisar mexer no
# código. O modelo do relatório principal é comprimido em gzip no Storage
# (arquivo grande, ~15MB descomprimido); a síntese fica sem compressão.
BUCKET_MODELOS = "modelos-relatorio"
MODELOS_STORAGE: dict[str, str] = {
    "relatorio": "relatorio_versao_3_modelo.svg.gz",
    "sintese": "sintese_modelo.svg",
}


def listar_info_modelos() -> dict[str, Optional[dict]]:
    """Metadados (tamanho em bytes, data da última atualização) de cada
    modelo hoje publicado no Storage - None pra um modelo que ainda não
    foi publicado por aqui (o Gerador de Relatório então usa o modelo
    embutido no próprio repositório dele, como reserva)."""
    sb = _supabase_client()
    arquivos = sb.storage.from_(BUCKET_MODELOS).list()
    por_nome = {a.get("name"): a for a in arquivos}
    info: dict[str, Optional[dict]] = {}
    for chave, nome_arquivo in MODELOS_STORAGE.items():
        arquivo = por_nome.get(nome_arquivo)
        if arquivo is None:
            info[chave] = None
            continue
        metadata = arquivo.get("metadata") or {}
        info[chave] = {
            "tamanhoBytes": metadata.get("size"),
            "atualizadoEm": arquivo.get("updated_at"),
        }
    return info


def gerar_url_upload_modelo(chave_modelo: str) -> dict:
    """Cria uma signed upload URL pro modelo `chave_modelo` ("relatorio" ou
    "sintese"): o navegador sobe o arquivo direto pro Supabase Storage com
    essa URL, sem passar pelo corpo desta função serverless (limite de
    4.5MB da Vercel, menor que o modelo do relatório comprimido). Com
    upsert, então reenviar sobrescreve o modelo anterior no mesmo lugar -
    é assim que o Gerador de Relatório sempre lê "o modelo atual"."""
    if chave_modelo not in MODELOS_STORAGE:
        raise ValueError("Modelo inválido.")
    from storage3.types import CreateSignedUploadUrlOptions

    nome_arquivo = MODELOS_STORAGE[chave_modelo]
    sb = _supabase_client()
    resultado = sb.storage.from_(BUCKET_MODELOS).create_signed_upload_url(
        nome_arquivo, CreateSignedUploadUrlOptions(upsert="true")
    )
    return {"url": resultado["signed_url"], "caminho": nome_arquivo}
