"""Contract tests for the generated root site (session arena-79cc0bd5).

Deliberately narrow, because other sessions own most of this area right now:
these assertions guard three rules that the brief states and that a generator
change can silently break.

  1. **Never a silent blank.** A value that could not be read from the official
     demo API must render the UNVERIFIED badge, so an empty cell can never be
     misread as a zero.
  2. **The settlement rule is stated for both sides.** Kalshi pays $1 per
     contract to the winning side — Yes holders on a Yes outcome *and* No
     holders on a No outcome. Wording that implies NO never pays is a factual
     error, not a style choice.
  3. **Fees carry their basis.** Both engines read each series' own
     ``fee_multiplier`` / ``fee_type`` from the official ``GET /series``
     response and print that basis per row, so the Flagged-for-Review page
     publishes the remaining *source* disagreement (the fee PDF vs the demo
     API field for some series) with its official sources, and the
     methodology page may never again claim a blanket "multiplier of 1 for
     every series" — that stopped being true when the collector's ledger
     started threading the series multiplier (request R-79CC-1, Board J).

`tools/root_pages_render.mjs` covers the DOM side of the same contract.
"""

from __future__ import annotations

import os
import re
import unittest

from site_build import extras, flagpage, format as fmt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


class TestMissingValues(unittest.TestCase):
    """Rule 1: absent data is flagged, never left blank."""

    def test_source_backed_accessors_flag_a_missing_value(self):
        for name in ("esc", "money", "cents", "num", "result_chip"):
            fn = getattr(fmt, name)
            for bad in (None, ""):
                with self.subTest(accessor=name, value=repr(bad)):
                    self.assertIn("UNVERIFIED", fn(bad))

    def test_zero_is_a_value_not_a_missing_one(self):
        self.assertNotIn("UNVERIFIED", fmt.money(0))
        self.assertNotIn("UNVERIFIED", fmt.num(0))
        self.assertEqual(fmt.count(0), "0")

    def test_count_is_blank_by_documented_decision(self):
        # Not an oversight: tests/test_site_build.py (PR #25) pins cnt=None as ""
        # because a missing count is an empty KPI tile, whereas a missing quantity
        # is a failed API read. Asserted here so the split is a decision on record
        # rather than something a later formatter refactor silently undoes.
        self.assertEqual(fmt.count(None), "")
        self.assertEqual(fmt.cnt("") if hasattr(fmt, "cnt") else fmt.count(""), "")

    def test_counts_stay_whole_numbers(self):
        self.assertEqual(fmt.count(750), "750")
        self.assertEqual(fmt.count(2000), "2,000")
        # Kalshi's own fixed-point quantities are legitimately fractional
        # (open_interest_fp returned "189529515.91" on 2026-11-20), so a
        # non-integral value must keep its decimals rather than be rounded.
        self.assertEqual(fmt.count(189529515.91), "189,529,515.91")

    def test_no_page_renders_a_raw_none(self):
        # A Python None reaching the HTML would show as "None" in a cell; every
        # accessor is supposed to convert it to the badge first.
        for page in ("index.html", "live.html", "trades.html", "resolutions.html",
                     "suggestions.html", "methodology.html", "review.html"):
            if not os.path.exists(os.path.join(ROOT, page)):
                self.skipTest("generated pages not built yet")
            body = re.sub(r"<script>.*?</script>", "", read(page), flags=re.S)
            text = re.sub(r"<[^>]+>", "", body)
            with self.subTest(page=page):
                for bad in ("None", "undefined", "NaN", "[object Object]"):
                    self.assertNotIn(bad, text, f"{page} rendered {bad!r}")


class TestSettlementWording(unittest.TestCase):
    """Rule 2: the payout is stated for both outcomes."""

    def test_methodology_states_both_sides_get_paid(self):
        page = read("methodology.html")
        blob = re.sub(r"\s+", " ", page)
        self.assertIn("Yes contract holders receive $1.00 per contract", blob)
        self.assertIn("No contract holders receive $1.00 per contract", blob)
        self.assertIn("Only net positions are settled", blob)

    def test_the_one_sided_wording_is_gone(self):
        blob = re.sub(r"\s+", " ", read("methodology.html"))
        self.assertNotIn("YES pays $1.00 per contract, NO pays nothing", blob)


