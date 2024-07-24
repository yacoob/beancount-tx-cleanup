"""An helper function that cleans up the payee field and adds discovered information to entry's metadata."""

import datetime
import re
from collections.abc import Callable, Iterable
from dataclasses import InitVar, field
from typing import Any, TypeAlias

from beancount.core.data import Transaction
from pydantic import (
    BaseModel,
    Field,
    field_validator,
)
from pydantic.dataclasses import dataclass

AGES_AGO = datetime.date(1900, 1, 1)

ReplacementType: TypeAlias = str | Callable[[re.Match], str]


class Action(BaseModel):
    """Action describes an action that an Extractor can perform after it matches."""

    v: ReplacementType = Field(frozen=True, default=r'\1')
    transformer: Callable[[str], str] = lambda s: s
    translation: dict[str, str] = Field(default_factory=dict)

    def apply(self, m: re.Match) -> str:
        """Work out the requested value out of matched data and transformations."""
        v: str = m.expand(self.v).strip()
        v = self.transformer(v)
        return self.translation.get(v.lower(), v)

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        raise NotImplementedError


class Payee(Action):
    """Set payee field to the result of Action."""

    v: ReplacementType = ''

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        if txn.payee:
            p = m.re.sub(self.v, txn.payee).strip()
            return txn._replace(payee=p)  # pyright: ignore[reportCallIssue]
        return txn


class Tag(Action):
    """Add a tag from Action."""

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        tags = txn.tags or set()
        tags.add(self.apply(m))
        return txn._replace(tags=tags)  # pyright: ignore[reportCallIssue]


class Meta(Action):
    """Add a metadata entry from Action."""

    n: str

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        meta = txn.meta or {}
        v = self.apply(m)
        if self.n in meta:
            meta[self.n] += f', {v}'
        else:
            meta[self.n] = v

        return txn._replace(meta=meta)  # pyright: ignore[reportCallIssue]


P: TypeAlias = Payee
T: TypeAlias = Tag
M: TypeAlias = Meta
# cleaner action - replace entire matched string with empty string in the payee field
C = Payee(v='')


class Extractor(BaseModel):
    """Apply regexp to payee, apply Actions."""

    r: re.Pattern = Field(frozen=True)
    actions: list[Action] = Field(default_factory=list)
    last_used: datetime.date = Field(default=AGES_AGO)

    @field_validator('r', mode='before')
    @classmethod
    def compile_str_to_regexp(cls, v: Any) -> Any:  # noqa: D102
        if isinstance(v, str):
            return re.compile(v)
        return v

    @field_validator('actions', mode='before')
    @classmethod
    def ensure_action_list(cls, v: Any) -> Any:  # noqa: D102
        if isinstance(v, Action):
            return [v]
        return v


E = Extractor
Extractors: TypeAlias = list[Extractor]


def TxnPayeeCleanup(
    txn: Transaction,
    extractors: Extractors | None = None,
    preserveOriginalIn: str | None = None,
) -> Transaction:
    """Extract extra information from the payee field of the Transaction."""
    if extractors is None or not txn.payee:
        return txn
    old_payee = txn.payee
    for extractor in extractors:
        if m := extractor.r.search(txn.payee):
            # record the most recent timestamp this extractor applied to:
            extractor.last_used = max(txn.date, extractor.last_used)
            for action in extractor.actions:
                txn = action.execute(m, txn)
    if preserveOriginalIn and txn.payee != old_payee:
        txn.meta[preserveOriginalIn] = old_payee
        txn.meta = dict(sorted(txn.meta.items()))
    return txn


class ExtractorUsage(BaseModel):
    """Structure for usage reporting of a single extractor."""

    date: datetime.date
    rulename: str

    def __str__(self) -> str:  # noqa: D105
        return f'{self.date.strftime("%Y-%m-%d")}: {self.rulename}'


class ExtractorsUsage(list[ExtractorUsage]):
    """Structure for usage reporting of a whole extractor set."""

    def __init__(self, iterable: Iterable):  # noqa: D107
        super().__init__(
            ExtractorUsage(date=d, rulename=n) for (d, n) in iterable
        )

    def __str__(self) -> str:  # noqa: D105
        return '\n'.join(str(u) for u in self)


def extractorsUsage(extractors: Extractors) -> ExtractorsUsage:
    """For every extractor in the set, reports what was the date of the most recent transaction processed by it."""
    return ExtractorsUsage(
        sorted(
            [(e.last_used, f"r'{e.r.pattern}'") for e in extractors],
        ),
    )
