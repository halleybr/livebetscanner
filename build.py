#!/usr/bin/env python3
"""Gera `api/scanner.json` — modo estático para o GitHub Pages.

O GitHub Pages não roda o servidor Python (`server.py`). Este script executa
um ciclo completo (poll RoboBet + enriquecimento SokkerPRO + LIVE PRESSURE
SCORE) e grava um JSON com o MESMO formato da rota `/api/scanner`, para o
GitHub Actions gerar periodicamente e publicar como site estático.

O frontend tenta primeiro `api/scanner.json` e, se não existir (servidor
local), cai na API ao vivo `/api/scanner`.

Uso:
    python build.py            # escreve api/scanner.json

Configuração (variáveis de ambiente):
    MIN_LPS=70                filtro mínimo do Live Pressure Score
    TOP_N=10                  máximo de jogos exibidos
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   alertas no Telegram (opcional)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scanner import robobet, sokkerpro, telegram
from scanner.entries import EntryTracker
from scanner.scorer import classify
from server import _enrich_one  # reutiliza o casamento/enriquecimento do servidor

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "api" / "scanner.json"
ENTRIES_FILE = ROOT / "data" / "entries.json"  # histórico green/red (commitado pelo workflow)

MIN_LPS = float(os.environ.get("MIN_LPS", "70"))
TOP_N = int(os.environ.get("TOP_N", "10"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    sources = {
        "robobet": "error",
        "stats": "unknown",
        "provider": "sokkerpro",
        "last_error": None,
    }

    # 1) Poll do RoboBet (mesma lógica do server.py; falha não derruba o build).
    payload = robobet.fetch_today()
    matches = robobet.extract_live_matches(payload)
    scored = [classify(m) for m in matches]

    if payload is None:
        sources["last_error"] = "Falha ao buscar dados do RoboBet"
        print("RoboBet: falha na atualização")
    else:
        sources["robobet"] = "ok"
        # 2) Enriquecimento SokkerPRO (uma única chamada, como no servidor).
        try:
            fixtures = sokkerpro.fetch_livescores()
            if fixtures is None:
                sources["stats"] = "error"
                sources["last_error"] = "Falha ao buscar estatísticas do SokkerPRO (N/D)"
                print("SokkerPRO: falha na atualização")
            else:
                enriched = 0
                for m in scored:
                    if _enrich_one(m, fixtures):
                        enriched += 1
                sources["stats"] = "ok"
                print(f"SokkerPRO: {enriched} partidas enriquecidas")
        except Exception as exc:  # noqa: BLE001
            sources["stats"] = "error"
            sources["last_error"] = str(exc)[:300]
            print(f"SokkerPRO: erro no enriquecimento: {exc}")

    # 3) Ordena e filtra (idêntico à rota /api/scanner).
    scored.sort(key=lambda m: m["lps"], reverse=True)
    opportunities = [m for m in scored if m["lps"] >= MIN_LPS][:TOP_N]

    # 3b) Registro de entradas (histórico green/red). Carrega o ledger que o
    #     workflow commitou no run anterior, evolui e salva de volta — assim o
    #     histórico sobrevive entre os builds do GitHub Pages.
    finished = robobet.extract_finished_matches(payload) if payload is not None else []
    tracker = EntryTracker(ENTRIES_FILE, MIN_LPS)
    events = tracker.observe(opportunities, finished)
    tracker.save()
    telegram.notify_events(events)

    data = {
        "summary": {
            "monitored": len(scored),
            "opportunities": len(opportunities),
            "updated_at": _now_iso(),
        },
        "sources": sources,
        "opportunities": opportunities,
        "entries": tracker.snapshot(),
        "live_count": len(scored),
        "min_lps": MIN_LPS,
        "config": {
            # No Pages o JSON só muda a cada execução do workflow (a cada 5 min);
            # o frontend consulta a cada 30 s para pegar atualizações novas assim
            # que o deploy termina.
            "poll_seconds": 30,
            "enrich_seconds": 300,
            "stats_enabled": True,
            "stats_provider": "sokkerpro",
            "top_n": TOP_N,
        },
        "generated_at": _now_iso(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {len(opportunities)} oportunidades de {len(scored)} jogos (LPS>={MIN_LPS:g}) -> {OUT}")


if __name__ == "__main__":
    main()
