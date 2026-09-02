"""Handler HTTP do Gerenciador de Dados QualiÔnibus - compartilhado entre o
servidor local (`dev_server.py`) e a função serverless da Vercel
(`api/index.py`), seguindo o mesmo padrão do Gerador de Relatório (ver o
comentário lá em `api/index.py` pra entender por que é um único ponto de
entrada em vez de um arquivo por rota)."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlsplit

PASTA_APP_WEB = Path(__file__).resolve().parent
PASTA_RAIZ = PASTA_APP_WEB.parent
PASTA_PUBLIC = PASTA_RAIZ / "public"

if str(PASTA_RAIZ) not in sys.path:
    sys.path.insert(0, str(PASTA_RAIZ))
from gerenciador import dados as dm  # noqa: E402

from auth import (  # noqa: E402
    cookie_logout,
    criar_cookie_sessao,
    senha_correta,
    sessao_valida,
)


class Handler(BaseHTTPRequestHandler):
    server_version = "GerenciadorDeDadosQualionibus/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _enviar_json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _servir_arquivo(self, caminho: Path, content_type: str) -> None:
        if not caminho.exists():
            self.send_error(404, f"Arquivo nao encontrado: {caminho.name}")
            return
        dados_arquivo = caminho.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(dados_arquivo)))
        self.end_headers()
        self.wfile.write(dados_arquivo)

    def _enviar_binario(self, conteudo: bytes, content_type: str, nome_arquivo: str) -> None:
        """Devolve `conteudo` como download (Content-Disposition: attachment)
        - usado pelos CSVs e .zip de exportacao."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(conteudo)))
        self.send_header("Content-Disposition", f'attachment; filename="{nome_arquivo}"')
        self.end_headers()
        self.wfile.write(conteudo)

    def _rota_efetiva(self, partes, query) -> str:
        """Ver o comentário equivalente em servidor.py do Gerador de
        Relatório: local roteia por `self.path`, na Vercel o rewrite manda
        a rota de verdade pela query string ("?rota=...")."""
        if "rota" in query:
            return query["rota"][0]
        if partes.path.startswith("/api/"):
            return partes.path[len("/api/"):]
        return ""

    def ler_corpo_json(self) -> Optional[dict]:
        tamanho = int(self.headers.get("Content-Length", "0"))
        bruto = self.rfile.read(tamanho) if tamanho else b"{}"
        try:
            return json.loads(bruto.decode("utf-8"))
        except Exception as e:
            self._enviar_json(400, {"ok": False, "erro": f"Corpo da requisicao invalido: {e}"})
            return None

    def do_GET(self):  # noqa: N802
        partes = urlsplit(self.path)
        if partes.path in ("/", "/index.html"):
            self._servir_arquivo(PASTA_PUBLIC / "index.html", "text/html; charset=utf-8")
            return
        if partes.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        query = parse_qs(partes.query)
        rota = self._rota_efetiva(partes, query)

        if rota == "sessao":
            self._rota_sessao()
            return

        if not sessao_valida(self.headers.get("Cookie")):
            self._enviar_json(401, {"ok": False, "erro": "Sessao expirada. Faca login novamente.", "precisaLogin": True})
            return

        if rota == "edicoes":
            self._rota_edicoes()
        elif rota == "modelos":
            self._rota_modelos()
        elif rota == "modelos/download-url":
            self._rota_modelos_download_url(query)
        elif rota == "tabela":
            self._rota_tabela(query)
        elif rota == "tabela/valores":
            self._rota_tabela_valores(query)
        elif rota == "tabela/csv":
            self._rota_tabela_csv(query)
        elif rota == "exportar/edicao":
            self._rota_exportar_edicao(query)
        elif rota == "exportar/completo":
            self._rota_exportar_completo()
        else:
            self.send_error(404, "Rota nao encontrada")

    def do_POST(self):  # noqa: N802
        partes = urlsplit(self.path)
        query = parse_qs(partes.query)
        rota = self._rota_efetiva(partes, query)

        if rota == "tabela/csv/importar":
            if not sessao_valida(self.headers.get("Cookie")):
                self._enviar_json(401, {"ok": False, "erro": "Sessao expirada. Faca login novamente.", "precisaLogin": True})
                return
            self._rota_importar_csv(query)
            return

        corpo = self.ler_corpo_json()
        if corpo is None:
            return

        if rota == "login":
            self._rota_login(corpo)
            return
        if rota == "logout":
            self._rota_logout()
            return

        if not sessao_valida(self.headers.get("Cookie")):
            self._enviar_json(401, {"ok": False, "erro": "Sessao expirada. Faca login novamente.", "precisaLogin": True})
            return

        if rota == "tabela/linha":
            self._rota_atualizar_linha(corpo)
        elif rota == "modelos/upload-url":
            self._rota_modelos_upload_url(corpo)
        else:
            self.send_error(404, "Rota nao encontrada")

    def _rota_login(self, corpo: dict) -> None:
        senha = corpo.get("senha") or ""
        if not senha_correta(senha):
            self._enviar_json(401, {"ok": False, "erro": "Senha incorreta."})
            return
        self._enviar_json(200, {"ok": True}, {"Set-Cookie": criar_cookie_sessao()})

    def _rota_logout(self) -> None:
        self._enviar_json(200, {"ok": True}, {"Set-Cookie": cookie_logout()})

    def _rota_sessao(self) -> None:
        self._enviar_json(200, {"ok": True, "autenticado": sessao_valida(self.headers.get("Cookie"))})

    def _rota_edicoes(self) -> None:
        try:
            edicoes = dm.listar_edicoes()
            self._enviar_json(200, {"ok": True, "edicoes": edicoes})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao consultar as edições: {e}"})

    def _filtros_da_query(self, query: dict, nome_tabela: str) -> dict:
        """Extrai da query string só as colunas listadas em
        COLUNAS_FILTRAVEIS_POR_TABELA pra essa tabela - o resto dos
        parametros (nome, edicaoId, pagina...) e' ignorado aqui."""
        colunas = dm.COLUNAS_FILTRAVEIS_POR_TABELA.get(nome_tabela, [])
        return {c: (query.get(c, [""])[0] or "").strip() for c in colunas if query.get(c, [""])[0]}

    def _rota_tabela(self, query: dict) -> None:
        nome_tabela = (query.get("nome", [""])[0] or "").strip()
        edicao_id_bruto = (query.get("edicaoId", [""])[0] or "").strip()
        pagina_bruta = (query.get("pagina", ["0"])[0] or "0").strip()
        if nome_tabela not in dm.TODAS_TABELAS:
            self._enviar_json(400, {"ok": False, "erro": "Tabela invalida ou nao informada."})
            return
        try:
            edicao_id = int(edicao_id_bruto)
            pagina = max(0, int(pagina_bruta))
        except ValueError:
            self._enviar_json(400, {"ok": False, "erro": "edicaoId/pagina invalidos."})
            return
        filtros = self._filtros_da_query(query, nome_tabela)
        try:
            resultado = dm.ler_pagina_tabela(nome_tabela, edicao_id, pagina, filtros=filtros)
            self._enviar_json(200, {"ok": True, **resultado})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao consultar {nome_tabela}: {e}"})

    def _rota_tabela_valores(self, query: dict) -> None:
        nome_tabela = (query.get("nome", [""])[0] or "").strip()
        coluna = (query.get("coluna", [""])[0] or "").strip()
        edicao_id_bruto = (query.get("edicaoId", [""])[0] or "").strip()
        try:
            edicao_id = int(edicao_id_bruto)
        except ValueError:
            self._enviar_json(400, {"ok": False, "erro": "edicaoId invalido."})
            return
        try:
            valores = dm.listar_valores_distintos(nome_tabela, coluna, edicao_id)
            self._enviar_json(200, {"ok": True, "valores": valores})
        except ValueError as e:
            self._enviar_json(400, {"ok": False, "erro": str(e)})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao consultar os valores: {e}"})

    def _rota_tabela_csv(self, query: dict) -> None:
        nome_tabela = (query.get("nome", [""])[0] or "").strip()
        edicao_id_bruto = (query.get("edicaoId", [""])[0] or "").strip()
        if nome_tabela not in dm.TODAS_TABELAS:
            self._enviar_json(400, {"ok": False, "erro": "Tabela invalida ou nao informada."})
            return
        try:
            edicao_id = int(edicao_id_bruto)
        except ValueError:
            self._enviar_json(400, {"ok": False, "erro": "edicaoId invalido."})
            return
        filtros = self._filtros_da_query(query, nome_tabela)
        try:
            csv_bytes = dm.gerar_csv_tabela(nome_tabela, edicao_id, filtros)
            self._enviar_binario(csv_bytes, "text/csv; charset=utf-8", f"{nome_tabela}_edicao{edicao_id}.csv")
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao exportar {nome_tabela}: {e}"})

    def _rota_exportar_edicao(self, query: dict) -> None:
        edicao_id_bruto = (query.get("edicaoId", [""])[0] or "").strip()
        try:
            edicao_id = int(edicao_id_bruto)
        except ValueError:
            self._enviar_json(400, {"ok": False, "erro": "edicaoId invalido."})
            return
        try:
            zip_bytes = dm.gerar_zip_edicao(edicao_id)
            self._enviar_binario(zip_bytes, "application/zip", f"edicao_{edicao_id}.zip")
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao exportar a edição: {e}"})

    def _rota_exportar_completo(self) -> None:
        try:
            zip_bytes = dm.gerar_zip_completo()
            self._enviar_binario(zip_bytes, "application/zip", "base_completa_qualionibus.zip")
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao exportar a base completa: {e}"})

    def _rota_atualizar_linha(self, corpo: dict) -> None:
        nome_tabela = (corpo.get("tabela") or "").strip()
        linha_id = corpo.get("id")
        valores = corpo.get("valores") or {}
        if nome_tabela not in dm.COLUNAS_EDITAVEIS_POR_TABELA:
            self._enviar_json(400, {"ok": False, "erro": "Tabela invalida ou nao editavel."})
            return
        try:
            linha_id = int(linha_id)
        except (TypeError, ValueError):
            self._enviar_json(400, {"ok": False, "erro": "Id da linha invalido."})
            return
        try:
            linha = dm.atualizar_linha(nome_tabela, linha_id, valores)
            self._enviar_json(200, {"ok": True, "linha": linha})
        except ValueError as e:
            self._enviar_json(200, {"ok": False, "erro": str(e)})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao atualizar a linha: {e}"})

    def _rota_modelos(self) -> None:
        try:
            info = dm.listar_info_modelos()
            self._enviar_json(200, {
                "ok": True,
                "modelos": info,
                "supabaseUrl": os.environ.get("SUPABASE_URL", ""),
                "supabaseAnonKey": os.environ.get("SUPABASE_ANON_KEY", ""),
            })
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao consultar os modelos: {e}"})

    def _rota_modelos_upload_url(self, corpo: dict) -> None:
        chave_modelo = (corpo.get("modelo") or "").strip()
        try:
            resultado = dm.gerar_url_upload_modelo(chave_modelo)
            self._enviar_json(200, {"ok": True, **resultado})
        except ValueError as e:
            self._enviar_json(400, {"ok": False, "erro": str(e)})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao preparar o envio: {e}"})

    def _rota_modelos_download_url(self, query: dict) -> None:
        chave_modelo = (query.get("modelo", [""])[0] or "").strip()
        try:
            resultado = dm.gerar_url_download_modelo(chave_modelo)
            self._enviar_json(200, {"ok": True, **resultado})
        except ValueError as e:
            self._enviar_json(400, {"ok": False, "erro": str(e)})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao preparar o download: {e}"})

    def _rota_importar_csv(self, query: dict) -> None:
        nome_tabela = (query.get("nome", [""])[0] or "").strip()
        edicao_id_bruto = (query.get("edicaoId", [""])[0] or "").strip()
        if nome_tabela not in dm.COLUNAS_EDITAVEIS_POR_TABELA:
            self._enviar_json(400, {"ok": False, "erro": "Tabela invalida ou nao editavel."})
            return
        try:
            edicao_id = int(edicao_id_bruto)
        except ValueError:
            self._enviar_json(400, {"ok": False, "erro": "edicaoId invalido."})
            return
        tamanho = int(self.headers.get("Content-Length", "0"))
        if tamanho <= 0:
            self._enviar_json(400, {"ok": False, "erro": "Arquivo vazio."})
            return
        if tamanho > 4_000_000:
            self._enviar_json(400, {"ok": False, "erro": "Arquivo grande demais (máx. ~4MB) - filtre a consulta antes de baixar/reenviar o CSV."})
            return
        conteudo = self.rfile.read(tamanho)
        try:
            resultado = dm.importar_csv_tabela(nome_tabela, edicao_id, conteudo)
            self._enviar_json(200, {"ok": True, **resultado})
        except ValueError as e:
            self._enviar_json(200, {"ok": False, "erro": str(e)})
        except Exception as e:
            self._enviar_json(200, {"ok": False, "erro": f"Erro ao importar o CSV: {e}"})

