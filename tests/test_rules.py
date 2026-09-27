"""ArrivalGuard kural motoru testleri — saf fonksiyonlar, ağ yok, saat parametre."""
from datetime import datetime, timedelta, timezone

from arrivalguard.rules import Config
from arrivalguard.rules import decisions as R

CFG = Config()
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


def itin(dest_eta=T0, transit=974, dest=90):
    return {"destination_country": dest,
            "legs": [{"country": transit, "eta": (dest_eta - timedelta(hours=4)).isoformat()},
                     {"country": dest, "eta": dest_eta.isoformat()}]}


# ------------------------------------------------------------------ 1) transit vs varış
def test_destination_in_window_is_arrival():
    d = R.classify_roaming_event(90, itin(), T0, CFG)
    assert d.decision == "arrival" and d.rule == "arrival.destination_in_window"
    assert "run_integrity_gate" in d.actions
    assert any(e.signal == "itinerary.eta_delta_min" and e.triggered for e in d.explain)


def test_destination_out_of_window_needs_coordinator():
    d = R.classify_roaming_event(90, itin(), T0 + timedelta(hours=5), CFG)
    assert d.decision == "unexpected" and d.actions == ["notify_coordinator"]


def test_transit_leg_greets_but_does_not_dispatch_driver():
    d = R.classify_roaming_event(974, itin(), T0 - timedelta(hours=4), CFG)
    assert d.decision == "transit" and "keep_waiting" in d.actions
    assert "greet_briefly" in d.actions and "send_welcome_with_pickup" not in d.actions


def test_country_outside_itinerary_is_unexpected():
    d = R.classify_roaming_event(20, itin(), T0, CFG)
    assert d.decision == "unexpected" and d.rule == "roaming.unknown_country"


def test_missing_country_code_is_unexpected():
    d = R.classify_roaming_event(None, itin(), T0, CFG)
    assert d.decision == "unexpected" and d.rule == "roaming.no_country"


def test_country_code_accepts_string_and_plus():
    assert R.classify_roaming_event("+90", itin(), T0, CFG).decision == "arrival"


# ------------------------------------------------------------------ 2) bütünlük kapısı
def test_recent_sim_swap_withholds_pickup():
    d = R.integrity_gate(True, (T0 - timedelta(hours=3)).isoformat(), CFG, now=T0)
    assert d.decision == "withhold_pickup" and "freeze_pickup_details" in d.actions
    assert d.risk_score >= 0.9


def test_old_sim_swap_releases_pickup():
    d = R.integrity_gate(False, (T0 - timedelta(days=120)).isoformat(), CFG, now=T0)
    assert d.decision == "release_pickup" and "send_welcome_with_pickup" in d.actions


def test_swap_date_inside_window_triggers_even_if_check_false():
    """API 'swapped' bayrağı gelmese bile tarih penceredeyse bekletilir."""
    d = R.integrity_gate(False, (T0 - timedelta(hours=2)).isoformat(), CFG, now=T0)
    assert d.decision == "withhold_pickup"


# ------------------------------------------------------------------ 3) sürücü doğrulama (iki aşamalı)
def test_driver_device_verified_issues_meeting_code():
    d = R.authenticate_driver_device(True, True)
    assert d.decision == "driver_verified" and "issue_meeting_code" in d.actions


def test_driver_device_on_other_line_rejected():
    d = R.authenticate_driver_device(False, True)
    assert d.decision == "driver_rejected" and d.rule == "driver.not_verified"


def test_driver_device_unknown_number_rejected():
    d = R.authenticate_driver_device(True, False)
    assert d.decision == "driver_rejected" and d.rule == "driver.not_registered"


def test_registered_caller_with_fresh_attestation_is_genuine():
    d = R.assess_incoming_call(True, 3, CFG)
    assert d.decision == "genuine" and "mark_first_contact" in d.actions


def test_unregistered_caller_is_impostor_regardless_of_attestation():
    d = R.assess_incoming_call(False, 1, CFG)
    assert d.decision == "impostor" and d.rule == "caller.not_registered" and "warn_patient" in d.actions


def test_registered_number_without_attestation_is_unverified_spoof_risk():
    assert R.assess_incoming_call(True, None, CFG).decision == "unverified"
    stale = R.assess_incoming_call(True, CFG.driver_attestation_ttl_min + 1, CFG)
    assert stale.decision == "unverified" and stale.rule == "caller.no_fresh_attestation"


# ------------------------------------------------------------------ 4) aynı sinyal, zıt anlam
def test_unreachable_before_contact_raises_then_alarms():
    raise_ = R.assess_unreachable("released", False, 2, CFG)
    alarm = R.assess_unreachable("released", False, CFG.unreachable_before_contact_alert_min, CFG)
    assert raise_.decision == "raise" and alarm.decision == "alarm"
    assert "escalate_coordinator" in alarm.actions


def test_unreachable_after_contact_lowers_alarm():
    d = R.assess_unreachable("contacted", True, 15, CFG)
    assert d.decision == "lower" and d.rule == "unreachable.after_contact_local_sim"
    assert "fallback_messaging_channel" in d.actions


def test_same_signal_opposite_meaning():
    before = R.assess_unreachable("released", False, 7, CFG)
    after = R.assess_unreachable("contacted", True, 7, CFG)
    assert before.decision == "alarm" and after.decision == "lower"
    assert before.explain[1].signal == after.explain[1].signal == "case.first_contact_done"


