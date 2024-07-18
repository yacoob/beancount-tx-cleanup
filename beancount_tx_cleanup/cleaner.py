"""An helper function that cleans up the payee field and adds discovered information to entry's metadata."""

import datetime
import re
from collections.abc import Callable, Iterable
from dataclasses import InitVar, field

from pydantic.dataclasses import dataclass

TAG_DESTINATION = '__TAG'
CLEANUP = '__CLEANUP'
AGES_AGO = datetime.date(1900, 1, 1)


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
class Extractor:
    """Single extractor definition."""

    match: InitVar[str]
    regexp: re.Pattern = field(init=False)
    replacement: str | Callable[[re.Match], str] = field(kw_only=True, default='')
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
E = Extractor
Extractors = dict[str, tuple[Extractor, ...]]


def TxnPayeeCleanup(
    txn,
    extractors: Extractors | None = None,
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
                if txn.date > extractor.last_used:
                    extractor.last_used = txn.date
                # stash the original payee for future record
                if preserveOriginalIn and preserveOriginalIn not in meta:
                    meta[preserveOriginalIn] = original_payee
                # replace the match in payee
                payee = re.sub(extractor.regexp, extractor.replacement, payee).strip()
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


@dataclass
class ExtractorUsage:
    """Structure for usage reporting of a single extractor."""

    date: datetime.date
    rulename: str

    def __str__(self) -> str:  # noqa: D105
        return f'{self.date.strftime("%Y-%m-%d")}: {self.rulename}'


class ExtractorsUsage(list[ExtractorUsage]):
    """Structure for usage reporting of a whole extractor set."""

    def __init__(self, iterable: Iterable):  # noqa: D107
        super().__init__(ExtractorUsage(*x) for x in iterable)

    def __str__(self) -> str:  # noqa: D105
        return '\n'.join(str(u) for u in self)


def extractorsUsage(extractors: Extractors) -> ExtractorsUsage:
    """For every extractor in the set, reports what was the date of the most recent transaction processed by it."""
    return ExtractorsUsage(
        sorted(
            [
                (e.last_used, f'{name} - {e.regexp}')
                for name, es in extractors.items()
                for e in es
            ],
        ),
    )
