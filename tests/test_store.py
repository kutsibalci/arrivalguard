"""Kalıcılık: SQLite ve bellek deposu aynı sözleşmeye uyar; SQLite yeniden başlatmada vakaları korur."""
from datetime import datetime, timedelta, timezone

import pytest

from arrivalguard.agent import Case
from arrivalguard.api.store import MemoryStore, SqliteStore, secret_key

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def make_case(cid="case-1", state="waiting", phone="+447700900001", clinic="clinic-1") -> Case:
    return Case(id=cid, clinic_id=clinic, clinic_name="K", patient_name="Layla A.", patient_phone=phone, language="en",
                itinerary={"destination_country": 90, "legs": [{"country": 90, "eta": NOW.isoformat()}]},
                driver={"id": "drv-1", "name": "M", "phone": "+447700900101"}, state=state,
                consent_token="c-tok", driver_token="d-tok", created_at=NOW.isoformat())


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    s = MemoryStore() if request.param == "memory" else SqliteStore(tmp_path / "ag.db")
    yield s
    if isinstance(s, SqliteStore):
        s.close()


def test_case_roundtrip_and_queries(store):
    a, b = make_case("a"), make_case("b", state="closed", phone="+447700900004", clinic="clinic-2")
    store.save_case(a)
    store.save_case(b)
    assert store.get_case("a").to_dict() == a.to_dict()
    assert [c.id for c in store.list_cases(clinic_id="clinic-2")] == ["b"]
    assert [c.id for c in store.list_cases(states=["waiting"])] == ["a"]
    assert store.list_cases(states=[]) == []
    assert store.find_case_by_secret("consent", "c-tok").id in ("a", "b")
    assert store.find_case_by_secret("driver", "yok") is None
    assert store.find_monitoring_case_by_phone_hash(a.phone_hash).id == "a"
    assert store.find_monitoring_case_by_phone_hash(b.phone_hash) is None  # kapalı vaka izlenmiyor
    store.delete_case("a")
    assert store.get_case("a") is None


def test_subscriptions_events_clinics(store):
    store.add_sub("s1", "a", "roaming")
    assert store.get_sub("s1") == ("a", "roaming") and store.list_subs() == [{"id": "s1", "case_id": "a", "target": "roaming"}]
    store.remove_sub("s1")
    assert store.get_sub("s1") is None
    assert store.seen_event("roaming:ce1", NOW) is False and store.seen_event("roaming:ce1", NOW) is True
    assert store.purge_events(NOW + timedelta(seconds=1)) == 1 and store.seen_event("roaming:ce1", NOW) is False
    store.save_clinic({"id": "c1", "name": "X", "drivers": []})
    assert store.get_clinic("c1")["name"] == "X" and [c["id"] for c in store.list_clinics()] == ["c1"]
    store.reset()
    assert store.list_cases() == [] and store.get_clinic("c1")  # reset klinik sicilini korur


def test_sqlite_survives_restart_and_indexes_only_hashed_secrets(tmp_path):
    path = tmp_path / "ag.db"
    s1 = SqliteStore(path)
    s1.save_case(make_case())
    s1.add_sub("sub-1", "case-1", "clinic")
    s1.close()
    s2 = SqliteStore(path)
    c = s2.get_case("case-1")
    assert c.patient_phone == "+447700900001" and s2.get_sub("sub-1") == ("case-1", "clinic")
    cols = s2.db.execute("SELECT consent_key, driver_key FROM cases").fetchone()
    assert cols == (secret_key("c-tok"), secret_key("d-tok")) and "c-tok" not in cols
    s2.close()


def test_purged_case_record_has_no_raw_phone(tmp_path):
    s = SqliteStore(tmp_path / "ag.db")
    c = make_case(state="closed")
    c.purge_pii(NOW)
    s.save_case(c)
    raw = s.db.execute("SELECT data FROM cases").fetchone()[0]
    assert "+447700900001" not in raw and "+447700900101" not in raw and "c-tok" not in raw
    s.close()
