"""Owner-authorized AsherieSystem calendar grammar; no storage or model calls.

Adapted from 68593c64, with the unused packet-rendering API omitted and
day-end precision extended to Hermes/SQLite microseconds.
The caller alone decides whether to use a timeline or lexical search.
"""

from __future__ import annotations
import re
from calendar import monthrange
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional

DEFAULT_LIMIT = 8
_DATE_NUMBER = "(?:\\d{1,2}|[零〇一二三四五六七八九十]{1,3})"
_DATE_YEAR = "(?:20\\d{2}|二[零〇][零〇一二三四五六七八九]{2})"
_NUMBER_CHARS = "\\d零〇一二两三四五六七八九十百千万亿"
_MONTH_START = f"(?<![{_NUMBER_CHARS}近这前后])(?<!过去)(?<!未来)"
_EXACT_DATE_PATTERNS = (
    f"({_DATE_YEAR})[年/-]\\s*({_DATE_NUMBER})[月/-]\\s*({_DATE_NUMBER})(?:日|号)?",
    f"(?<![{_NUMBER_CHARS}])({_DATE_NUMBER})月({_DATE_NUMBER})(?:日|号)?",
    "(?<!\\d)(\\d{1,2})[/-](\\d{1,2})(?!\\d)",
)
_RANGE_JOIN = "\\s*(?:到|至|[-—–~～])\\s*"
_ABSOLUTE_SPAN_PATTERNS = (
    f"(?<![{_NUMBER_CHARS}])(?:({_DATE_YEAR})[年/-]\\s*)?({_DATE_NUMBER})[月/-]\\s*({_DATE_NUMBER})(?:日|号)?"
    + _RANGE_JOIN
    + f"(?:({_DATE_YEAR})[年/-]\\s*)?(?:({_DATE_NUMBER})[月/-]\\s*)?({_DATE_NUMBER})(?:日|号)?(?![{_NUMBER_CHARS}])",
    _MONTH_START
    + f"(?:({_DATE_YEAR})年\\s*)?({_DATE_NUMBER})月"
    + _RANGE_JOIN
    + f"(?:({_DATE_YEAR})年\\s*)?({_DATE_NUMBER})月(?!\\s*[{_NUMBER_CHARS}])",
    _MONTH_START
    + f"(?:({_DATE_YEAR})年\\s*)?({_DATE_NUMBER})月(?!\\s*[{_NUMBER_CHARS}])(?:份)?",
)
_RELATIVE_TIME_PATTERN = "大前天|前天|昨天|昨日|今天|刚才|刚刚|早些时候|方才|(?:这|最近|前)(?:\\d+|两|三|几)天|上周|上星期|上礼拜|上个月|上月"
_CLOCK_TIME_PATTERN = "(?:[01]?\\d|2[0-3])[:：][0-5]\\d(?:[:：][0-5]\\d)?|(?:\\d{1,2}|[零〇一二两三四五六七八九十]{1,3})(?:点|时)(?:半|(?:\\d{1,2}|[零〇一二两三四五六七八九十]{1,3})分?)?"
_COMMUNICATION_MODIFIERS = (
    "早上|上午|中午|下午|晚上|\\s|和你|跟你|和我|跟我|曾经|" + _CLOCK_TIME_PATTERN
)
_CONVERSATION_TIME_REFERENCE = re.compile(
    "(?P<time>"
    + "|".join(
        (*_ABSOLUTE_SPAN_PATTERNS, *_EXACT_DATE_PATTERNS, _RELATIVE_TIME_PATTERN)
    )
    + ")(?:的|那次|那天|我们|我|你|"
    + _COMMUNICATION_MODIFIERS
    + ")*(?:(?:我们|我|你)(?:"
    + _COMMUNICATION_MODIFIERS
    + ")*(?:说|聊|讨论)|(?:说|聊|讨论)(?:过|的|了|起|到)|提到|提过|告诉|谈过|问过|问的|发(?:的|过|了)?(?:消息|信息))"
)
FUZZY_PAST_PATTERNS = [
    "上次",
    "那天",
    "当时",
    "之前那(?:次|天|回)?",
    "前面(?:说|聊|提)?",
]


