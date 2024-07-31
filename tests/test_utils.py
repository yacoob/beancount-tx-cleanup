"""Tests for the utils module."""

import datetime

from beancount_tx_cleanup.helpers import Tx
from beancount_tx_cleanup.utils import make_test_transaction_factory


def test_TTx_factory():
    """Test for the testing tx factory."""
    TESTDATE = datetime.date(2098, 9, 7)
    TTx = make_test_transaction_factory(TESTDATE)
    tx = TTx('gelato', tags={'tasty'})
    assert tx == Tx(
        date=TESTDATE,
        payee='gelato',
        tags={'tasty'},
    )
