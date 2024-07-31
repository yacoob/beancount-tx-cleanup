"""Helper functions for tests."""

import datetime
from collections.abc import Callable

from beancount.core.data import Transaction

from beancount_tx_cleanup.helpers import Tx


def make_test_transaction_factory(
    date: datetime.date,
) -> Callable[..., Transaction]:
    """Return a factory of test transactions with a fixed date."""
    return lambda p, **kwargs: Tx(date=date, payee=p, **kwargs)
