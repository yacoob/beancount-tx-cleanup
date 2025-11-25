"""Tests for beancount helpers."""

import datetime
from decimal import Decimal
from typing import ClassVar

from beancount.core.amount import Amount
from beancount.core.data import EMPTY_SET, Balance, Open, Posting, Transaction

from beancount_tx_cleanup.helpers import (
    DEFAULT_CURRENCY,
    DEFAULT_FLAG,
    Bal,
    Meta,
    Op,
    Post,
    Tx,
)


class TestMakeHelpers:
    """Test convenience helpers.

    All of those tests two call variants: one with a minimal required set
    of arguments, one with a full set.
    """

    date = datetime.date(1985, 10, 26)
    account = 'Assets:Secret-stash'
    amount_str = '420'
    amount = Amount(Decimal(420), DEFAULT_CURRENCY)
    currency = 'JPY'
    amount2 = Amount(Decimal(420), currency)
    payee = 'Damage Inc.'
    narration = 'May contract'
    tags = frozenset({'wet-work'})
    links = frozenset({'http://damage.inc'})
    meta: ClassVar[Meta] = {'number_of_bullets': 'seven'}

    def test_makeOpen(self):  # noqa: D102
        # test minimal argument set
        x = Op(self.account, self.date)
        o = Open({}, self.date, self.account, [DEFAULT_CURRENCY], None)
        assert x == o
        # test full argument set
        y = Op(self.account, self.date, currency=self.currency)
        o = Open({}, self.date, self.account, [self.currency], None)
        assert y == o

    def test_makeBalance(self):  # noqa: D102
        # test minimal argument set
        x = Bal(self.account, self.amount_str, self.date)
        b = Balance({}, self.date, self.account, self.amount, None, None)
        assert x == b
        # test full argument set
        y = Bal(
            self.account,
            self.amount_str,
            self.date,
            currency=self.currency,
            meta=self.meta,
        )
        b2 = Balance(
            self.meta,
            self.date,
            self.account,
            self.amount2,
            None,
            None,
        )
        assert y == b2

    def test_makePosting(self):  # noqa: D102
        # test minimal argument set
        x = Post(self.account)
        p = Posting(self.account, None, None, None, None, None)  # pyright: ignore reportArgumentType
        assert x == p
        # test full argument set
        y = Post(self.account, amount=self.amount_str, currency=self.currency)
        p2 = Posting(self.account, self.amount2, None, None, None, None)
        assert y == p2

    def test_makeTransaction(self):  # noqa: D102
        # test minimal argument set
        x = Tx(self.date)
        t = Transaction(
            {},
            self.date,
            DEFAULT_FLAG,
            '',
            '',
            EMPTY_SET,
            EMPTY_SET,
            [],
        )
        assert x == t

        # test full argument set
        p = Post(self.account)
        y = Tx(
            self.date,
            self.payee,
            narration=self.narration,
            postings=[p],
            flag='*',
            tags=EMPTY_SET,
            meta=self.meta,
        )
        t = Transaction(
            self.meta,
            self.date,
            '*',
            self.payee,
            self.narration,
            EMPTY_SET,
            EMPTY_SET,
            [p],
        )
        assert y == t
