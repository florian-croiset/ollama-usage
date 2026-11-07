"""The report, as typed read-only objects mirroring schema 1.0."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Range = Literal["24h", "7d", "30d"]
"""Period covered by the usage. Each one ends now."""

_PARTIAL_CODES = frozenset({"balance_unavailable", "usage_unavailable"})
_FRACTION = re.compile(r"\.(\d+)")


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    # Python 3.10 accepts neither "Z" nor fractions other than 3 or 6 digits.
    text = _FRACTION.sub(lambda match: "." + match.group(1)[:6].ljust(6, "0"), value, count=1)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class Window:
    """How much of a quota window is used, and when it resets.

    Attributes:
        used_pct: Share of the window used, from 0 to 100.
        starts_at: Start of the window. Only known for the monthly window.
        resets_at: When the window resets.
    """

    used_pct: float
    starts_at: datetime | None
    resets_at: datetime | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Window:
        """Reads a window from its schema 1.0 form."""
        return cls(
            used_pct=float(data["used_pct"]),
            starts_at=_timestamp(data.get("starts_at")),
            resets_at=_timestamp(data.get("resets_at")),
        )


@dataclass(frozen=True, slots=True)
class Windows:
    """The quota windows of a plan; those that do not apply are ``None``.

    A current plan has ``monthly``. A plan subscribed before Ollama's 2026-08-31
    pricing change has ``session`` (five hours) and ``weekly``.
    """

    monthly: Window | None
    session: Window | None
    weekly: Window | None

    def items(self) -> Iterator[tuple[str, Window]]:
        """Yields ``(name, window)`` for the windows present: monthly, session, weekly."""
        for name in ("monthly", "session", "weekly"):
            window = getattr(self, name)
            if window is not None:
                yield name, window

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Windows:
        """Reads the windows from their schema 1.0 form."""

        def window(name: str) -> Window | None:
            value = data.get(name)
            return None if value is None else Window.from_dict(value)

        return cls(monthly=window("monthly"), session=window("session"), weekly=window("weekly"))


@dataclass(frozen=True, slots=True)
class IncludedCredits:
    """The included credits of the current monthly period, in US dollars.

    Attributes:
        balance_usd: What is left for this period.
        allowance_usd: What the plan includes for a whole period.
        spent_usd: What has been used this period.
    """

    balance_usd: float
    allowance_usd: float
    spent_usd: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IncludedCredits:
        """Reads included credits from their schema 1.0 form."""
        return cls(
            balance_usd=float(data["balance_usd"]),
            allowance_usd=float(data["allowance_usd"]),
            spent_usd=float(data["spent_usd"]),
        )


@dataclass(frozen=True, slots=True)
class Credits:
    """Credit balances, in US dollars.

    Attributes:
        included: The plan's included credits; ``None`` on plans subscribed before
            the pricing change.
        purchased_balance_usd: Remaining purchased credits that have not expired.
    """

    included: IncludedCredits | None
    purchased_balance_usd: float | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Credits:
        """Reads credits from their schema 1.0 form."""
        included = data.get("included")
        purchased = data.get("purchased_balance_usd")
        return cls(
            included=None if included is None else IncludedCredits.from_dict(included),
            purchased_balance_usd=None if purchased is None else float(purchased),
        )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """The usage of one model.

    Attributes:
        model: Model name as Ollama reports it.
        requests: Number of requests.
        cost_usd: Cost in US dollars, whether covered by the plan or paid with credits.
        input_tokens: Input tokens, cached ones included.
        cached_input_tokens: Input tokens served from the cache.
        output_tokens: Output tokens.
        share_pct: Share of the total cost, from 0 to 100, or of the requests when
            nothing was billed.
    """

    model: str
    requests: int
    cost_usd: float
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    share_pct: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModelUsage:
        """Reads a model's usage from its schema 1.0 form."""
        return cls(model=str(data["model"]), **_metrics(data), share_pct=float(data["share_pct"]))