class TestFeeAssumptionIsFlagged(unittest.TestCase):
    """Rule 3: the multiplier assumption stays visible with official sources."""

    def _entry(self):
        for item in flagpage.STANDING:
            if "multiplier" in item["title"]:
                return item
        self.fail("no standing limitation mentions the fee multiplier")

    def test_entry_exists_and_names_both_sources(self):
        item = self._entry()
        body = item["body"]
        self.assertIn("0.07", body)
        sources = list(item["source"])
        self.assertTrue(any("kalshi-fee-schedule.pdf" in u for u in sources), sources)
        self.assertTrue(any("demo.kalshi.co/trade-api/v2/series/KXBTCY" in u for u in sources),
                        sources)
        self.assertIn("fee_multiplier", body)

    def test_it_is_rendered_on_the_flagged_page(self):
        # R-1E3-2: the flagged item describes the *source disagreement* (fee
        # PDF vs GET /series field) rather than the pre-2026-11-21 code path;
        # the title is HTML-escaped on render, so assert the apostrophe-free
        # prefix.
        page = read("review.html")
        self.assertIn("The fee PDF and the demo API disagree about some series", page)
        self.assertIn("trade-api/v2/series/KXBTCY", page)


class TestNegativeMoney(unittest.TestCase):
    """A loss must read as a loss: ``-$125.00``, not ``$-125.00``."""

    def test_sign_sits_outside_the_currency_symbol(self):
        self.assertEqual(fmt.money(-125), "-$125.00")
        self.assertEqual(fmt.money(-0.5, 4), "-$0.5000")
        self.assertEqual(fmt.money(125), "$125.00")
        self.assertEqual(fmt.money(0), "$0.00")

    def test_no_page_shows_the_wrong_form(self):
        for page in ("index.html", "trades.html", "resolutions.html", "live.html"):
            path = os.path.join(ROOT, page)
            if not os.path.exists(path):
                self.skipTest("generated pages not built yet")
            with self.subTest(page=page):
                self.assertNotIn("$-", read(page))


class TestFeeClaimIsScoped(unittest.TestCase):
    """The methodology page must not overstate fee coverage.

    Both engines now read each market's ``fee_multiplier`` (``trading/engine.py``
    since its inception; ``collector/engine.py`` since request R-79CC-1 landed),
    print the basis per row, and fall back to the schedule's default M = 1 only
    when a series lookup is unavailable. A sentence claiming the collector's
    ledger "applies a multiplier of 1 to every series" is a factual claim about
    code that stopped being true, so it is pinned *gone* here, and the accurate
    scoping is pinned present.
    """

    def test_fees_section_names_both_engines(self):
        blob = re.sub(r"\s+", " ", read("methodology.html"))
        i = blob.index("Fees")
        section = blob[i:i + 1600]
        self.assertIn("trading/", section)
        self.assertIn("fee_multiplier", section)
        self.assertIn("GET /series", section)
        self.assertIn("review.html", section)

    def test_the_false_blanket_claim_stays_gone(self):
        blob = re.sub(r"\s+", " ", read("methodology.html"))
        self.assertNotIn("applies a multiplier of 1 to every series", blob)


class TestAgeLabel(unittest.TestCase):
    def test_deterministic_for_a_fixed_reference_time(self):
        ts = 1_795_200_000.0
        a = extras.age_label("2026-11-20T18:40:00Z", ts)
        b = extras.age_label("2026-11-20T18:40:00Z", ts)
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("old"), a)

    def test_unparseable_timestamp_yields_no_label_rather_than_a_guess(self):
        self.assertEqual(extras.age_label(None, None), "")


class TestGeneratorWritesThePublishedPageSet(unittest.TestCase):
    """Every page the sidebar offers must be a page the builder writes, so a new
    nav entry can never ship as a 404 on GitHub Pages."""

    def test_nav_targets_are_build_outputs(self):
        src = read(os.path.join("site_build", "build.py"))
        written = set(re.findall(r'write\("([^"]+\.html)"', src))
        nav_block = src[src.index("def research_nav"):src.index("def page(")]
        for href in re.findall(r'\("([a-z_-]+\.html)"', nav_block):
            self.assertIn(href, written, f"{href} is in the nav but never written")
        for page in ("index.html", "live.html", "review.html", "methodology.html"):
            self.assertIn(page, written)


if __name__ == "__main__":
    unittest.main(verbosity=2)
