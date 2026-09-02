"""Servidor local do Gerenciador de Dados QualiÔnibus.

Uso:
    python dev_server.py

Depois abra http://localhost:8767/ no navegador.

A lógica de rotas fica em `servidor.py`, compartilhada com a função
serverless da Vercel (`api/index.py`) - ver o comentário lá."""

from __future__ import annotations

import webbrowser
from http.server import ThreadingHTTPServer
from threading import Timer

from servidor import Handler

PORTA_PREFERIDA = 8767


def escolher_porta(preferida: int) -> int:
    import socket
    for porta in range(preferida, preferida + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", porta))
                return porta
            except OSError:
                continue
    raise RuntimeError("Nao foi possivel encontrar uma porta livre.")


def main():
    porta = escolher_porta(PORTA_PREFERIDA)
    url = f"http://127.0.0.1:{porta}/"
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    print("=" * 70)
    print(" Gerenciador de Dados QualiÔnibus - servidor local")
    print(f" Abrindo {url} no navegador...")
    print(" Para encerrar, feche esta janela ou pressione Ctrl+C.")
    print("=" * 70)
    Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
