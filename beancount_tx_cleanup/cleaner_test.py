"""Tests for the transaction cleaner."""

import datetime
from typing import Callable

import pytest
from beancount.core.data import Transaction
from beancount_tx_cleanup.cleaner import (
    C,
    E,
    Extractors,
    M,
    P,
    T,
    TxnPayeeCleanup,
    extractorsUsage,
)
from beancount_tx_cleanup.helpers import Tx


def TestTxMaker(date: datetime.date) -> Callable[..., Transaction]:
    """Return a factory of test transactions with a fixed date."""
    return lambda p, **kwargs: Tx(date=date, payee=p, **kwargs)


@pytest.fixture
def extractors():
    """Provide a set of base extractors, which can be modified as needed in each test."""
    return Extractors([
        # extract '^XY1234', add id=XY1234 to metadata
        E(r'(?i)^(XY9\d+)',actions=[M('id'), C]),
        # extract '^ID1234', lowercase it, add id=id1234 to metadata
        E(r'(?i)^(ID\d+)', actions=[M('id', transformer=lambda s: s.lower()), C]),
        # match '^GTS1234', add id=v-1234 to metadata, replace 'GTS1234' with '4321'
        E(r'(?i)^GTS(\d+)', actions=[M('id', v=r'v-\1'), P(v=lambda m: m.group(1)[::-1])]),
        # match '12.34 ABC@ 0.13 ', extract abc, run it through the lookup table, no replacement
        E(r' [\d.]+ ([A-Z]{3})@ [\d.]+ *$', actions=[T(r'\1', translation={'jpy': '¥'}), P(r'\g<0>')]),
        # match '@ 0.13$', replace with ' (0.13 each)', no extraction
        E(r'@ ([\d.]+)$', actions=P(r' (\1 each)')),
    ])  # fmt: skip


TESTDATE = datetime.date(2071, 3, 14)
TTx = TestTxMaker(TESTDATE)


class TestCleanerFunctionality:
    """These tests exercise the basic functionality of TxnPayeeCleanup.

    To fully test the custom rules defined by the importer you should also have:
    - a beancount.ingest.regression_pytest based on actual bank CSVs
    - a test that checks if all extractors are tested by the regression tests
    """

    CLEANER_SCENARIOS: tuple[tuple[Transaction, Transaction], ...] = (
        # no extractor matches this payee
        (TTx('Fredrikson*and Sons Ltd.'), TTx('Fredrikson*and Sons Ltd.')),
        # straightforward extraction
        (TTx('XY90210 Happy Days'), TTx('Happy Days', meta={'id': 'XY90210'})),
        # as above, but the input transaction already has some metadata
        (TTx('XY90210 Happy Days', meta={'length': '7 days'}), TTx('Happy Days', meta={'id': 'XY90210', 'length': '7 days'})),
        # as above, but the input transaction already has exactly this field in metadata
        (TTx('XY90210 Happy Days', meta={'id': 'Agent 007'}), TTx('Happy Days', meta={'id': 'Agent 007, XY90210'})),
        # extraction plus a lambda transformer
        (TTx('ID1234 standing order'), TTx('standing order', meta={'id': 'id1234'})),
        # extraction with a custom value plus a lambda replacement
        (TTx('GTS98765 regular saver'), TTx('56789 regular saver', meta={'id': 'v-98765'})),
        # extraction to a tag, a lookup table then a cleanup with a string replacement
        (TTx('AirSide Coffee 12.30 JPY@ 0.13  '), TTx('AirSide Coffee 12.30 JPY (0.13 each)', tags={'¥'})),
        # as above, but the input transaction already has some tags
        (TTx('AirSide Coffee 12.30 JPY@ 0.13  ', tags={'tasty'}), TTx('AirSide Coffee 12.30 JPY (0.13 each)', tags={'¥', 'tasty'})),
        # as above, but the input transaction has an exactly identical tag
        (TTx('AirSide Coffee 12.30 JPY@ 0.13  ', tags={'¥'}), TTx('AirSide Coffee 12.30 JPY (0.13 each)', tags={'¥'})),
    )  # fmt: skip

    @pytest.mark.parametrize(('in_tx', 'out_tx'), CLEANER_SCENARIOS)
    def test_cleaning(self, extractors: Extractors, in_tx, out_tx):
        """Test different scenarios from CLEANER_SCENARIOS."""
        assert out_tx == TxnPayeeCleanup(in_tx, extractors)

    def test_empty_extractors(self):
        """Empty extractor list should result in no changes."""
        tx = TTx('shai hulud vendor')
        assert tx == TxnPayeeCleanup(tx)

    def test_save_original_payee(self, extractors):
        """TxnPayeeCleanup should preserve the tx's original payee."""
        p = 'ID19283 standing order'
        tx = TTx(p)
        clean_tx = TTx(
            'standing order',
            meta={'id': 'id19283', 'previously': p},
        )
        assert clean_tx == TxnPayeeCleanup(
            tx,
            extractors,
            preserveOriginalIn='previously',
        )

    def test_extractor_order_swap(self, extractors):
        """The ordering of extractors is important; in this test we swap the order of applications of  __CLEANUP and TAG_DESTINATION."""
        e: Extractors = extractors.copy()
        e[-2], e[-1] = e[-1], e[-2]
        tx = TTx('AirSide Coffee 12.30 JPY@ 0.13  ')
        # As a result of the order swap no tag is extracted - by the time TAG_DESTINATION extractor
        # is applied, the string it'd match on has already been cleaned by the __CLEANUP extractor.
        clean_tx = TTx('AirSide Coffee 12.30 JPY (0.13 each)', tags=set())
        assert clean_tx == TxnPayeeCleanup(tx, e)


class TestExtractorsUsageReporting:
    """Verifies extractorsUsage contents and format."""

    date = datetime.date(2071, 3, 14)

    def test_reporting(self, extractors):
        """TxnPayeeCleanup records date of the most recent tx each extractor matched."""
        _ = TxnPayeeCleanup(
            Tx(self.date, 'ID29381 Grooveshark subscription'),
            extractors,
        )
        print(extractorsUsage(extractors))
        expected_usage = r"""1900-01-01: r' [\d.]+ ([A-Z]{3})@ [\d.]+ *$'
1900-01-01: r'(?i)^(XY9\d+)'
1900-01-01: r'(?i)^GTS(\d+)'
1900-01-01: r'@ ([\d.]+)$'
2071-03-14: r'(?i)^(ID\d+)'"""
        assert expected_usage == str(extractorsUsage(extractors))
