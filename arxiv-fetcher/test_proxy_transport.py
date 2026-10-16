"""Proxy routing and official search fallback regression tests."""
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import http_transport as transport
import curated_fetcher as app
from arxiv_web import parse_results, web_query


PAGE = '''<ol><li class="arxiv-result">
<p class="list-title"><a href="https://arxiv.org/abs/2610.12345">arXiv:2610.12345</a></p>
<p class="title">A <span>scientific</span> method</p>
<p class="authors"><a>Alice Smith</a>, <a>Bob Lee</a></p>
<span class="tag">cs.LG</span>
<span class="abstract-full">A complete <span>abstract</span>. <a>△ Less</a></span>
<p><span>Submitted</span> 7 October, 2026; originally announced October 2026.</p>
</li></ol>'''


class TransportTests(unittest.TestCase):
    def tearDown(self):
        transport.configure_network({})

    def test_profile_port_applies_to_all_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile.yaml"
            profile.write_text("mixed-port: 7890\n", encoding="utf-8")
            transport.configure_network({"network": {"require_proxy": True, "mihomo_profile": str(profile)}})
        for session in (transport.SESSION, transport.FALLBACK_SESSION):
            self.assertFalse(session.trust_env)
            self.assertEqual(session.proxies, {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"})
            self.assertIs(session.verify, True)
        self.assertIs(app.legacy.SESSION, transport.SESSION)

    def test_required_proxy_cannot_silently_use_direct(self):
        with self.assertRaises(ValueError):
            transport.configure_network({"network": {"require_proxy": True}})

    def test_html_metadata_preserves_highlights_and_dates(self):
        entry = parse_results(PAGE)[0]
        self.assertEqual(entry["title"], "A scientific method")
        self.assertEqual(entry["summary"], "A complete abstract.")
        self.assertEqual(entry["published"], "2026-10-07T00:00:00Z")
        self.assertEqual(len(entry["authors"]), 2)

    def test_block_page_is_not_empty_results(self):
        with self.assertRaises(ValueError):
            parse_results("<html>Access denied</html>")
        self.assertEqual(parse_results("Sorry, your query returned no results"), [])

    def test_api_throttle_falls_back_once_for_remaining_queries(self):
        response = MagicMock(status_code=429)
        failure = app.requests.HTTPError(response=response)
        config = {"selection": {"crossref_enabled": False}, "interests": [
            {"name": "test", "queries": ['all:"flow matching"', 'all:agent']}]}
        errors = []
        with patch.object(app, "get", side_effect=failure) as request, \
             patch.object(app, "search_arxiv_web", return_value=parse_results(PAGE)) as web, \
             patch.object(app.time, "sleep"):
            papers = app.discover(config, 14, 12, errors, "2026-10-05", "2026-10-11")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(web.call_count, 2)
        self.assertEqual(len(papers), 1)
        self.assertEqual(errors, [])

    def test_web_query_keeps_boolean_terms(self):
        self.assertEqual(web_query('(all:agent OR all:agentic) AND (cat:cs.AI OR cat:cs.LG)'), [('all', 'agent'), ('all', 'agentic')])

    def test_cached_discovery_does_not_query_sources_or_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / "cache.json"
            paper = {"title": "Candidate", "interests": ["test"], "link": "https://arxiv.org/abs/2610.12345"}
            cache.write_text(json.dumps({"papers": [paper], "errors": [], "start_date": "2026-10-05", "end_date": "2026-10-11"}), encoding="utf-8")
            config = {"selection": {}, "interests": [{}] * 7,
                      "obsidian": {"vault_path": str(root), "target_folder": "Papers"}}
            with patch.object(app, "ROOT", root), patch.object(app.legacy, "load_config", return_value=config), \
                 patch.object(app, "discover") as discover, patch.object(app, "ask") as ask, \
                 patch("sys.argv", ["test", "--from-discovery", str(cache), "--discover-only"]):
                self.assertEqual(app.run(), 0)
            discover.assert_not_called()
            ask.assert_not_called()
            self.assertEqual(len(list((root / "logs").glob("discovery_*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
