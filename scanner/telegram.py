"""🤖 Alertas no Telegram (stdlib apenas, sem dependências).

Dispara mensagens quando o radar **recomenda** uma entrada (nova) e quando ela
**liquida** (green/red/sem dado). Tudo via urllib da stdlib.

Configuração (variáveis de ambiente):
    TELEGRAM_BOT_TOKEN   token do bot (criado no @BotFather) — sem token nada envia
    TELEGRAM_CHAT_ID     chat/grupo/canal que recebe as mensagens (ex.: 123456789)
    TELEGRAM_SITE_URL    link do site nos alertas (opcional; tem default)

Local:     export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...
GitHub Pages: defina os secrets TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no repo
    (Settings -> Secrets and variables -> Actions). O workflow pages.yml já os
    repassa para o build.py — sem secrets, o build roda normal e nada é enviado.

Falhas silenciosas: erro de rede/API é logado como warning e NUNCA derruba o
build nem o servidor.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger("scanner.telegram")

API = "https://api.telegram.org/bot{token}/sendMessage"
SITE_URL = os.environ.get(
    "TELEGRAM_SITE_URL", "https://halleybr.github.io/livebetscanner/"
)

_STATUS_META = {
    "green": ("✅", "GREEN"),
    "red": ("❌", "RED"),
    "n_d": ("⚪", "SEM DADO"),
}


def enabled() -> bool:
    """True se token e chat estão configurados (senão nada é enviado)."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_message(text: str) -> bool:
    """Envia uma mensagem de texto para o chat configurado. Nunca levanta."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info(
            "Telegram não configurado (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) — pulando alerta"
        )
        return False
    body = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        API.format(token=token),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            ok = resp.status == 200
            if not ok:
                log.warning("Telegram: HTTP %s", resp.status)
            return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram: falha ao enviar alerta: %s", exc)
        return False


def notify_events(events: list[dict]) -> None:
    """Dispara os alertas da lista de eventos do ledger (new/settled)."""
    for ev in events or []:
        entry = ev.get("entry") or {}
        try:
            if ev.get("kind") == "new":
                notify_new_entry(entry)
            elif ev.get("kind") == "settled":
                notify_settled(entry)
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram: falha ao notificar evento %s: %s", ev.get("kind"), exc)


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def _market_label(entry: dict) -> str:
    return str(entry.get("market") or entry.get("corner_market") or "?")


def _time_of(iso: str | None) -> str:
    """'2026-08-15T20:35:12+00:00' -> '20:35' (hora local do envio)."""
    if not iso:
        return ""
    try:
        return iso[11:16]
    except (TypeError, IndexError):
        return ""


def _context(entry: dict) -> str:
    """Contexto da entrada: LPS, minuto, odd, probabilidade e confiança."""
    parts = []
    if entry.get("lps_at_entry") is not None:
        parts.append(f"LPS {entry['lps_at_entry']:g}")
    if entry.get("minute_at_entry") is not None:
        parts.append(f"{entry['minute_at_entry']}'")
    if entry.get("odd") is not None:
        parts.append(f"@{entry['odd']:g}")
    if entry.get("prob") is not None:
        parts.append(f"{entry['prob']:.0%}")
    if entry.get("confidence"):
        parts.append(f"Confiança {entry['confidence']}")
    return " · ".join(parts)


def notify_new_entry(entry: dict) -> bool:
    """Alerta quando o radar recomenda uma entrada nova."""
    if not enabled():
        return False
    text = (
        "🎯 NOVA ENTRADA\n"
        f"{_market_label(entry)}\n"
        f"{entry.get('home')} x {entry.get('away')}\n"
        f"📌 {entry.get('league')}\n"
        f"{_context(entry)}\n"
        f"🔗 {SITE_URL}"
    )
    return send_message(text)


def notify_settled(entry: dict) -> bool:
    """Alerta quando a partida termina e a dica liquida (green/red/sem dado)."""
    if not enabled():
        return False
    icon, label = _STATUS_META.get(
        str(entry.get("status")), ("ℹ️", str(entry.get("status") or "?"))
    )
    line = f"final {entry.get('final_score')}" if entry.get("final_score") else ""
    entered = f"entrou {_time_of(entry.get('entered_at'))}"
    detail = " · ".join(p for p in (line, entered) if p)
    text = (
        f"{icon} {label}\n"
        f"{_market_label(entry)}\n"
        f"{entry.get('home')} x {entry.get('away')}\n"
        f"{detail}\n"
        f"🔗 {SITE_URL}"
    )
    return send_message(text)
