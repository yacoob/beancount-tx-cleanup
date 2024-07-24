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

    value: ReplacementType = Field(frozen=True, default=r'\1')
    transformer: Callable[[str], str] = lambda s: s
    translation: dict[str, str] = Field(default_factory=dict)

    def apply(self, m: re.Match) -> str:
        """Work out the requested value out of matched data and transformations."""
        v: str = m.expand(self.value).strip()
        v = self.transformer(v)
        return self.translation.get(v.lower(), v)

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        raise NotImplementedError


class Payee(Action):
    """Set payee field to the result of Action."""

    value: ReplacementType = ''

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        if txn.payee:
            p = m.re.sub(self.value, txn.payee).strip()
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

    name: str

    def execute(self, m: re.Match, txn: Transaction) -> Transaction:  # noqa: D102
        meta = txn.meta or {}
        v = self.apply(m)
        if self.name in meta:
            meta[self.name] += f', {v}'
        else:
            meta[self.name] = v

        return txn._replace(meta=meta)  # pyright: ignore[reportCallIssue]


P: TypeAlias = Payee
T: TypeAlias = Tag
M: TypeAlias = Meta
# cleaner action - replace entire matched string with empty string in the payee field
C = Payee(value='')


class Extractor(BaseModel):
    """Apply regexp to payee, apply Actions."""

    regexp: re.Pattern = Field(frozen=True)
    actions: list[Action] = Field(default_factory=list)
    last_used: datetime.date = Field(default=AGES_AGO)

    @field_validator('regexp', mode='before')
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
        if m := extractor.regexp.search(txn.payee):
            # record the most recent timestamp this extractor applied to:
            extractor.last_used = max(txn.date, extractor.last_used)
            for action in extractor.actions:
                txn = action.execute(m, txn)
    if preserveOriginalIn and txn.payee != old_payee:
        txn.meta[preserveOriginalIn] = old_payee
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
            [(e.last_used, f"r'{e.regexp.pattern}'") for e in extractors],
        ),
    )


# # # # # # OLD EXTRACTORS CODE
TAG_DESTINATION = '__TAG'
CLEANUP = '__CLEANUP'


# Each Extractor describes a transformation performed on the transaction's payee.
# An Extractor object gets initialized with:
# ```
#     match: RE to match payee against
#     replacement: string or lambda taking a re.Match object (see: re.sub)
#                  to replace matched part of the payee field with (default='')
#     value: string to use as a value of the metadata, fed to Match.expand() (default='\1')
#     transformer: lambda to apply to the value string (default: lambda s: s)
#     translation: optional lookup table to look up value.lower() (default={})
# ```
@dataclass
class OldExtractor:
    """Single extractor definition."""

    match: InitVar[str]
    regexp: re.Pattern = field(init=False)
    replacement: str | Callable[[re.Match], str] = field(
        kw_only=True,
        default='',
    )
    value: str = field(kw_only=True, default=r'\1')
    transformer: Callable[[str], str] = field(kw_only=True, default=lambda s: s)
    translation: dict[str, str] = field(kw_only=True, default_factory=dict)
    last_used: datetime.date = field(kw_only=True, default=AGES_AGO)

    def __post_init__(self, match):  # noqa: D105
        self.regexp = re.compile(match)


# Each entry in Extractors dict looks like this:
# `name: (ExtractorA, ExtractorB, ...)`
#
# If an extractor successfully applies, metadata gets a new entry of `name: value`.
# If the `name` is `TAG_DESTINATION`, a tag is added instead of a metadata entry.
# If the `name` is `CLEANUP`, only the replacement is performed, and no value is extracted.
#
# NOTE: The ordering of `name`s in Extractors and Extractor objects themselves on the list
# is important; some REs use anchors that won't match anymore after a preceeding extractor
# modifies the payee string.
#
OldE = OldExtractor
OldExtractors = dict[str, tuple[OldExtractor, ...]]


def OldTxnPayeeCleanup(
    txn,
    extractors: OldExtractors | None = None,
    preserveOriginalIn: str | None = None,
):
    """Extract extra information from the payee field of the Transaction."""
    if extractors is None:
        extractors = {}
    # get current txn fields
    original_payee = payee = txn.payee
    tags = set(txn.tags)
    meta = txn.meta.copy()
    # remove selected stars from the description, AIB loves to sprinkle them over
    payee = payee.strip('*').replace(' *', ' ').replace('* ', ' ').strip()
    # apply extractors to the payee field
    for name, list_of_extractors in extractors.items():
        for extractor in list_of_extractors:
            if m := extractor.regexp.search(payee):
                # record the most recent timestamp this extractor applied to:
                extractor.last_used = max(txn.date, extractor.last_used)
                # stash the original payee for future record
                if preserveOriginalIn and preserveOriginalIn not in meta:
                    meta[preserveOriginalIn] = original_payee
                # replace the match in payee
                payee = re.sub(
                    extractor.regexp,
                    extractor.replacement,
                    payee,
                ).strip()
                # Was this a cleanup extractor?
                if name is CLEANUP:
                    continue
                # extract the value
                value = m.expand(extractor.value).strip()
                # apply the transformation
                value = extractor.transformer(value)
                # run the value through a lookup table
                value = extractor.translation.get(value.lower(), value)
                # assign the value to tag set or metadata entry
                if name is TAG_DESTINATION:
                    tags.add(value)
                elif name in meta:
                    meta[name] += f', {value}'
                else:
                    meta[name] = value
    return txn._replace(payee=payee, tags=tags, meta=dict(sorted(meta.items())))
