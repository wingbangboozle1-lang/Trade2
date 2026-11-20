import unittest

from site_build.build import build_overview, build_performance_section, build_topic, cnt, money, num
from site_build.flagpage import detect_data_issues, render as render_flagpage


class CountFormatterTests(unittest.TestCase):
    def test_integral_counts_have_no_fractional_suffix(self):
        self.assertEqual(cnt(750), "750")
        self.assertEqual(cnt(1.0), "1")
        self.assertEqual(cnt("2000.00"), "2,000")
        self.assertEqual(cnt("9007199254740993"), "9,007,199,254,740,993")

    def test_non_integral_values_keep_existing_precision(self):
        self.assertEqual(cnt("12.5"), "12.50")
        self.assertEqual(cnt("1.0000000001"), "1.00")

    def test_missing_count_stays_blank(self):
        self.assertEqual(cnt(None), "")
        self.assertEqual(cnt(""), "")

    def test_fractional_quantity_and_money_formatting_is_unchanged(self):
        self.assertEqual(num("12.5"), "12.50")
        self.assertEqual(money("1.5"), "$1.50")


class CountRenderingTests(unittest.TestCase):
    def test_overview_formats_count_kpis_as_counts(self):
        html = build_overview(
            {
                "generated_at": "2026-11-20T18:41:08Z",
                "observation_count": 1250,
                "alerts": [{}, {}],
                "resolutions_count": 2000,
                "events": [],
                "portfolio": {"open_positions": 1.0},
                "exchange": {"trading_active": True},
            }
        )
        self.assertIn("<strong>1,250</strong>", html)
        self.assertIn("<strong>2</strong>", html)
        self.assertIn("<strong>1</strong>", html)
        self.assertIn("<strong>2,000</strong>", html)
        self.assertNotIn("<strong>1,250.00</strong>", html)

    def test_topic_kpis_and_footer_format_counts_as_counts(self):
        html = build_topic(
            "elections",
            {
                "generated_at": "2026-11-20T18:41:08Z",
                "topics": {
                    "elections": {
                        "label": "Elections",
                        "series_count": 1500,
                        "event_count": 23,
                        "tracked_market_count": 12,
                        "market_count": 1250,
                    }
                },
                "events": [],
                "resolutions": {"elections": []},
            },
        )
        self.assertIn("<strong>1,500</strong>", html)
        self.assertIn("<strong>23</strong>", html)
        self.assertIn("<strong>12</strong>", html)
        self.assertIn("<strong>0</strong>", html)
        self.assertIn("1,250 markets matched", html)

    def test_performance_trade_win_loss_counts_are_integers(self):
        html = build_performance_section(
            {
                "portfolio": {
                    "overall": {"trades": 1.0, "wins": 1.0, "losses": 0.0},
                    "by_strategy": {
                        "momentum": {
                            "trades": 1.0,
                            "wins": 1.0,
                            "losses": 0.0,
                        }
                    },
                    "by_topic": {"elections": {"trades": 1.0}},
                    "settled_positions": [],
                },
                "strategies": {
                    "momentum": {"label": "Momentum", "description": "Test"}
                },
            }
        )
        self.assertIn("<small>1 settled</small>", html)
        self.assertIn("<small>1W / 0L</small>", html)
        self.assertIn("<td>1</td><td>1</td>", html)
        self.assertIn("<td>0</td>", html)
        self.assertNotIn("<td>1.00</td>", html)


class CultureSourceTests(unittest.TestCase):
    def setUp(self):
        self.live = {
            "generated_at": "2026-11-20T18:41:08Z",
            "events": [],
            "topics": {
                "culture": {
                    "label": "Culture",
                    "series_count": 789,
                    "event_count": 23,
                    "market_count": 23,
                    "source_url": "https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture",
                    "notes": "Culture and Entertainment series are grouped into this dashboard topic.",
                    "series": [],
                }
            },
            "resolutions": {"culture": []},
        }

    def test_topic_page_links_both_categories_for_combined_count(self):
        html = build_topic("culture", self.live)
        self.assertIn(
            'href="https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture"',
            html,
        )
        self.assertIn(
            'href="https://external-api.demo.kalshi.co/trade-api/v2/series?category=Entertainment"',
            html,
        )
        self.assertIn("Culture series API", html)
        self.assertIn("Entertainment series API", html)

    def test_flag_describes_combined_scope_and_links_both_official_queries(self):
        issue = next(
            issue for issue in detect_data_issues(self.live)
            if issue["topic"] == "culture"
        )
        self.assertEqual(issue["kind"], "Culture topic combines categories")
        self.assertIn("not the result of the Culture-only query", issue["detail"])
        self.assertNotIn("789 series", issue["detail"])
        self.assertEqual(
            [source["url"] for source in issue["sources"]],
            [
                "https://external-api.demo.kalshi.co/trade-api/v2/series?category=Culture",
                "https://external-api.demo.kalshi.co/trade-api/v2/series?category=Entertainment",
            ],
        )
        page = render_flagpage(self.live)
        self.assertIn("Culture series API", page)
        self.assertIn("Entertainment series API", page)
        self.assertNotIn("returns 789 series", page)


class AlertReviewTests(unittest.TestCase):
    def test_repeated_midpoint_alerts_are_flagged_with_official_book_links(self):
        live = {
            "generated_at": "2026-11-20T18:41:08Z",
            "events": [],
            "alerts": [
                {"ticker": "KXPRESNOMD-28-HBID", "topic": "elections"},
                {"ticker": "KXPRESNOMD-28-HBID", "topic": "elections"},
            ],
        }
        issue = next(
            issue for issue in detect_data_issues(live)
            if issue["kind"].startswith("Repeated midpoint alerts")
        )
        self.assertIn("2 alert rows across 1 distinct ticker", issue["detail"])
        self.assertIn("not executed fills", issue["detail"])
        self.assertIn("2 stored row(s) lack a recognized quote reference basis", issue["detail"])
        self.assertIn(
            "https://external-api.demo.kalshi.co/trade-api/v2/markets/"
            "KXPRESNOMD-28-HBID/orderbook",
            [source["url"] for source in issue["sources"]],
        )
        page = render_flagpage(live)
        self.assertIn("Repeated midpoint alerts", page)
        self.assertIn("Orderbook format and bid/ask explanation", page)
        self.assertIn("Swing alerts are detections, not executed fills", page)
        self.assertNotIn("29 raw alert rows", page)
        self.assertNotIn("Until the engine-side fix lands", page)


if __name__ == "__main__":
    unittest.main()