def test_unreachable_after_grace_raises_again():
    d = R.assess_unreachable("in_transit", True, CFG.unreachable_after_contact_grace_min + 5, CFG)
    assert d.decision == "raise"


def test_closed_case_ignores_unreachable():
    assert R.assess_unreachable("closed", True, 999, CFG).decision == "lower"


# ------------------------------------------------------------------ 5) yolculuk bütünlüğü
def test_on_corridor_moving_is_ok():
    d = R.journey_check([], 0, False, CFG)
    assert d.decision == "ok" and d.meta["confidence"] == 0.95


def test_off_corridor_moving_is_probable_traffic_and_does_not_wake_coordinator():
    d = R.journey_check([{"type": "geofence_left"}], 2, True, CFG)
    assert d.decision == "probable_traffic" and d.meta["confidence"] == CFG.off_corridor_confidence_low
    assert d.actions == ["write_case_note"]


def test_off_corridor_stationary_is_trouble_medium_confidence():
    d = R.journey_check([], CFG.stationary_minutes_alert + 2, True, CFG)
    assert d.decision == "trouble" and d.meta["confidence"] == CFG.off_corridor_stationary_confidence


def test_off_corridor_stationary_unreachable_is_high_confidence():
    d = R.journey_check([], 20, True, CFG, patient_unreachable=True)
    assert d.decision == "trouble" and d.meta["confidence"] == CFG.trouble_confidence_high
    assert d.actions == ["escalate_coordinator"]


# ------------------------------------------------------------------ 6) eskalasyon bütçesi
def test_escalation_budget_allows_then_denies():
    assert R.escalation_allowed({"escalations_used": 0}, CFG).decision == "allow"
    denied = R.escalation_allowed({"escalations_used": CFG.escalation_budget_per_case}, CFG)
    assert denied.decision == "deny" and "append_to_open_alert" in denied.actions


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("AG_ESCALATION_BUDGET_PER_CASE", "7")
    monkeypatch.setenv("AG_CORRIDOR_RADIUS_M", "2500")
    c = Config.from_env()
    assert c.escalation_budget_per_case == 7 and c.corridor_radius_m == 2500
    assert "sim_swap_freeze_window_h" in c.to_dict()


# ------------------------------------------------------------------ bağlam: yol kapanması, gece
def test_known_disruption_turns_stationary_detour_into_case_note():
    d = R.journey_check([], 15, True, CFG, known_disruption={"note": "O-3 kapalı"}, hour_of_day=3)
    assert d.decision == "probable_traffic" and d.rule == "journey.stationary_explained_by_disruption"
    assert d.meta["confidence"] == round(CFG.off_corridor_stationary_confidence - CFG.disruption_discount, 2)
    assert any(e.signal == "context.known_disruption" and e.triggered for e in d.explain)
    assert any(e.signal == "context.hour" and e.triggered for e in d.explain)  # 03:00 gece aralığında


def test_known_disruption_lowers_but_does_not_hide_high_confidence_trouble():
    d = R.journey_check([], 20, True, CFG, patient_unreachable=True, known_disruption={"note": "kapanma"})
    assert d.decision == "trouble" and d.meta["confidence"] == round(CFG.trouble_confidence_high - CFG.disruption_discount, 2)


def test_night_window_wraps_midnight():
    cfg = Config(night_start_hour=22, night_end_hour=5)
    assert R.is_night(23, cfg) and R.is_night(2, cfg) and not R.is_night(12, cfg)
    assert not R.is_night(None, cfg)


# ------------------------------------------------------------------ yeniden eskalasyon, gecikmiş varış, süre dolumu
def test_reescalation_waits_for_interval():
    assert R.should_reescalate(None, T0, CFG)
    assert not R.should_reescalate((T0 - timedelta(minutes=CFG.reescalate_after_min - 1)).isoformat(), T0, CFG)
    assert R.should_reescalate((T0 - timedelta(minutes=CFG.reescalate_after_min)).isoformat(), T0, CFG)


def test_arrival_overdue_after_window():
    assert R.arrival_overdue(T0 + timedelta(hours=CFG.arrival_window_h) - timedelta(minutes=1), itin(), CFG).decision == "on_time"
    d = R.arrival_overdue(T0 + timedelta(hours=CFG.arrival_window_h, minutes=10), itin(), CFG)
    assert d.decision == "overdue" and "poll_roaming_status" in d.actions


def test_case_expiry_after_max_hours():
    assert not R.case_expired(T0 + timedelta(hours=CFG.case_max_hours), itin(), CFG)
    assert R.case_expired(T0 + timedelta(hours=CFG.case_max_hours, minutes=1), itin(), CFG)


# ------------------------------------------------------------------ rıza kapısı
def test_consent_gate():
    assert R.consent_gate("granted", True).decision == "start_monitoring"
    assert R.consent_gate("granted", None).decision == "start_monitoring"  # operatör cevapsız → hasta rızasıyla, işaretli
    pending = R.consent_gate("granted", False, "https://consent.example")
    assert pending.decision == "await_operator_consent" and pending.meta["capture_url"]
    assert R.consent_gate("declined", None).decision == "no_monitoring"
    assert "delete_subscriptions" in R.consent_gate("withdrawn", True).actions


def test_config_bool_and_bad_values_from_env(monkeypatch):
    monkeypatch.setenv("AG_OPERATOR_CONSENT_CHECK", "0")
    monkeypatch.setenv("AG_ARRIVAL_WINDOW_H", "abc")
    c = Config.from_env()
    assert c.operator_consent_check is False and c.arrival_window_h == Config().arrival_window_h
