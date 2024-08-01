"""A function that cleans up the payee field and adds discovered information to entry's metadata."""

import datetime
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import TypeAlias

from beancount.core.data import Transaction
from pydantic import BaseModel
from typing_extensions import override

AGES_AGO = datetime.date(1900, 1, 1)
Replacement: TypeAlias = str | Callable[[re.Match], str]


class Action(BaseModel, ABC):
    """Action describes an action that an Extractor can perform after it matches."""

    v: Replacement = r'\1'
    transformer: Callable[[str], str] = lambda s: s
    translation: dict[str, str] = {}

    def apply(self, m: re.Match) -> str:
        """Work out the requested value out of matched data and transformations."""
        v: str = m.expand(self.v).strip()
        v = self.transformer(v)
        return self.translation.get(v.lower(), v)

    @classmethod
    def new(cls, v: Replacement, **kwargs) -> 'Action':
        """Positional constructor for Action."""
        return cls(v=v, **kwargs)

    @abstractmethod
    def execute(self, m: re.Match, txn: Transaction) -> Transaction:
        """Apply this action to txn, using match data m."""
        pass


class Payee(Action):
    """Set payee field to the result of Action."""

    v: Replacement = ''

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        p: str = m.re.sub(self.v, txn.payee).strip()
        return txn._replace(payee=p)


class Tag(Action):
    """Add a tag from Action."""

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        tags = set(txn.tags or [])
        tags.add(self.apply(m))
        return txn._replace(tags=tags)


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
        return txn._replace(meta=meta)

    @classmethod
    @override
    def new(cls, n: str, **kwargs) -> 'Meta':  # pyright: ignore[reportIncompatibleMethodOverride]
        return cls(n=n, **kwargs)


P = Payee.new
T = Tag.new
M = Meta.new
# cleaner action - replace entire matched string with empty string in the payee field
C = Payee(v='')


class Extractor(BaseModel):
    """Apply regexp to payee, apply Actions."""

    r: re.Pattern
    actions: list[Action] = []
    last_used: datetime.date = AGES_AGO
    description: str = ''

    @classmethod
    def new(  # noqa: D102
        cls,
        desc: str,
        r: str | re.Pattern,
        actions: Action | list[Action],
    ) -> 'Extractor':
        if isinstance(r, str):
            r = re.compile(r)
        if isinstance(actions, Action):
            actions = [actions]
        return cls(r=r, actions=actions, description=desc)


E = Extractor.new


class Extractors(list[Extractor]):
    """A list of Extractor that can handle += operator."""

    def __iadd__(self, e: Extractor | Iterable[Extractor], /) -> 'Extractors':
        """Handle += operator."""
        if isinstance(e, Extractor):
            e = [e]
        return super().__iadd__(e)


def TxnPayeeCleanup(
    txn: Transaction,
    extractors: Extractors | None = None,
    preserveOriginalIn: str | None = None,
) -> Transaction:
    """Extract extra information from the payee field of the Transaction."""
    if extractors is None or not txn.payee:
        return txn
    old_payee = txn.payee
    old_meta = txn.meta.copy()
    for extractor in extractors:
        if m := extractor.r.search(txn.payee):
            # record the most recent timestamp this extractor applied to:
            extractor.last_used = max(txn.date, extractor.last_used)
            for action in extractor.actions:
                txn = action.execute(m, txn)
    if preserveOriginalIn and txn.payee != old_payee:
        txn.meta[preserveOriginalIn] = old_payee
    if txn.meta != old_meta:
        txn = txn._replace(meta=dict(sorted(txn.meta.items())))  # pyright: ignore[reportCallIssue]
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
            [(e.last_used, f'{e.description}') for e in extractors],
        ),
    )
