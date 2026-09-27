"""Kalıcılık: aynı arayüzü paylaşan iki depo.

MemoryStore  — geliştirme/demo/test. Vaka nesneleri bellekte, yeniden başlatmada kaybolur.
SqliteStore  — tek sunuculu üretim. Vaka = JSON kayıt + arama sütunları; abonelik eşlemesi, CloudEvent
               tekilleştirme ve klinik sicili tablolarda. Tüm erişim `lock` altında (FastAPI thread havuzu + zamanlayıcı).

Gizlilik: ham telefon numarası vaka kaydında yalnızca izleme sürerken durur; terminal durumda
`Case.purge_pii()` onu siler ve kayıt yeniden yazılır. Sırlar (rıza/sürücü token'ı) aranırken SHA-256 ile
indekslenir; indeks sütununda düz token yoktur.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..agent import Case


def secret_key(token: str | None) -> str | None:
    return hashlib.sha256(token.encode()).hexdigest() if token else None


class Store(Protocol):
    lock: threading.RLock

    def reset(self) -> None: ...
    def get_case(self, case_id: str) -> Case | None: ...
    def save_case(self, case: Case) -> None: ...
    def delete_case(self, case_id: str) -> None: ...
    def list_cases(self, clinic_id: str | None = None, states: Iterable[str] | None = None) -> list[Case]: ...
    def find_case_by_secret(self, kind: str, token: str) -> Case | None: ...
    def find_monitoring_case_by_phone_hash(self, phone_hash: str) -> Case | None: ...
    def add_sub(self, sub_id: str, case_id: str, target: str) -> None: ...
    def get_sub(self, sub_id: str) -> tuple[str, str] | None: ...
    def remove_sub(self, sub_id: str) -> None: ...
    def list_subs(self) -> list[dict]: ...
    def seen_event(self, key: str, now: datetime) -> bool: ...
    def purge_events(self, before: datetime) -> int: ...
    def get_clinic(self, clinic_id: str) -> dict | None: ...
    def save_clinic(self, clinic: dict) -> None: ...
    def list_clinics(self) -> list[dict]: ...


_MONITORING_EXCLUDED = ("pending_consent", "closed", "expired", "declined", "withdrawn")


class MemoryStore:
    backend = "memory"

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset(clinics=True)

    def reset(self, clinics: bool = False) -> None:
        with self.lock:
            self.cases: dict[str, Case] = {}
            self.subs: dict[str, tuple[str, str]] = {}
            self.events: dict[str, datetime] = {}
            if clinics:
                self.clinics: dict[str, dict] = {}

    def get_case(self, case_id: str) -> Case | None:
        return self.cases.get(case_id)

    def save_case(self, case: Case) -> None:
        self.cases[case.id] = case

    def delete_case(self, case_id: str) -> None:
        self.cases.pop(case_id, None)
        for sid in [s for s, (cid, _) in self.subs.items() if cid == case_id]:
            self.subs.pop(sid, None)

    def list_cases(self, clinic_id: str | None = None, states: Iterable[str] | None = None) -> list[Case]:
        st = set(states) if states is not None else None
        return [c for c in self.cases.values()
                if (clinic_id is None or c.clinic_id == clinic_id) and (st is None or c.state in st)]

    def find_case_by_secret(self, kind: str, token: str) -> Case | None:
        attr = {"consent": "consent_token", "driver": "driver_token"}[kind]
        return next((c for c in self.cases.values() if getattr(c, attr) and getattr(c, attr) == token), None)

    def find_monitoring_case_by_phone_hash(self, phone_hash: str) -> Case | None:
        hits = [c for c in self.cases.values() if c.phone_hash == phone_hash and c.state not in _MONITORING_EXCLUDED]
        return max(hits, key=lambda c: c.created_at or "", default=None)

    def add_sub(self, sub_id: str, case_id: str, target: str) -> None:
        self.subs[sub_id] = (case_id, target)

    def get_sub(self, sub_id: str) -> tuple[str, str] | None:
        return self.subs.get(sub_id)

    def remove_sub(self, sub_id: str) -> None:
        self.subs.pop(sub_id, None)

    def list_subs(self) -> list[dict]:
        return [{"id": sid, "case_id": cid, "target": tgt} for sid, (cid, tgt) in self.subs.items()]

    def seen_event(self, key: str, now: datetime) -> bool:
        if key in self.events:
            return True
        self.events[key] = now
        return False

    def purge_events(self, before: datetime) -> int:
        old = [k for k, t in self.events.items() if t < before]
        for k in old:
            self.events.pop(k, None)
        return len(old)

    def get_clinic(self, clinic_id: str) -> dict | None:
        c = self.clinics.get(clinic_id)
        return json.loads(json.dumps(c)) if c else None

    def save_clinic(self, clinic: dict) -> None:
        self.clinics[clinic["id"]] = json.loads(json.dumps(clinic))

    def list_clinics(self) -> list[dict]:
        return [json.loads(json.dumps(c)) for c in self.clinics.values()]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    clinic_id TEXT NOT NULL,
    state TEXT NOT NULL,
    phone_hash TEXT,
    consent_key TEXT,
    driver_key TEXT,
    created_at TEXT,
    updated_at TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cases_clinic ON cases(clinic_id);
CREATE INDEX IF NOT EXISTS ix_cases_state ON cases(state);
CREATE INDEX IF NOT EXISTS ix_cases_phone ON cases(phone_hash);
CREATE INDEX IF NOT EXISTS ix_cases_consent ON cases(consent_key);
CREATE INDEX IF NOT EXISTS ix_cases_driver ON cases(driver_key);
CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, target TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_subs_case ON subscriptions(case_id);
CREATE TABLE IF NOT EXISTS seen_events (key TEXT PRIMARY KEY, seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clinics (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
SCHEMA_VERSION = "1"


class SqliteStore:
    backend = "sqlite"

    def __init__(self, path: str | Path) -> None:
        self.lock = threading.RLock()
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.lock:
            self.db.executescript(_SCHEMA)
            self.db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def reset(self, clinics: bool = False) -> None:
        with self.lock:
            self.db.execute("DELETE FROM cases")
            self.db.execute("DELETE FROM subscriptions")
            self.db.execute("DELETE FROM seen_events")
            if clinics:
                self.db.execute("DELETE FROM clinics")

    # ---- vakalar ----
    @staticmethod
    def _row_to_case(row) -> Case | None:
        return Case.from_record(json.loads(row[0])) if row else None

    def get_case(self, case_id: str) -> Case | None:
        with self.lock:
            return self._row_to_case(self.db.execute("SELECT data FROM cases WHERE id = ?", (case_id,)).fetchone())

    def save_case(self, case: Case) -> None:
        rec = case.to_record()
        with self.lock:
            self.db.execute(
                "INSERT INTO cases(id, clinic_id, state, phone_hash, consent_key, driver_key, created_at, updated_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET clinic_id=excluded.clinic_id, "
                "state=excluded.state, phone_hash=excluded.phone_hash, consent_key=excluded.consent_key, "
                "driver_key=excluded.driver_key, updated_at=excluded.updated_at, data=excluded.data",
                (case.id, case.clinic_id, case.state, case.phone_hash, secret_key(case.consent_token), secret_key(case.driver_token),
                 case.created_at, case.updated_at, json.dumps(rec, ensure_ascii=False)),
            )

    def delete_case(self, case_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM subscriptions WHERE case_id = ?", (case_id,))
            self.db.execute("DELETE FROM cases WHERE id = ?", (case_id,))

    def list_cases(self, clinic_id: str | None = None, states: Iterable[str] | None = None) -> list[Case]:
        q, args = "SELECT data FROM cases WHERE 1=1", []
        if clinic_id is not None:
            q += " AND clinic_id = ?"
            args.append(clinic_id)
        if states is not None:
            st = list(states)
            if not st:
                return []
            q += f" AND state IN ({','.join('?' * len(st))})"
            args += st
        q += " ORDER BY created_at"
        with self.lock:
            return [Case.from_record(json.loads(r[0])) for r in self.db.execute(q, args).fetchall()]

    def find_case_by_secret(self, kind: str, token: str) -> Case | None:
        col = {"consent": "consent_key", "driver": "driver_key"}[kind]
        with self.lock:
            row = self.db.execute(f"SELECT data FROM cases WHERE {col} = ?", (secret_key(token),)).fetchone()  # noqa: S608 — col sabit
        return self._row_to_case(row)

    def find_monitoring_case_by_phone_hash(self, phone_hash: str) -> Case | None:
        ph = ",".join("?" * len(_MONITORING_EXCLUDED))
        with self.lock:
            row = self.db.execute(
                f"SELECT data FROM cases WHERE phone_hash = ? AND state NOT IN ({ph}) ORDER BY created_at DESC LIMIT 1",  # noqa: S608
                (phone_hash, *_MONITORING_EXCLUDED)).fetchone()
        return self._row_to_case(row)

    # ---- abonelikler ----
    def add_sub(self, sub_id: str, case_id: str, target: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO subscriptions(id, case_id, target) VALUES (?, ?, ?)", (sub_id, case_id, target))

    def get_sub(self, sub_id: str) -> tuple[str, str] | None:
        with self.lock:
            row = self.db.execute("SELECT case_id, target FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def remove_sub(self, sub_id: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))

    def list_subs(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id, case_id, target FROM subscriptions").fetchall()
        return [{"id": r[0], "case_id": r[1], "target": r[2]} for r in rows]

    # ---- CloudEvent tekilleştirme ----
    def seen_event(self, key: str, now: datetime) -> bool:
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO seen_events(key, seen_at) VALUES (?, ?)", (key, now.isoformat()))
            return cur.rowcount == 0

    def purge_events(self, before: datetime) -> int:
        with self.lock:
            return self.db.execute("DELETE FROM seen_events WHERE seen_at < ?", (before.isoformat(),)).rowcount

    # ---- klinikler ----
    def get_clinic(self, clinic_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT data FROM clinics WHERE id = ?", (clinic_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_clinic(self, clinic: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO clinics(id, data) VALUES (?, ?)", (clinic["id"], json.dumps(clinic, ensure_ascii=False)))

    def list_clinics(self) -> list[dict]:
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM clinics ORDER BY id").fetchall()]


def build_store(backend: str, db_path: str) -> MemoryStore | SqliteStore:
    if backend == "sqlite":
        return SqliteStore(db_path)
    return MemoryStore()