@dataclass(frozen=True, slots=True)
class OtherUsage:
    """The combined usage of the models beyond the first ten.

    Its attributes mean the same as those of `ModelUsage`.
    """

    requests: int
    cost_usd: float
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    share_pct: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OtherUsage:
        """Reads the remainder from its schema 1.0 form."""
        return cls(**_metrics(data), share_pct=float(data["share_pct"]))


@dataclass(frozen=True, slots=True)
class Usage:
    """Requests, cost and tokens over a fixed range, overall and per model.

    The totals mean the same as the attributes of `ModelUsage`.

    Attributes:
        range: The range covered. It ends now and is not aligned with the quota period.
        from_: Start of the range, inclusive.
        until: End of the range, exclusive.
        models: Up to ten models, most expensive first.
        other: The models beyond the first ten, combined; ``None`` when there are none.
    """

    range: Range
    from_: datetime | None
    until: datetime | None
    requests: int
    cost_usd: float
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    models: tuple[ModelUsage, ...]
    other: OtherUsage | None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Usage:
        """Reads the usage from its schema 1.0 form."""
        other = data.get("other")
        return cls(
            range=data["range"],
            from_=_timestamp(data.get("from")),
            until=_timestamp(data.get("until")),
            **_metrics(data),
            models=tuple(ModelUsage.from_dict(model) for model in data["models"]),
            other=None if other is None else OtherUsage.from_dict(other),
        )


@dataclass(frozen=True, slots=True)
class ReportWarning:
    """Something that went wrong without preventing the report.

    Attributes:
        code: Stable identifier, safe to compare, e.g. ``"usage_unavailable"``.
        message: Human-readable explanation. Its wording may change.
    """

    code: str
    message: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReportWarning:
        """Reads a warning from its schema 1.0 form."""
        return cls(code=str(data["code"]), message=str(data["message"]))


@dataclass(frozen=True, slots=True)
class Report:
    """Everything one fetch learned about the account.

    Attributes:
        schema_version: Version of the JSON contract, ``"1.0"``.
        fetched_at: When the report was built.
        plan: Plan name in lower case, e.g. ``"free"``; ``None`` if unknown.
        windows: The quota windows.
        credits: Credit balances; ``None`` when ``/api/balance`` failed.
        usage: Usage over a range; ``None`` when ``/api/usage`` failed.
        warnings: What went wrong without preventing the report.
    """

    schema_version: str
    fetched_at: datetime
    plan: str | None
    windows: Windows
    credits: Credits | None
    usage: Usage | None
    warnings: tuple[ReportWarning, ...]
    _data: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def is_partial(self) -> bool:
        """Whether ``/api/balance`` or ``/api/usage`` failed, leaving part of it empty."""
        return any(warning.code in _PARTIAL_CODES for warning in self.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Returns the report in its schema 1.0 JSON form."""
        return copy.deepcopy(dict(self._data))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Report:
        """Reads a report from its schema 1.0 JSON form, e.g. ``ollama-usage --json``."""
        fetched_at = _timestamp(data["fetched_at"])
        if fetched_at is None:
            raise ValueError("fetched_at is required")
        credits = data.get("credits")
        usage = data.get("usage")
        return cls(
            schema_version=str(data["schema_version"]),
            fetched_at=fetched_at,
            plan=data.get("plan"),
            windows=Windows.from_dict(data["windows"]),
            credits=None if credits is None else Credits.from_dict(credits),
            usage=None if usage is None else Usage.from_dict(usage),
            warnings=tuple(ReportWarning.from_dict(w) for w in data.get("warnings", ())),
            _data=copy.deepcopy(dict(data)),
        )


def _metrics(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "requests": int(data["requests"]),
        "cost_usd": float(data["cost_usd"]),
        "input_tokens": int(data["input_tokens"]),
        "cached_input_tokens": int(data["cached_input_tokens"]),
        "output_tokens": int(data["output_tokens"]),
    }
