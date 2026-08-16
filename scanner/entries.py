"""📋 Registro das entradas recomendadas + liquidação green/red.

Somente as partidas que o radar **recomendou** (entraram na lista de
oportunidades, LPS >= MIN_LPS, com entrada ativa) são registradas. Quando a
pressão cai e a partida sai da lista, o registro NÃO é apagado — ele fica na
seção "Possíveis entradas" do site até o jogo terminar (ou por TTL).

Quando a partida termina (status "finished" no payload do RoboBet), o placar
final é usado para avaliar a dica:

  * Over 0.5 gol   -> green se total de gols final >= 1
  * Over 1.5 gols  -> green se total de gols final >= 2
  * Próximo gol    -> green se houve gol depois da entrada (final > na entrada)
  * Escanteios     -> sem dado final disponível na fonte pública => status N/D

O ledger é persistido em JSON: no servidor local em `data/entries.json`; no
GitHub Pages o workflow commita esse arquivo de volta ao repositório para o
histórico sobreviver entre os builds (a cada ~2-3 min).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("scanner.entries")

# Entradas mais antigas que isso são podadas do ledger (o frontend mostra 24h).
ENTRY_TTL_HOURS = 48


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _goals(home: Optional[int], away: Optional[int]) -> int:
    return int(home or 0) + int(away or 0)


def settle_market(market: Optional[str], goals_at_entry: int, final_goals: int) -> Optional[str]:
    """green/red para o mercado de gols; None = não avaliável (ex.: escanteios)."""
    if market == "Over 0.5 gol":
        return "green" if final_goals >= 1 else "red"
    if market == "Over 1.5 gols":
        return "green" if final_goals >= 2 else "red"
    if market == "Próximo gol":
        return "green" if final_goals > goals_at_entry else "red"
    return None


def entry_from_match(m: dict) -> dict:
    """Snapshot da oportunidade recomendada (a partida pode sumir depois)."""
    # A odd/probabilidade do modelo só faz sentido se for do mesmo mercado da
    # entrada: para dicas de gols descartamos sugestão de escanteios e vice-versa.
    sug_market = str(m.get("suggestion_market") or "")
    is_corners_sug = sug_market.startswith("corners")
    entry_market = m.get("market")
    entry_corner = m.get("corner_market")
    keep_odd = (entry_market and not is_corners_sug) or (
        entry_corner and not entry_market and is_corners_sug
    )

    return {
        "id": m.get("id"),
        "league": m.get("league"),
        "home": m.get("home"),
        "away": m.get("away"),
        "home_score_at_entry": m.get("home_score"),
        "away_score_at_entry": m.get("away_score"),
        "minute_at_entry": m.get("minute"),
        "market": entry_market,
        "corner_market": entry_corner,
        "entry_type": m.get("entry_type"),
        "odd": m.get("suggestion_odd") if keep_odd else None,
        "prob": m.get("suggestion_prob") if keep_odd else None,
        "lps_at_entry": m.get("lps"),
        "confidence": m.get("confidence"),
        "entered_at": _now_iso(),
        "status": "ativa",  # ativa | green | red | n_d
        "settled_at": None,
        "final_score": None,
        "note": None,
    }


class EntryTracker:
    """Ledger de entradas recomendadas, persistido em JSON entre execuções."""

    def __init__(self, path: Optional[str | Path] = None, min_lps: float = 70.0) -> None:
        self.path = Path(path) if path else None
        self.min_lps = min_lps
        self._entries: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------ IO
    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for e in raw if isinstance(raw, list) else []:
                if e.get("id") is not None:
                    self._entries[str(e["id"])] = e
        except Exception as exc:  # noqa: BLE001
            log.warning("não foi possível carregar o ledger %s: %s", self.path, exc)

    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("não foi possível salvar o ledger %s: %s", self.path, exc)

    # ---------------------------------------------------------------- API
    def snapshot(self) -> list[dict]:
        """Todas as entradas, da mais recente para a mais antiga."""
        return sorted(
            self._entries.values(),
            key=lambda e: e.get("entered_at") or "",
            reverse=True,
        )

    def observe(
        self, opportunities: list[dict], finished_matches: list[dict]
    ) -> list[dict]:
        """Adiciona entradas novas (recomendações atuais) e liquida as encerradas.

        Retorna a lista de eventos da rodada — ``{"kind": "new"|"settled",
        "entry": {...}}`` — para quem chama disparar alertas (ex.: Telegram).
        Só eventos de transição: uma entrada nova gera 1 evento, uma liquidação
        gera 1 evento.
        """
        events: list[dict] = []

        # 1) Novas entradas: só o que o radar recomendou agora.
        for m in opportunities:
            key = m.get("id")
            if key is None or str(key) in ("", "None"):
                continue
            if m.get("entry_type", "none") == "none":
                continue
            if (m.get("lps") or 0) < self.min_lps:
                continue
            key = str(key)
            if key in self._entries:
                continue
            self._entries[key] = entry_from_match(m)
            events.append({"kind": "new", "entry": self._entries[key]})

        # 2) Liquidação: partidas que acabaram (placar final do RoboBet).
        finished_by_id = {
            str(m.get("id")): m for m in finished_matches if m.get("id") is not None
        }
        for key, entry in self._entries.items():
            if entry.get("status") != "ativa":
                continue
            ended = finished_by_id.get(key)
            if ended is not None:
                self._settle(entry, ended)
                events.append({"kind": "settled", "entry": entry})

        # 3) Podas: entradas muito antigas saem do ledger.
        cutoff = datetime.now(timezone.utc).timestamp() - ENTRY_TTL_HOURS * 3600
        self._entries = {
            k: v
            for k, v in self._entries.items()
            if _iso_ts(v.get("entered_at")) >= cutoff
        }

        return events

    # ------------------------------------------------------------ interno
    def _settle(self, entry: dict, ended: dict) -> None:
        fh = ended.get("home_score") or 0
        fa = ended.get("away_score") or 0
        entry["final_score"] = f"{fh} x {fa}"
        entry["settled_at"] = _now_iso()
        goals_at_entry = _goals(
            entry.get("home_score_at_entry"), entry.get("away_score_at_entry")
        )
        result = settle_market(entry.get("market"), goals_at_entry, _goals(fh, fa))
        if result is None:
            entry["status"] = "n_d"
            entry["note"] = "Mercado de escanteios sem dado final disponível (N/D)"
        else:
            entry["status"] = result


def _iso_ts(value) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0
