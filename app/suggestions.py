"""Propozycje par aktywności o zbliżonym czasie (np. zegarek + licznik)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Act:
    id: int
    start: datetime
    end: datetime
    type: str
    name: str


def _parse_start(s: str | None) -> datetime | None:
    if not s:
        return None
    # Strava: "2024-01-15T10:00:00Z" lub z offsetem
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_acts(rows: list[dict]) -> list[Act]:
    acts: list[Act] = []
    for r in rows:
        st = _parse_start(r.get("start_date"))
        if st is None:
            continue
        st = _ensure_utc(st)
        elapsed = int(r.get("elapsed_time") or 0)
        end = st.timestamp() + elapsed
        acts.append(
            Act(
                id=int(r["id"]),
                start=st,
                end=datetime.fromtimestamp(end, tz=timezone.utc),
                type=str(r.get("type") or ""),
                name=str(r.get("name") or ""),
            )
        )
    return acts


def suggest_pairs(
    rows: list[dict],
    *,
    max_start_gap_minutes: float = 45.0,
    min_overlap_seconds: float = 120.0,
    max_pairs: int = 40,
) -> list[dict]:
    """
    Zwraca listę par { id_a, id_b, reason, score }.
    Heurystyka: nakładające się przedziały czasu LUB bardzo bliskie starty
    (typowy przypadek: dwa urządzenia logują ten sam przejazd).
    """
    acts = build_acts(rows)
    acts.sort(key=lambda a: a.start)
    pairs: list[dict] = []

    for i in range(len(acts)):
        for j in range(i + 1, len(acts)):
            a, b = acts[i], acts[j]
            # tylko „niedaleko” w czasie startu — ogranicza O(n²)
            gap = (b.start - a.start).total_seconds()
            if gap > max_start_gap_minutes * 60 * 3:
                break

            overlap_start = max(a.start, b.start)
            overlap_end = min(a.end, b.end)
            overlap = (overlap_end - overlap_start).total_seconds()

            start_gap_sec = abs((a.start - b.start).total_seconds())
            same_type = a.type and a.type == b.type

            ok = False
            reason = ""
            score = 0.0

            if overlap >= min_overlap_seconds:
                ok = True
                reason = f"nakładanie się ~{int(overlap)} s"
                score = 100.0 + min(overlap, 3600) / 100.0 + (10.0 if same_type else 0)
            elif start_gap_sec <= max_start_gap_minutes * 60:
                ok = True
                reason = f"start w odstępie {int(start_gap_sec // 60)} min"
                score = 50.0 - start_gap_sec / 60.0 + (10.0 if same_type else 0)

            if ok:
                if a.start <= b.start:
                    id_first, id_second = a.id, b.id
                    name_first, name_second = a.name, b.name
                    type_first, type_second = a.type, b.type
                else:
                    id_first, id_second = b.id, a.id
                    name_first, name_second = b.name, a.name
                    type_first, type_second = b.type, a.type
                pairs.append(
                    {
                        "id_first": id_first,
                        "id_second": id_second,
                        "reason": reason,
                        "score": round(score, 2),
                        "name_first": name_first,
                        "name_second": name_second,
                        "type_first": type_first,
                        "type_second": type_second,
                    }
                )

    pairs.sort(key=lambda p: -p["score"])
    return pairs[:max_pairs]
