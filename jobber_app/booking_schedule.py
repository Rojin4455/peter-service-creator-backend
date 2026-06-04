"""
Parse booking start/end for Jobber visits with explicit timezone rules.

GHL often sends startTime as UTC (Z) while the wall clock is local (e.g. 09:00Z meaning 9 AM
America/Toronto). When calendar_timezone is provided, optional GHL_Z_SUFFIX_MEANS_LOCAL_WALL_CLOCK
(default true) treats Z-suffixed timestamps as local wall time in that zone.
"""
from datetime import timedelta, timezone as dt_timezone

from decouple import config
from django.utils.dateparse import parse_datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def default_booking_timezone():
    return (config("JOBBER_BOOKING_TIMEZONE", default="America/Toronto") or "America/Toronto").strip()


def _z_suffix_means_local_wall_clock():
    raw = (config("GHL_Z_SUFFIX_MEANS_LOCAL_WALL_CLOCK", default="true") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _zone(tz_name):
    if not tz_name or ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return None


def parse_booking_instant(iso_value, tz_name=None, *, z_suffix_means_local=None):
    """
    Return timezone-aware datetime in UTC.

    Rules:
    - Naive ISO → interpret as local time in tz_name (default America/Toronto).
    - Offset / Z → if z_suffix_means_local and tz_name set, strip offset and use wall clock in tz_name.
      Otherwise parse as absolute instant (UTC for Z).
    """
    if iso_value is None:
        return None
    s = str(iso_value).strip()
    if not s:
        return None

    if z_suffix_means_local is None:
        z_suffix_means_local = _z_suffix_means_local_wall_clock()
    tz_name = (tz_name or "").strip() or default_booking_timezone()
    zone = _zone(tz_name)

    # GHL quirk: "2026-06-25T09:00:00.000Z" often means 9 AM local, not 9 AM UTC.
    # Only apply wall-clock fix for bare Z; trust explicit numeric offsets (+00:00, -04:00).
    if (
        z_suffix_means_local
        and zone is not None
        and (s.endswith("Z") or s.endswith("z"))
        and "+" not in s[:-1]
        and not (len(s) > 10 and s.rfind("-") > 10)
    ):
        naive = s.rstrip("Zz")
        dt = parse_datetime(naive.strip())
        if dt is not None:
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt.replace(tzinfo=zone).astimezone(dt_timezone.utc)

    normalized = s.replace("Z", "+00:00").replace("z", "+00:00")
    dt = parse_datetime(normalized)
    if dt is None:
        return None
    if dt.tzinfo is None:
        if zone is not None:
            dt = dt.replace(tzinfo=zone)
        else:
            dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


def format_jobber_iso_timestamp(dt_utc):
    """Format UTC instant for Jobber visitCreate schedule.isoTimestamp (with offset)."""
    if dt_utc is None:
        return None
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=dt_timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(dt_timezone.utc)
    tz_name = default_booking_timezone()
    zone = _zone(tz_name)
    if zone is not None:
        local = dt_utc.astimezone(zone)
        return local.isoformat(timespec="seconds")
    return dt_utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve_slot_duration_hours(
    *,
    slot_duration_hours=None,
    approved_price=None,
    service_type=None,
    team_size=2,
    compute_slot_fn=None,
):
    """Resolve calendar slot length in hours (0.5h increments from booking rules)."""
    if slot_duration_hours is not None:
        try:
            h = float(slot_duration_hours)
            if h > 0:
                return round(h * 2) / 2.0
        except (TypeError, ValueError):
            pass
    if approved_price is not None and compute_slot_fn is not None:
        try:
            p = float(approved_price)
        except (TypeError, ValueError):
            p = None
        if p and p > 0:
            _, _, slot = compute_slot_fn(price=p, service_type=service_type or "", team_size=team_size)
            if slot is not None:
                return slot
    try:
        fallback = float(config("JOBBER_DEFAULT_VISIT_DURATION_HOURS", default="3"))
        if fallback > 0:
            return round(fallback * 2) / 2.0
    except (TypeError, ValueError):
        pass
    return 3.0


def resolve_booking_window(
    *,
    scheduled_start_iso=None,
    scheduled_end_iso=None,
    calendar_timezone=None,
    slot_duration_hours=None,
    approved_price=None,
    service_type=None,
    team_size=2,
    compute_slot_fn=None,
):
    """
    Return (start_utc, end_utc, slot_hours, tz_name) or (None, None, None, tz_name) if no start.
    """
    tz_name = (calendar_timezone or "").strip() or default_booking_timezone()
    start_utc = parse_booking_instant(scheduled_start_iso, tz_name)
    if start_utc is None:
        return None, None, None, tz_name

    end_utc = None
    if scheduled_end_iso:
        end_utc = parse_booking_instant(scheduled_end_iso, tz_name)
        if end_utc is not None and end_utc <= start_utc:
            end_utc = None

    slot_hours = resolve_slot_duration_hours(
        slot_duration_hours=slot_duration_hours,
        approved_price=approved_price,
        service_type=service_type,
        team_size=team_size,
        compute_slot_fn=compute_slot_fn,
    )

    if end_utc is None:
        end_utc = start_utc + timedelta(hours=slot_hours)

    return start_utc, end_utc, slot_hours, tz_name


def calendar_window_from_ghl(cal):
    """Extract start/end ISO strings and timezone from GHL workflow calendar object."""
    if not isinstance(cal, dict):
        return None, None, None
    start_raw = (cal.get("startTime") or cal.get("start_time") or "").strip() or None
    end_raw = (cal.get("endTime") or cal.get("end_time") or "").strip() or None
    tz_name = (cal.get("selectedTimezone") or cal.get("timezone") or "").strip() or None
    return start_raw, end_raw, tz_name


def booking_window_from_payload(data, calendar_obj=None):
    """
    Build resolve_booking_window kwargs from booking confirm dict + optional GHL calendar.
    """
    data = data if isinstance(data, dict) else {}
    cal = calendar_obj if isinstance(calendar_obj, dict) else {}
    cal_start, cal_end, cal_tz = calendar_window_from_ghl(cal)

    start_iso = (data.get("scheduled_start_iso") or "").strip() or cal_start
    end_iso = (data.get("scheduled_end_iso") or "").strip() or cal_end
    tz_name = (data.get("calendar_timezone") or "").strip() or cal_tz

    approved = data.get("approved_price")
    if approved is None and data.get("services"):
        try:
            approved = sum(float(r.get("line_item_price") or 0) for r in data["services"] if isinstance(r, dict))
        except (TypeError, ValueError):
            approved = None

    service_type = (data.get("service_type") or "").strip()
    if not service_type and data.get("service_types"):
        st = data.get("service_types")
        if isinstance(st, list) and st:
            service_type = str(st[0])

    return {
        "scheduled_start_iso": start_iso,
        "scheduled_end_iso": end_iso,
        "calendar_timezone": tz_name,
        "slot_duration_hours": data.get("slot_duration_hours") or data.get("calendar_slot_duration"),
        "approved_price": approved,
        "service_type": service_type,
        "team_size": data.get("team_size", 2),
    }
