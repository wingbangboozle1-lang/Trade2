"""K1 — the all-events chat carries the published candlestick-close moves.

What this pins, in the order the defect appeared:

1. the root snapshot's midpoint detector refuses an empty book (correct), so on
   a thin demo book it legitimately fires nothing; the landing page then said
   "Swings ≥ $0.10: 0" while the ``docs/`` collector published 6 sourced moves of
   ≥ $0.10 on the same markets in the same half hour. Two views of one exchange
   disagreeing is worse for a trader than either alone.
2. the merge adds those moves to the all-events feed only, labelled with the
   basis they were measured on — the model / high-ROI chat keeps its
   executability gate, because a historical close is not a price anyone could
   have traded.
3. nothing is invented: a row is dropped, and counted, when it is below the
   threshold, older than the freshness window, not a market this site tracks, or
   malformed.

Sources: https://docs.kalshi.com/api-reference/market/get-market-candlesticks
         https://docs.kalshi.com/getting_started/orderbook_responses

Run: python3 -m unittest tests.test_swing_feed_d6a0282d -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from site_build import build, swingfeed

NOW = 1795242600.0          # 2026-11-21T06:30:00Z, the real run time of the fixture
CANDLE_URL = ("https://external-api.demo.kalshi.co/trade-api/v2/series/KXPGATOUR/"
              "markets/KXPGATOUR-THRC26-MTHO/candlesticks?start_ts=1795238665"
              "&end_ts=1795242265&period_interval=1")
MARKET_URL = ("https://external-api.demo.kalshi.co/trade-api/v2/markets/"
              "KXPGATOUR-THRC26-MTHO")


def docs_alert(**over):
    """One row exactly as ``collector.runner.detect_alerts`` writes it."""
    row = {
        "ticker": "KXPGATOUR-THRC26-MTHO",
        "topic": "golf",
        "title": "The RSM Classic: Michael Thorbjornsen wins",
        "window": "seconds",
        "from": 0.17,
        "to": 0.39,
        "delta": 0.22,
        "direction": "up",
        "t": 1795241520.0,
        "t_iso": "2026-11-21T06:12:00+00:00",
        "threshold": 0.1,
        "headlines": [{"title": "Highlights | Round 2 | The RSM Classic | 2026 - PGA Tour",
                       "url": "https://news.google.com/rss/articles/abc?oc=5",
                       "source": "PGA Tour",
                       "published": "2026-11-21T02:42:58+00:00",
                       "status": "verified-fetch"}],
        "news_status": "ok",
        "source_url": MARKET_URL,
        "candle_source_url": CANDLE_URL,
        "docs_url": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
        "flags": [],
    }
    row.update(over)
    return row


def payload(alerts, generated_at="2026-11-21T06:24:58.987284+00:00"):
    return {"generated_at": generated_at, "threshold": 0.1,
            "source_docs": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
            "alerts": alerts}


def live_alert(**over):
    row = {"id": "KXPGATOUR-THRC26-MTHO:1", "ts": 1795241520.0,
           "iso": "2026-11-21T06:12:00Z", "ticker": "KXPGATOUR-THRC26-MTHO",
           "event_ticker": "KXPGATOUR-THRC26", "series_ticker": "KXPGATOUR",
           "topic": "golf", "title": "Michael Thorbjornsen wins",
           "previous": 0.17, "current": 0.39, "abs_delta": 0.22,
           "direction": "up", "yes_bid": 0.38, "yes_ask": 0.40,
           "spread": 0.02, "quality": "executable",
           "reference_basis": "quote mid → quote mid", "news": [],
           "market_url": "https://kalshi.com/markets/KXPGATOUR/KXPGATOUR-THRC26-MTHO"}
    row.update(over)
    return row


class Projection(unittest.TestCase):
    def test_a_qualifying_move_becomes_a_chat_row(self):
        rows, stats = swingfeed.candle_alerts(payload([docs_alert()]), now_ts=NOW)
        self.assertEqual(stats["kept"], 1)
        row = rows[0]
        self.assertEqual(row["abs_delta"], 0.22)
        self.assertEqual(row["previous"], 0.17)
        self.assertEqual(row["current"], 0.39)
        self.assertEqual(row["direction"], "up")
        self.assertEqual(row["quality"], swingfeed.CANDLE_QUALITY)
        self.assertEqual(row["iso"], "2026-11-21T06:12:00+00:00")
        self.assertEqual(row["candle_source_url"], CANDLE_URL)
        self.assertEqual(row["source_url"], MARKET_URL)
        self.assertEqual(len(row["news"]), 1)
        self.assertIn("candlestick", row["quality_reason"])

    def test_below_threshold_is_counted_not_shown(self):
        rows, stats = swingfeed.candle_alerts(
            payload([docs_alert(**{"delta": 0.09, "from": 0.30, "to": 0.39})]),
            now_ts=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(stats["below-threshold"], 1)

    def test_stale_move_is_dropped_as_stale(self):
        old = docs_alert(t=NOW - 25 * 3600.0, t_iso="2026-11-20T05:30:00+00:00")
        rows, stats = swingfeed.candle_alerts(payload([old]), now_ts=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(stats["too-old"], 1)

    def test_a_market_this_site_does_not_track_is_not_smuggled_in(self):
        rows, stats = swingfeed.candle_alerts(
            payload([docs_alert()]), now_ts=NOW, tickers={"KXOTHER-1"})
        self.assertEqual(rows, [])
        self.assertEqual(stats["unknown-ticker"], 1)

    def test_malformed_rows_are_counted_not_repaired(self):
        rows, stats = swingfeed.candle_alerts(payload([
            {"ticker": "X"},                     # no numbers at all
            {"ticker": "Y", "delta": 0.5, "from": 0.1, "to": 0.6},  # no timestamp
            "not-a-row",
        ]), now_ts=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(stats["malformed"], 3)

    def test_headline_without_a_url_is_not_shown_as_a_link(self):
        row_only = docs_alert(headlines=[{"title": "No link", "url": ""}])
        rows, _ = swingfeed.candle_alerts(payload([row_only]), now_ts=NOW)
        self.assertEqual(rows[0]["news"], [])


class Attachment(unittest.TestCase):
    def test_attach_labels_the_feed_and_records_its_age(self):
        live = {"events": [{"ticker": "KXPGATOUR-THRC26-MTHO"}], "alerts": []}
        stats = swingfeed.attach(live, payload([docs_alert()]), now_ts=NOW)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(len(live["candle_alerts"]), 1)
        self.assertEqual(live["candle_feed_stats"]["source_generated_at"],
                         "2026-11-21T06:24:58.987284+00:00")
        self.assertEqual(live["candle_feed_stats"]["source_path"], "docs/data/alerts.json")

    def test_the_same_step_already_in_the_live_feed_is_not_duplicated(self):
        live = {"events": [{"ticker": "KXPGATOUR-THRC26-MTHO"}],
                "alerts": [live_alert()]}
        stats = swingfeed.attach(live, payload([docs_alert()]), now_ts=NOW)
        self.assertEqual(live["candle_alerts"], [])
        self.assertEqual(stats["duplicates_dropped"], 1)

    def test_a_different_measurement_of_the_same_market_is_still_shown(self):
        """Opposite direction and a different size: a distinct row, labelled."""
        live = {"events": [{"ticker": "KXPGATOUR-THRC26-MTHO"}],
                "alerts": [live_alert(direction="down", abs_delta=0.22)]}
        stats = swingfeed.attach(live, payload([docs_alert()]), now_ts=NOW)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(live["candle_alerts"][0]["direction"], "up")

    def test_a_snapshot_with_no_docs_feed_is_left_untouched(self):
        live = {"events": [], "alerts": [live_alert()]}
        stats = swingfeed.attach(live, {}, now_ts=NOW)
        self.assertEqual(live["candle_alerts"], [])
        self.assertEqual(stats["read"], 0)
        self.assertEqual(len(build.all_feed(live)), 1)


class Rendering(unittest.TestCase):
    def _live(self, **over):
        live = {
            "generated_at": "2026-11-21T06:30:00Z",
            "observation_count": 750,
            "resolutions_count": 328,
            "exchange": {"trading_active": True},
            "events": [{"ticker": "KXPGATOUR-THRC26-MTHO",
                        "event_ticker": "KXPGATOUR-THRC26",
                        "series_ticker": "KXPGATOUR", "topic": "golf",
                        "title": "Michael Thorbjornsen wins",
                        "open_interest_notional": 123.0,
                        "open_interest_contracts": 123.0,
                        "volume_contracts": 456.0,
                        "yes_bid": None, "yes_ask": None,
                        "quote_bid": 0.0, "quote_ask": 1.0,
                        "book_state": "empty", "last_price": 0.39}],
            "alerts": [],
            "signals": [],
            "suppressed_alerts": [],
            "candle_alerts": [],
            "candle_feed_stats": {},
        }
        live.update(over)
        return live

    def test_chat_row_links_the_candlestick_series_it_came_from(self):
        rows, _ = swingfeed.candle_alerts(payload([docs_alert()]), now_ts=NOW)
        html = build.alert_chat_row(rows[0])
        self.assertIn("/candlesticks?start_ts=1795238665", html)
        self.assertIn("candle series ↗", html)
        self.assertIn(MARKET_URL, html)
        self.assertIn("candlestick close · not a live mid", html)
        # An event-page link needs an event ticker the API returned; this feed
        # has none, so the row must not invent one.
        self.assertNotIn("Event page", html)

    def test_live_row_still_gets_its_event_page_and_api_link(self):
        html = build.alert_chat_row(live_alert())
        self.assertIn("Event page ↗", html)
        self.assertIn("/markets/KXPGATOUR-THRC26-MTHO", html)
        self.assertIn(">executable</span>", html)

    def test_overview_shows_the_merged_feed_and_says_what_it_is(self):
        live = self._live()
        swingfeed.attach(live, payload([docs_alert()]), now_ts=NOW)
        html = build.build_overview(live)
        self.assertIn("row(s) measured on Kalshi's published candlestick closes", html)
        self.assertIn("2026-11-21 06:24Z collector run", html)
        self.assertIn("<strong>1</strong>", html)          # the KPI counts the feed
        self.assertIn("0 live mid ·", html)
        self.assertNotIn("No ≥ $0.10 swing on a two-sided book in the current "
                         "buffer, and no candlestick-close move in the window",
                         html)

    def test_the_model_chat_never_shows_a_candle_close_row(self):
        """The gate is the whole point: a published close says nothing about a
        price that was tradeable, so it cannot carry a net-ROI claim.

        The same ticker is deliberately made a model pick, so a regression that
        feeds the merged list to the model chat cannot hide behind a shortlist
        that happens to be empty."""
        # A live midpoint move on one market, and a *different* published close
        # move on another that the model also likes. The candle row survives
        # dedupe, is a model pick, and must still not enter the model chat.
        other = live_alert(ticker="KXETHD-26NOV2117-T1459.99",
                           event_ticker="KXETHD-26NOV2117", series_ticker="KXETHD",
                           topic="crypto", title="Ethereum at 5pm EST",
                           direction="down", abs_delta=0.15, previous=0.90,
                           current=0.75)
        live = self._live(alerts=[other])
        swingfeed.attach(live, payload([docs_alert()]), now_ts=NOW)
        live["events"].append({"ticker": "KXETHD-26NOV2117-T1459.99",
                               "topic": "crypto", "title": "Ethereum at 5pm EST"})
        self.assertEqual(len(live["candle_alerts"]), 1,
                         "fixture must keep a candle row that survived dedupe")
        live["signals"] = [{"ticker": "KXETHD-26NOV2117-T1459.99", "net_roi": 0.4,
                            "score": 0.4, "side": "yes", "topic": "crypto",
                            "title": "Ethereum at 5pm EST",
                            "executable_price": 0.75,
                            "market_url": "https://kalshi.com/markets/KXETHD/"
                                          "KXETHD-26NOV2117-T1459.99", "ts": NOW}]
        html = build.build_overview(live)
        model = html.split('model-chat')[1]
        self.assertIn(">executable</span>", model,
                      "the live midpoint row for that ticker belongs there")
        self.assertNotIn("candlestick close", model)
        self.assertEqual(model.count('<div class="chat-row">'), 1,
                         "exactly one model row: the candle-close row for the "
                         "same ticker must not join it")
        # …and it *is* in the all-events chat, so the row is not simply missing.
        all_chat = html.split('model-chat')[0]
        self.assertEqual(all_chat.count('<div class="chat-row">'), 2)


    def test_empty_buffer_without_a_docs_feed_still_says_so(self):
        html = build.build_overview(self._live())
        self.assertIn("and no candlestick-close move in the window", html)

    def test_last_and_empty_book_columns_reach_the_tables(self):
        html = build.build_overview(self._live())
        self.assertIn("$0.3900", html)   # the Last column, from last_price_dollars
        self.assertIn("empty book · nothing resting", html)
        self.assertIn("<th>Last</th>", html)

    def test_desk_page_carries_the_same_rows_as_the_json_it_reloads(self):
        html = build.build_live(self._live(
            **{"candle_alerts": swingfeed.candle_alerts(payload([docs_alert()]),
                                                        now_ts=NOW)[0]}))
        self.assertIn("candlestick close", html)
        self.assertIn("row(s) measured on Kalshi's published candlestick closes",
                      html)



class Wiring(unittest.TestCase):
    """The merge has to be *called*, not merely available.

    Follows this repo's existing source-pattern convention
    (``tests/test_exchange_status_a3137708.py``): a mutation that deletes the
    call from ``main()`` leaves every renderer test above green, because each
    one attaches the feed itself.
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "site_build", "build.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        cls.main_body = src.split("def main(", 1)[1].split("\ndef ", 1)[0]
        cls.src = src

    def test_main_attaches_the_feed_before_any_page_is_built(self):
        self.assertIn("swingfeed.attach(live, load_json(DOCS_ALERTS_PATH",
                      self.main_body)
        self.assertLess(self.main_body.index("swingfeed.attach"),
                        self.main_body.index('write("index.html"'),
                        "the feed must be attached before the pages render")

    def test_the_all_events_chats_read_the_merged_feed(self):
        # Overview and desk both render from all_feed(); the model loops both
        # iterate `grouped`/`alerts`, never `feed`.
        self.assertEqual(self.src.count("all_feed(live)"), 3,
                         "one definition + the two chat call sites")
        self.assertIn("for a in grouped:\n        pick = shortlist.get", self.src)

    def test_the_candle_feed_is_published_for_the_browser_path(self):
        """assets/live.json is what desk.js re-fetches; the rows have to be in
        it or the live feed and the pre-rendered feed disagree."""
        self.assertIn('write("assets/live.json", json.dumps(live, default=str, indent=1))',
                      self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
