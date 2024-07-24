"""Tests for the transaction cleaner."""

import datetime
from dataclasses import field

import pytest
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
from pydantic.dataclasses import dataclass


@dataclass
class CleanerScenario:
    """A dataclass describing a test scenario for cleaner.

    TxnPayeeCleanup should turn
      Tx(payee=input)
    into
      Tx(payee, tags, meta)
    """

    input_payee: str
    payee: str
    input_tags: set = field(default_factory=set, kw_only=True)
    input_meta: dict = field(default_factory=dict, kw_only=True)
    tags: set = field(default_factory=set, kw_only=True)
    meta: dict = field(default_factory=dict, kw_only=True)


CS = CleanerScenario


@pytest.fixture
def extractors():
    """Provide a set of base extractors, which can be modified as needed in each test."""
    return Extractors([
        # extract '^XY1234', add id=XY1234 to metadata
        E(regexp=r'(?i)^(XY9\d+)',actions=[M(name='id'), C]),                                                    # pyright: ignore[reportArgumentType]
        # extract '^ID1234', lowercase it, add id=id1234 to metadata
        E(regexp=r'(?i)^(ID\d+)', actions=[M(name='id', transformer=lambda s: s.lower()), C]),                   # pyright: ignore[reportArgumentType]
        # match '^GTS1234', add id=v-1234 to metadata, replace 'GTS1234' with '4321'
        E(regexp=r'(?i)^GTS(\d+)', actions=[M(name='id', value=r'v-\1'), P(value=lambda m: m.group(1)[::-1])]),  # pyright: ignore[reportArgumentType]
        # match '12.34 ABC@ 0.13 $'', extract abc, run it through the lookup table, no replacement
        E(regexp=r' [\d.]+ ([A-Z]{3})@ [\d.]+ *$', actions=[T(translation={'jpy': '¥'}), P(value=r'\g<0>')]),    # pyright: ignore[reportArgumentType]
        # match '@ 0.13$', replace with ' (0.13 each)', no extraction
        E(regexp=r'@ ([\d.]+)$', actions=P(value=r' (\1 each)')),                                                # pyright: ignore[reportArgumentType]
    ])  # fmt: skip


class TestCleanerFunctionality:
    """These tests exercise the basic functionality of TxnPayeeCleanup.

    To fully test the custom rules defined by the importer you should also have:
    - a beancount.ingest.regression_pytest based on actual bank CSVs
    - a test that checks if all extractors are tested by the regression tests
    """

    date = datetime.date(2071, 3, 14)
    CLEANER_SCENARIOS = (
        # no extractor matches this payee
        CS('Fredrikson*and Sons Ltd.', 'Fredrikson*and Sons Ltd.'),
        # straightforward extraction
        CS('XY90210 Happy Days', 'Happy Days', meta={'id': 'XY90210'}),
        # as above, but the input transaction already has some metadata
        CS('XY90210 Happy Days', 'Happy Days', input_meta={'length': '7 days'}, meta={'id': 'XY90210', 'length': '7 days'}),
        # as above, but the input transaction already has exactly this field in metadata
        CS('XY90210 Happy Days', 'Happy Days', input_meta={'id': 'Agent 007'}, meta={'id': 'Agent 007, XY90210'}),
        # extraction plus a lambda transformer
        CS('ID1234 standing order', 'standing order', meta={'id': 'id1234'}),
        # extraction with a custom value plus a lambda replacement
        CS('GTS98765 regular saver', '56789 regular saver', meta={'id': 'v-98765'}),
        # extraction to a tag, a lookup table then a cleanup with a string replacement
        CS('AirSide Coffee 12.30 JPY@ 0.13  ', 'AirSide Coffee 12.30 JPY (0.13 each)', tags={'¥'}),
        # as above, but the input transaction already has some tags
        CS('AirSide Coffee 12.30 JPY@ 0.13  ', 'AirSide Coffee 12.30 JPY (0.13 each)', input_tags={'tasty'}, tags={'¥', 'tasty'}),
        # as above, but the input transaction has an exactly identical tag
        CS('AirSide Coffee 12.30 JPY@ 0.13  ', 'AirSide Coffee 12.30 JPY (0.13 each)', input_tags={'¥'}, tags={'¥'}),
    )  # fmt: skip

    @pytest.mark.parametrize('scenario', CLEANER_SCENARIOS)
    def test_cleaning(self, extractors, scenario):
        """Test different scenarios from CLEANER_SCENARIOS."""
        tx = Tx(
            self.date,
            scenario.input_payee,
            tags=scenario.input_tags,
            meta=scenario.input_meta,
        )
        clean_tx = Tx(
            self.date,
            scenario.payee,
            tags=scenario.tags,
            meta=scenario.meta,
        )
        assert clean_tx == TxnPayeeCleanup(
            tx,
            extractors,
        )

    def test_empty_extractors(self):
        """Empty extractor list should result in no changes."""
        tx = Tx(self.date, 'shai hulud extract')
        assert tx == TxnPayeeCleanup(tx, None)

    def test_save_original_payee(self, extractors):
        """TxnPayeeCleanup should preserve the tx's original payee."""
        p = 'ID19283 standing order'
        tx = Tx(self.date, p)
        clean_tx = Tx(
            self.date,
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
        scenario = CS('AirSide Coffee 12.30 JPY@ 0.13  ', 'AirSide Coffee 12.30 JPY (0.13 each)', tags={'¥'})  # fmt: skip
        tx = Tx(self.date, scenario.input_payee)
        # As a result of the order swap no tag is extracted - by the time TAG_DESTINATION extractor
        # is applied, the string it'd match on has already been cleaned by the __CLEANUP extractor.
        clean_tx = Tx(self.date, scenario.payee, tags=set())
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