def build_temporal_recall_plan(
    *, query: str = "", reference_time: Any = None, limit: int = DEFAULT_LIMIT
) -> Dict[str, Any]:
    text = str(query or "").strip()
    if not text:
        return _empty_plan()
    now = _parse_datetime(reference_time) or datetime.now().astimezone()
    conversation_time = _CONVERSATION_TIME_REFERENCE.search(text)
    time_text = conversation_time.group("time") if conversation_time else text
    for kind, pattern in enumerate(_ABSOLUTE_SPAN_PATTERNS):
        match = re.search(pattern, time_text)
        if match:
            span = _resolve_absolute_span(match, kind, now)
            return (
                _plan_for_range(query=text, limit=limit, **span)
                if span
                else _empty_plan()
            )
    exact = _resolve_exact_date(time_text, now)
    if exact is not None:
        (day, label) = exact
        return _plan_for_range(
            query=text,
            label=label,
            start=_start_of_local_day(day),
            end=_end_of_local_day(day),
            reason="exact_date",
            limit=limit,
        )
    relative = _resolve_relative_range(time_text, now)
    if relative is not None:
        return _plan_for_range(query=text, limit=limit, **relative)
    if any((re.search(pattern, text) for pattern in FUZZY_PAST_PATTERNS)):
        return _plan_for_range(
            query=text,
            label="recent_past",
            start=_start_of_local_day(now) - timedelta(days=14),
            end=_end_of_local_day(now),
            reason="fuzzy_past_reference",
            limit=limit,
        )
    return _empty_plan()


def strip_temporal_words(value: str) -> str:
    text = str(value or "").strip()
    patterns = [
        *_ABSOLUTE_SPAN_PATTERNS,
        *_EXACT_DATE_PATTERNS,
        _RELATIVE_TIME_PATTERN,
        *FUZZY_PAST_PATTERNS,
    ]
    for pattern in patterns:
        text = re.sub(pattern, " ", text)
    return re.sub("\\s+", " ", text).strip()


def _empty_plan() -> Dict[str, Any]:
    return {
        "should_recall": False,
        "label": "",
        "reason": "",
        "query": "",
        "topic_query": "",
        "window_start_utc": "",
        "window_end_utc": "",
        "limit": DEFAULT_LIMIT,
    }


def _plan_for_range(
    *, query: str, label: str, start: datetime, end: datetime, reason: str, limit: int
) -> Dict[str, Any]:
    start_dt = _ensure_aware(start)
    end_dt = _ensure_aware(end)
    recap_text = strip_temporal_words(query)
    recap = bool(
        re.search("聊天|对话|(?:说|聊|谈|讨论)(?:过|了|的)?(?:些|点)?什么", recap_text)
        and re.fullmatch(
            "(?:请|帮我|给我|我们|我|你|把|的|都|全部|所有|完整|一下|一遍|回顾|回看|回忆|总结|列出|列出来|翻一下|聊天|对话|记录|内容|说|聊|谈|讨论|过|了|些|点|什么|有哪些|[\\s，,。？！?!])*",
            recap_text,
        )
    )
    conversation_time = recap or bool(_CONVERSATION_TIME_REFERENCE.search(query))
    return {
        "should_recall": True,
        "label": str(label or "").strip(),
        "reason": str(reason or "").strip(),
        "query": str(query or "").strip(),
        "topic_query": query
        if (reason == "exact_date" or reason.startswith("absolute_"))
        and (not conversation_time)
        else strip_temporal_words(query),
        "time_basis": "conversation" if conversation_time else "unspecified",
        "retrieval_mode": "timeline" if recap else "lexical",
        "window_start_utc": start_dt.astimezone().astimezone(_utc_tz()).isoformat(),
        "window_end_utc": end_dt.astimezone().astimezone(_utc_tz()).isoformat(),
        "limit": max(1, min(int(limit or DEFAULT_LIMIT), 24)),
    }


def _resolve_absolute_span(
    match: re.Match, kind: int, now: datetime
) -> Optional[Dict[str, Any]]:
    if kind == 0:
        (sy, sm, sd, ey, em, ed) = match.groups()
        em = em or sm
    elif kind == 1:
        (sy, sm, ey, em) = match.groups()
        (sd, ed) = ("1", "1")
    else:
        (sy, sm) = match.groups()
        (ey, em, sd, ed) = (sy, sm, "1", "1")
    (sm, sd, em, ed) = map(_parse_small_number, (sm, sd, em, ed))
    if not (1 <= sm <= 12 and 1 <= em <= 12):
        return None
    rollover = em < sm
    if sy:
        sy = _parse_small_number(sy)
        ey = _parse_small_number(ey) if ey else sy + int(rollover)
    elif ey:
        ey = _parse_small_number(ey)
        sy = ey - int(rollover)
    else:
        inferred_start = _infer_month_day(sm, sd, now)
        if inferred_start is None:
            return None
        sy = inferred_start.year
        ey = sy + int(rollover)
    if kind != 0:
        ed = monthrange(ey, em)[1]
    (start, end) = (
        _safe_local_date(sy, sm, sd, now),
        _safe_local_date(ey, em, ed, now),
    )
    if start is None or end is None or start > end:
        return None
    return {
        "label": match.group(0),
        "start": start,
        "end": _end_of_local_day(end),
        "reason": "absolute_date_range" if kind == 0 else "absolute_month_range",
    }


