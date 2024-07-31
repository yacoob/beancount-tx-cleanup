"""Tests for the transaction cleaner."""

import datetime
import re

import pytest
from beancount.core.data import Transaction

from beancount_tx_cleanup.cleaner import (
    Action,
    C,
    E,
    Extractor,
    Extractors,
    M,
    Meta,
    P,
    Payee,
    T,
    Tag,
    TxnPayeeCleanup,
    extractorsUsage,
)
from beancount_tx_cleanup.helpers import Tx
from beancount_tx_cleanup.utils import make_test_transaction_factory

TESTDATE = datetime.date(2071, 3, 14)
TTx = make_test_transaction_factory(TESTDATE)


class TestActionTypes:
    """Tests for Action and all child classes."""

    def testNoGenericActions(self):
        """Verifies that you can't make a plain Action object."""
        with pytest.raises(TypeError):
            _ = Action.new('whatever')

    def testPayeeAction(self):
        """Test Payee action."""
        assert P('word') == Payee.new('word')

    def testTagAction(self):
        """Test Tag action."""
        assert T('tag') == Tag.new('tag')

    def testMetaAction(self):
        """Test Meta action."""
        assert M('name') == Meta.new('name')

    def testCleanerAction(self):
        """Test Cleaner action."""
        assert Payee(v='') == C


class TestExtractorAndExtractors:
    """Extractor(s) related tests."""

    def test_extractor_new(self):
        """Test Extractor creation."""
        # Test with string regex and single Action
        extractor = E('digit eraser', r'^\d+', C)
        assert isinstance(extractor.r, re.Pattern)
        assert isinstance(extractor.actions, list)
        assert extractor.description == 'digit eraser'

        # Test with compiled regex and list of Actions
        extractor = E('digit extractor', re.compile(r'\d+'), [M('digits'), C])
        assert isinstance(extractor.r, re.Pattern)
        assert isinstance(extractor.actions, list)
        assert extractor.description == 'digit extractor'

    def test_extractors(self):
        """Test Extractors creation and addition."""
        exs = Extractors(
            [
                E('digit eraser', r'^\d+', C),
            ],
        )
        # test += with a single extractor
        exs += E('digit extractor', r'\d+', [M('digits'), C])
        assert len(exs) == 2  # noqa: PLR2004
        # test += with an iterable
        exs += exs
        assert len(exs) == 4  # noqa: PLR2004
        assert all(isinstance(x, Extractor) for x in exs)


@pytest.fixture
def extractors():
    """Provide a set of base extractors, which can be modified as needed in each test."""
    return Extractors(
        [
            E(
                "extract '^XY1234', add id=XY1234 to metadata",
                re.compile(r'(?i)^(XY9\d+)'),
                actions=[M('id'), C],
            ),
            E(
                "extract '^ID1234', lowercase it, add id=id1234 to metadata",
                r'(?i)^(ID\d+)',
                actions=[M('id', transformer=lambda s: s.lower()), C],
            ),
            E(
                "match '^GTS1234', add id=v-1234 to metadata, replace 'GTS1234' with '4321'",
                r'(?i)^GTS(\d+)',
                actions=[M('id', v=r'v-\1'), P(v=lambda m: m.group(1)[::-1])],
            ),
            E(
                "match '12.34 ABC@ 0.13 ', extract abc, run it through the lookup table, no replacement",
                r' [\d.]+ ([A-Z]{3})@ [\d.]+ *$',
                actions=[T(r'\1', translation={'jpy': '¥'}), P(r'\g<0>')],
            ),
            E(
                "match '@ 0.13$', replace with ' (0.13 each)', no extraction",
                r'@ ([\d.]+)$',
                actions=P(r' (\1 each)'),
            ),
        ],
    )


class TestCleanerFunctionality:
    """These tests exercise the basic functionality of TxnPayeeCleanup.

    To fully test the custom rules defined by the importer you should also have:
    - a beancount.ingest.regression_pytest based on actual bank CSVs
    - a test that checks if all extractors are tested by the regression tests
    """

    CLEANER_SCENARIOS: tuple[tuple[Transaction, Transaction], ...] = (
        # empty payee
        (TTx(''), TTx('')),
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
        expected_usage = r"""1900-01-01: extract '^XY1234', add id=XY1234 to metadata
1900-01-01: match '12.34 ABC@ 0.13 ', extract abc, run it through the lookup table, no replacement
1900-01-01: match '@ 0.13$', replace with ' (0.13 each)', no extraction
1900-01-01: match '^GTS1234', add id=v-1234 to metadata, replace 'GTS1234' with '4321'
2071-03-14: extract '^ID1234', lowercase it, add id=id1234 to metadata"""
        assert expected_usage == str(extractorsUsage(extractors))
