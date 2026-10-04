"""Ein Release – eine Quelle: Tracks einer EP oder eines Albums sollen nicht aus verschiedenen
Releases oder Quellen getaggt werden (sonst landen sie in verschiedenen Ordnern, mit
unterschiedlichem Jahr, Label oder Tracknummern).

Zusammengehörige Tracks erkennen wir an
  * gleichem Album-Tag im selben Quellordner (alte Tags) oder
  * gleichem Release-Namen + Album-Artist beim Treffer (z. B. dieselbe EP bei Beatport und Discogs).

Für jede Gruppe wird ein Release gewählt (bereits übernommene > manuell gewählte > Beatport > die
meisten Tracks) und die übrigen Tracks werden auf dessen Trackliste umgestellt. Klappt das nicht,
wird der Track als „unsicher“ markiert und nicht automatisch übernommen.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from .matcher import MATCH_THRESHOLD, PREFERRED_SOURCE, UNCERTAIN_THRESHOLD, _sim, enrich, normalize
from .models import LibraryItem, MatchStatus, TrackMeta
from .urlimport import assign_release

CONFLICT = "⚠ anderes Release als der Rest der EP"
ALBUM_SIMILARITY = 0.6  # ab hier gilt ein altes Album-Tag als „dieselbe EP“ wie der Release-Name


def release_key(meta: TrackMeta) -> tuple[str, str]:
    return meta.source, str(meta.release_id or normalize(meta.release))


def _local_key(item: LibraryItem) -> tuple | None:
    album = normalize(item.local.album)
    return ("lokal", str(item.local.path.parent), album) if album else None


def _match_key(item: LibraryItem) -> tuple | None:
    m = item.selected
    if m is None or not normalize(m.release):
        return None
    return ("treffer", normalize(m.release), normalize(m.effective_album_artist))


def groups(items: list[LibraryItem]) -> list[list[LibraryItem]]:
    """Zusammengehörige Tracks (mindestens zwei) über alte Album-Tags und Release-Namen verbinden."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[tuple, int] = {}
    for i, it in enumerate(items):
        for key in (_local_key(it), _match_key(it)):
            if key is None:
                continue
            if key in first:
                parent[find(i)] = find(first[key])
            else:
                first[key] = i
    out: dict[int, list[LibraryItem]] = defaultdict(list)
    for i, it in enumerate(items):
        out[find(i)].append(it)
    return [g for g in out.values() if len(g) > 1]


def choose_release(group: list[LibraryItem]) -> TrackMeta | None:
    """Das Release, dem die Gruppe folgen soll."""
    by_key: dict[tuple, list[LibraryItem]] = defaultdict(list)
    for it in group:
        if it.selected is not None:
            by_key[release_key(it.selected)].append(it)
    if not by_key:
        return None

    def rank(members: list[LibraryItem]):
        return (
            any(m.status == MatchStatus.DONE for m in members),    # liegt schon so in der neuen Library
            any(m.status == MatchStatus.MANUAL for m in members),  # bewusst gewählt
            members[0].selected.source == PREFERRED_SOURCE,
            len(members),
            sum(m.score for m in members) / len(members),
        )

    return max(by_key.values(), key=rank)[0].selected


def _belongs(item: LibraryItem, target: TrackMeta) -> bool:
    """Gehört der Track wirklich zu diesem Release? Schützt vor Sammelordnern mit gleichem Album-Tag."""
    if item.selected is not None and normalize(item.selected.release) == normalize(target.release):
        return True
    return bool(item.local.album) and _sim(item.local.album, target.release) >= ALBUM_SIMILARITY


def harmonize(items: list[LibraryItem], sources, match_threshold: float = MATCH_THRESHOLD,
              uncertain_threshold: float = UNCERTAIN_THRESHOLD, only: LibraryItem | None = None,
              cancelled: Callable[[], bool] = lambda: False) -> list[str]:
    """Gleicht die Releases zusammengehöriger Tracks an. Gibt Log-Zeilen zurück.

    Bereits übernommene und manuell gewählte Tracks werden nie geändert.
    ``only``: nur die Gruppe dieses Tracks bearbeiten (z. B. nach einer manuellen Auswahl).
    """
    if not isinstance(sources, (list, tuple)):
        sources = [sources]
    by_name = {getattr(s, "name", ""): s for s in sources}
    tracklists: dict[tuple, list[TrackMeta]] = {}
    log: list[str] = []

    def tracklist(target: TrackMeta) -> list[TrackMeta]:
        key = release_key(target)
        if key not in tracklists:
            src = by_name.get(target.source)
            tracks: list[TrackMeta] = []
            if src is not None and hasattr(src, "release_tracks") and target.release_id:
                try:
                    tracks = src.release_tracks(target.release_id)
                except Exception as e:
                    log.append(f"Trackliste von „{target.release}“ ({target.source}) nicht ladbar: {e}")
            tracklists[key] = tracks
        return tracklists[key]

    for group in groups(items):
        if cancelled():
            break
        if only is not None and not any(it is only for it in group):
            continue
        target = choose_release(group)
        if target is None:
            continue
        tkey = release_key(target)
        off = [it for it in group
               if it.status not in (MatchStatus.DONE, MatchStatus.MANUAL)
               and (it.selected is None or release_key(it.selected) != tkey)
               and _belongs(it, target)]
        for it in group:
            if it.status == MatchStatus.MANUAL and it.selected is not None and release_key(it.selected) != tkey \
                    and _belongs(it, target):
                log.append(f"⚠ {it.local.path.name}: manuell „{it.selected.release}“ ({it.selected.source}) gewählt, "
                           f"der Rest der EP nutzt „{target.release}“ ({target.source})")
        if not off:
            continue

        # Kandidaten aus der Suche + komplette Trackliste des Releases; schon vergebene Tracks auslassen
        taken = {it.selected.key for it in group if it.selected is not None and release_key(it.selected) == tkey}
        pool: dict[tuple, TrackMeta] = {}
        for it in off:
            for c in it.candidates:
                if release_key(c.track) == tkey:
                    pool.setdefault(c.track.key, c.track)
        for t in tracklist(target):
            pool.setdefault(t.key, t)
        pool = {k: t for k, t in pool.items() if k not in taken}

        assigned = {id(it): (meta, s) for it, meta, s in assign_release(off, list(pool.values()), uncertain_threshold)}
        for it in off:
            meta, s = assigned.get(id(it), (None, 0.0))
            if meta is not None and s < uncertain_threshold and it.selected is not None:
                meta = None  # nur über die Tracknummer gefunden – einen echten Treffer nicht dafür verwerfen
            if meta is not None:
                it.selected = enrich(meta, sources)
                it.score = s
                it.status = MatchStatus.MATCHED if s >= match_threshold else MatchStatus.UNCERTAIN
                it.message = f"an Release „{target.release}“ ({target.source}) angeglichen"
                log.append(f"{it.local.path.name}: {it.message}")
            elif it.selected is not None:
                it.status = MatchStatus.UNCERTAIN
                it.message = (f"{CONFLICT} – hier „{it.selected.release}“ "
                              f"({it.selected.source}), sonst „{target.release}“ ({target.source})")
                log.append(f"{it.local.path.name}: {it.message}")
    return log

