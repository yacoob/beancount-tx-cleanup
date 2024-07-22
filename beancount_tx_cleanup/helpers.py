"""Helper functions for creating beancount Directives.

NOTE: beancount.core.data types are all created via a helper function in
beancount v2 and as a result they don't play well with static type checking :[
https://github.com/jmgilman/beancount-stubs helps a lot here.

beancount v3 does away with that helper function precisely for that reason :)
https://github.com/beancount/beancount/commit/7ee06ff7f922950cd36a067c2fad54370efeeaf5
"""

import datetime
from decimal import Decimal

from beancount.core.amount import Amount
from beancount.core.data import Balance, Flag, Open, Posting, Transaction

DEFAULT_CURRENCY = 'EUR'
DEFAULT_FLAG = '!'
EMPTY_TAGS = set()
EMPTY_LINKS = set()
EMPTY_META = {}


def Op(
    account: str,
    date: datetime.date,
    *,
    currency: str = DEFAULT_CURRENCY,
) -> Open:
    """Create an Open directive."""
    return Open(EMPTY_META, date, account, [currency], None)


def Bal(
    account: str,
    amount: str,
    date: datetime.date,
    *,
    currency: str = DEFAULT_CURRENCY,
    meta: dict[str, str] | None = None,
):
    """Create a Balance directive."""
    return Balance(
        meta or EMPTY_META,
        date,
        account,
        Amount(Decimal(amount), currency),
        None,
        None,
    )


def Post(
    account: str,
    *,
    amount: str | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> Posting:
    """Create a Posting object."""
    return Posting(
        account,
        # beancount v2 handles amount=None just fine, for postings whose
        # amount should be inferred. v3 lists this field as Optional[Amount].
        Amount(Decimal(amount), currency) if amount else None,  # pyright: ignore reportArgumentType
        None,
        None,
        None,
        None,
    )


def Tx(  # noqa: PLR0913
    date: datetime.date,
    payee: str | None = None,
    *,
    narration: str | None = None,
    postings: list[Posting] | None = None,
    flag: Flag = DEFAULT_FLAG,
    tags: set[str] | None = None,
    meta: dict[str, str] | None = None,
):
    """Create a Transaction directive."""
    return Transaction(
        meta.copy() if meta else EMPTY_META,
        date,
        flag,
        payee.strip() if payee else '',
        narration.strip() if narration else '',
        tags.copy() if tags else EMPTY_TAGS,
        EMPTY_LINKS,
        postings or [],
    )
