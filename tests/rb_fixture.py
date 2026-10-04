"""Erzeugt eine verschlüsselte Mini-Datenbank im Rekordbox-6/7-Format für Tests."""
from __future__ import annotations

import datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session


def _filler(col, now):
    t = col.type
    if isinstance(t, (DateTime, Date)) or "date" in type(t).__name__.lower() or col.name in ("created_at", "updated_at"):
        return now
    if isinstance(t, (Integer, Float)):
        return 0
    if isinstance(t, (String, Text)):
        return ""
    return None


def _complete(obj, now):
    for col in obj.__table__.columns:
        if getattr(obj, col.key, None) is None and not col.primary_key:
            v = _filler(col, now)
            if v is not None:
                setattr(obj, col.key, v)
    return obj


def make_db(root: Path, tracks: list[dict]) -> Path:
    """tracks: [{"ID": "1", "FolderPath": "...", "Title": ..., "Rating": ...}, …] -> Pfad der master.db"""
    from pyrekordbox.db6 import tables
    from pyrekordbox.db6.database import BLOB, deobfuscate

    db = root / "master.db"
    eng = create_engine(f"sqlite+pysqlcipher://:{deobfuscate(BLOB)}@/{db}?")
    tables.Base.metadata.create_all(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    with Session(eng) as s:
        s.add(_complete(tables.AgentRegistry(registry_id="localUpdateCount", int_1=1), now))
        for t in tracks:
            fp = t["FolderPath"]
            row = tables.DjmdContent(FileNameL=Path(fp).name, OrgFolderPath=fp, UUID=f"uuid-{t['ID']}",
                                     AnalysisDataPath=f"/PIONEER/USBANLZ/{t['ID']}/x/ANLZ0000.DAT", **t)
            s.add(_complete(row, now))
        s.commit()
    eng.dispose()
    return db