def _resolve_exact_date(text: str, now: datetime) -> Optional[tuple[datetime, str]]:
    full = re.search(_EXACT_DATE_PATTERNS[0], text)
    if full:
        day = _safe_local_date(*map(_parse_small_number, full.groups()), now)
        if day is not None and day <= _end_of_local_day(now) + timedelta(days=1):
            return (day, _format_local_date_label(day))
    chinese = re.search(_EXACT_DATE_PATTERNS[1], text)
    if chinese:
        day = _infer_month_day(*map(_parse_small_number, chinese.groups()), now)
        if day is not None:
            return (day, _format_local_date_label(day))
    slash = re.search(_EXACT_DATE_PATTERNS[2], text)
    if slash:
        day = _infer_month_day(int(slash.group(1)), int(slash.group(2)), now)
        if day is not None:
            return (day, _format_local_date_label(day))
    return None


def _resolve_relative_range(text: str, now: datetime) -> Optional[Dict[str, Any]]:
    today = _start_of_local_day(now)
    for label, offset in (("大前天", -3), ("前天", -2), ("昨天", -1), ("昨日", -1)):
        if label in text:
            day = today + timedelta(days=offset)
            return {
                "label": label,
                "start": day,
                "end": _end_of_local_day(day),
                "reason": "relative_day",
            }
    if re.search("(刚才|刚刚|早些时候|方才)", text):
        return {
            "label": "刚才",
            "start": now - timedelta(hours=6),
            "end": now,
            "reason": "recent_hours",
        }
    recent = re.search("(?:这|最近|前)(\\d+|两|三|几)天", text)
    if recent:
        days = _parse_small_number(recent.group(1)) or 3
        return {
            "label": recent.group(0),
            "start": today - timedelta(days=max(1, days - 1)),
            "end": _end_of_local_day(now),
            "reason": "relative_day_range",
        }
    fallback_days = re.search("(这两天|这几天|前两天|前几天|最近几天)", text)
    if fallback_days:
        return {
            "label": fallback_days.group(1),
            "start": today - timedelta(days=2),
            "end": _end_of_local_day(now),
            "reason": "relative_day_range",
        }
    if re.search("(上周|上星期|上礼拜)", text):
        this_week_start = _start_of_local_week(now)
        start = this_week_start - timedelta(days=7)
        return {
            "label": "上周",
            "start": start,
            "end": _end_of_local_day(start + timedelta(days=6)),
            "reason": "relative_week",
        }
    if re.search("(上个月|上月)", text):
        year = now.year
        month = now.month - 1
        if month < 1:
            year -= 1
            month = 12
        start = _safe_local_date(year, month, 1, now)
        next_month = _safe_local_date(now.year, now.month, 1, now)
        if start is not None and next_month is not None:
            return {
                "label": "上个月",
                "start": start,
                "end": _end_of_local_day(next_month - timedelta(days=1)),
                "reason": "relative_month",
            }
    if "今天" in text:
        return {
            "label": "今天",
            "start": today,
            "end": _end_of_local_day(now),
            "reason": "today_reference",
        }
    return None


def _infer_month_day(month: int, day: int, now: datetime) -> Optional[datetime]:
    candidate = _safe_local_date(now.year, month, day, now)
    if candidate is None:
        return None
    if candidate > _end_of_local_day(now) + timedelta(days=2):
        candidate = _safe_local_date(now.year - 1, month, day, now)
    return candidate


def _safe_local_date(
    year: int, month: int, day: int, now: datetime
) -> Optional[datetime]:
    try:
        return datetime.combine(
            datetime(year, month, day).date(),
            time.min,
            tzinfo=_ensure_aware(now).tzinfo,
        )
    except ValueError:
        return None


def _parse_small_number(value: str) -> int:
    text = str(value or "").strip()
    digits = text.translate(str.maketrans("零〇一二两三四五六七八九", "001223456789"))
    if digits.isdigit():
        return int(digits)
    if re.fullmatch("[1-9]?十[1-9]?", digits):
        (tens, ones) = digits.split("十")
        return int(tens or 1) * 10 + int(ones or 0)
    return 3 if text == "几" else 0


def _start_of_local_day(value: datetime) -> datetime:
    date = _ensure_aware(value)
    return date.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_local_day(value: datetime) -> datetime:
    date = _ensure_aware(value)
    return date.replace(hour=23, minute=59, second=59, microsecond=999999)


def _start_of_local_week(value: datetime) -> datetime:
    day = _start_of_local_day(value)
    return day - timedelta(days=day.isoweekday() - 1)


def _format_local_date_label(value: datetime) -> str:
    date = _ensure_aware(value)
    return f"{date.year:04d}-{date.month:02d}-{date.day:02d}"


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return _ensure_aware(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _ensure_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone()
    return value


def _utc_tz():
    from datetime import timezone

    return timezone.utc
