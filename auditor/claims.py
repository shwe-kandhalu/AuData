from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Iterable, Literal


StatKind = Literal["t", "F", "chi_square", "r"]
Comparator = Literal["=", "<", ">"]


@dataclass(frozen=True)
class StatisticalClaim:
    kind: StatKind
    statistic: float
    reported_p: float
    comparator: Comparator
    raw: str
    start_char: int
    end_char: int
    df1: int | None = None
    df2: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


P_VALUE = r"p\s*(?P<comp>[=<>])\s*(?P<p>(?:0?\.\d+|1\.0+|1|0)(?:e[-+]?\d+)?)"

PATTERNS: tuple[tuple[StatKind, re.Pattern[str]], ...] = (
    (
        "t",
        re.compile(
            rf"\bt\s*\(\s*(?P<df1>\d+)\s*\)\s*=\s*(?P<stat>-?\d+(?:\.\d+)?)\s*,?\s*{P_VALUE}",
            re.IGNORECASE,
        ),
    ),
    (
        "F",
        re.compile(
            rf"\bF\s*\(\s*(?P<df1>\d+)\s*,\s*(?P<df2>\d+)\s*\)\s*=\s*(?P<stat>\d+(?:\.\d+)?)\s*,?\s*{P_VALUE}",
            re.IGNORECASE,
        ),
    ),
    (
        "chi_square",
        re.compile(
            rf"(?:χ\s*2|χ²|chi[-\s]?square|chi\s*2)\s*\(\s*(?P<df1>\d+)\s*\)\s*=\s*(?P<stat>\d+(?:\.\d+)?)\s*,?\s*{P_VALUE}",
            re.IGNORECASE,
        ),
    ),
    (
        "r",
        re.compile(
            rf"\br\s*\(\s*(?P<df1>\d+)\s*\)\s*=\s*(?P<stat>-?(?:0?\.\d+|1\.0+|1|0))\s*,?\s*{P_VALUE}",
            re.IGNORECASE,
        ),
    ),
)


def extract_claims(text: str) -> list[StatisticalClaim]:
    claims: list[StatisticalClaim] = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            claims.append(
                StatisticalClaim(
                    kind=kind,
                    statistic=float(match.group("stat")),
                    reported_p=float(match.group("p")),
                    comparator=match.group("comp"),  # type: ignore[arg-type]
                    raw=match.group(0),
                    start_char=match.start(),
                    end_char=match.end(),
                    df1=int(match.group("df1")) if match.groupdict().get("df1") else None,
                    df2=int(match.group("df2")) if match.groupdict().get("df2") else None,
                )
            )
    return sorted(claims, key=lambda c: c.start_char)


def claims_to_dicts(claims: Iterable[StatisticalClaim]) -> list[dict]:
    return [claim.to_dict() for claim in claims]
