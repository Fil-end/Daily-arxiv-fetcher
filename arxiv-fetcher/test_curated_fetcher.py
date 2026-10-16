"""Regression tests for evidence gates and daily delivery limits."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import curated_fetcher as app


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.text = "A fair baseline comparison supports the central result. An independent experiment constrains the proposed mechanism."
        self.review = {"decision": "recommend", "full_text_sufficient": True, "score": 90,
                       "reason": "reason", "advance": "advance", "prior_work_comparison": "baseline",
                       "limitations": "limits", "author_claim_vs_evidence": "claims",
                       "evidence": [{"quote": s + "."} for s in self.text.rstrip(".").split(". ")]}

    def test_fabricated_evidence_rejected(self):
        self.assertTrue(app.evidence_valid(self.review, self.text, 85))
        self.review["evidence"][0]["quote"] = "An invented numerical improvement of ninety percent."
        self.assertFalse(app.evidence_valid(self.review, self.text, 85))

    def test_insufficient_text_or_low_score_rejected(self):
        for key, value in [("score", 84), ("full_text_sufficient", False), ("decision", "reject")]:
            review = dict(self.review, **{key: value})
            self.assertFalse(app.evidence_valid(review, self.text, 85))

    def test_version_deduplication(self):
        self.assertEqual(app.identity({"arxiv_id": "2609.12345v1"}), app.identity({"arxiv_id": "2609.12345v3"}))

    def test_critic_veto(self):
        config = {"interests": [], "selection": {"min_score": 85}}
        with patch.object(app, "ask", side_effect=[self.review, {"uphold": False, "fatal_concerns": ["unfair baseline"]}]):
            review, _ = app.review_paper(config, {}, {"text": self.text})
        self.assertIsNone(review)

    def run_fixture(self, dry=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {"selection": {"daily_limit": 5}, "interests": [{}] * 7,
                      "obsidian": {"vault_path": str(root), "target_folder": "Papers"}}
            papers = [{"arxiv_id": f"2609.{n:05d}v1", "title": f"Paper {n}", "authors": ["Author"],
                       "published": "2026-09-10", "interest": "area", "interests": ["area"], "link": "https://example.org", "summary": ""} for n in range(8)]
            review = dict(self.review, critique={"reason": "checked"})
            source = {"text": self.text, "url": "https://example.org", "sha256": "test"}
            with patch.object(app, "ROOT", root), patch.object(app.legacy, "load_config", return_value=config), \
                 patch.object(app, "discover", return_value=papers), patch.object(app, "shortlist", side_effect=lambda c, p: p), \
                 patch.object(app, "fulltext", return_value=source), patch.object(app, "review_paper", return_value=(review, review)), \
                 patch("sys.argv", ["test"] + (["--dry-run"] if dry else [])):
                self.assertEqual(app.main(), 0)
                if dry:
                    self.assertEqual(list(root.iterdir()), [])
                else:
                    state = json.loads((root / "recommendations.json").read_text(encoding="utf-8"))
                    self.assertEqual(len(state), 5)
                    self.assertEqual(app.main(), 0)
                    self.assertEqual(len([p for p in (root / "Papers").rglob("*.md") if app.RETAINED_FOLDER not in p.parts]), 6)

    def test_daily_cap_across_reruns(self):
        self.run_fixture()

    def test_dry_run_has_no_writes(self):
        self.run_fixture(dry=True)

    def test_existing_orphan_notes_count_toward_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "Papers" / datetime.now().strftime("%Y-%m-%d") / "area"
            target.mkdir(parents=True)
            for n in range(5):
                (target / f"note-{n}.md").write_text("saved before ledger update", encoding="utf-8")
            config = {"selection": {"daily_limit": 5}, "interests": [{}] * 7,
                      "obsidian": {"vault_path": str(root), "target_folder": "Papers"}}
            with patch.object(app, "ROOT", root), patch.object(app.legacy, "load_config", return_value=config), \
                 patch.object(app, "discover") as discover, patch("sys.argv", ["test"]):
                self.assertEqual(app.main(), 0)
                discover.assert_not_called()

    def test_model_failure_does_not_deliver(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {"selection": {"daily_limit": 5}, "interests": [{}] * 7,
                      "obsidian": {"vault_path": str(root), "target_folder": "Papers"}}
            paper = {"arxiv_id": "2609.99999v1", "title": "Candidate"}
            with patch.object(app, "ROOT", root), patch.object(app.legacy, "load_config", return_value=config), \
                 patch.object(app, "discover", return_value=[paper]), \
                 patch.object(app, "shortlist", side_effect=ValueError("Invalid model output")), \
                 patch("sys.argv", ["test"]):
                self.assertEqual(app.main(), 1)
                self.assertFalse((root / "recommendations.json").exists())
                caches = list((root / "logs").glob("discovery_*.json"))
                self.assertEqual(json.loads(caches[0].read_text(encoding="utf-8"))["papers"], [paper])
                self.assertTrue(caches[0].with_suffix(".md").exists())
                reports = list((root / "logs").glob("review_*.json"))
                self.assertTrue(json.loads(reports[0].read_text(encoding="utf-8"))["errors"])

    def test_responses_stream_requires_completion(self):
        config = {"llm": {"enabled": True, "provider": "openai-responses", "api_base": "https://example.org", "model": "test"}}
        response = MagicMock()
        event = {"type": "response.completed", "response": {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}}
        response.iter_lines.return_value = [b"data: " + json.dumps(event).encode()]
        with patch.object(app, "resolve_key", return_value="fixture"), patch.object(app.SESSION, "post", return_value=response):
            self.assertEqual(app.ask_once(config, "test", {}), {"ok": True})
            text_done = {"type": "response.output_text.done", "output_index": 1, "content_index": 0, "text": '{"ok":true}'}
            event["response"]["output"] = []
            response.iter_lines.return_value = [b"data: " + json.dumps(e).encode() for e in [text_done, event]]
            self.assertEqual(app.ask_once(config, "test", {}), {"ok": True})
            response.iter_lines.return_value = [b"data: [DONE]"]
            with self.assertRaises(ValueError):
                app.ask_once(config, "test", {})
        self.assertTrue(response.close.called)

    def test_transient_overload_retries(self):
        with patch.object(app, "ask_once", side_effect=[app.RetryableModelError(), {"ok": True}]) as request, \
             patch.object(app.time, "sleep"):
            self.assertEqual(app.ask({}, "test", {}), {"ok": True})
            self.assertEqual(request.call_count, 2)

    def test_source_timeout_retries(self):
        response = MagicMock(status_code=200)
        with patch.object(app.SESSION, "get", side_effect=[app.requests.ReadTimeout(), response]) as request, \
             patch.object(app.time, "sleep") as sleep:
            self.assertIs(app.get("https://example.org"), response)
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once_with(15)

    def test_rate_limit_honors_retry_after(self):
        limited = MagicMock(status_code=429, headers={"Retry-After": "90"})
        limited.raise_for_status.side_effect = app.requests.HTTPError(response=limited)
        success = MagicMock(status_code=200)
        with patch.object(app.SESSION, "get", side_effect=[limited, success]), \
             patch.object(app.time, "sleep") as sleep:
            self.assertIs(app.get("https://example.org"), success)
            sleep.assert_called_once_with(90)
            limited.close.assert_called_once()

    def test_ssl_failure_preserves_proxy_in_alternate_pool(self):
        response = MagicMock(status_code=200)
        with patch.object(app.SESSION, "get", side_effect=app.requests.exceptions.SSLError("TLS failed")), \
             patch.object(app.FALLBACK_SESSION, "get", return_value=response) as direct, \
             patch.object(app.time, "sleep"):
            self.assertIs(app.get(app.legacy.ARXIV_API, params={"max_results": 1}), response)
            self.assertNotIn("verify", direct.call_args.kwargs)
            self.assertEqual(direct.call_args.kwargs["params"], {"max_results": 1})

    def test_connection_failure_switches_official_host(self):
        response = MagicMock(status_code=200)
        with patch.object(app.SESSION, "get", side_effect=[app.requests.ConnectionError(), response]) as request, \
             patch.object(app.FALLBACK_SESSION, "get", side_effect=app.requests.ConnectionError()), \
             patch.object(app.time, "sleep"):
            self.assertIs(app.get("https://export.arxiv.org/api/query?start=0"), response)
            self.assertEqual(request.call_args.args[0], "https://arxiv.org/api/query?start=0")

    def test_failed_routes_are_bounded_and_preserve_cause(self):
        failure = app.requests.exceptions.SSLError("TLS failed")
        with patch.object(app.SESSION, "get", side_effect=failure) as request, \
             patch.object(app.FALLBACK_SESSION, "get", side_effect=failure) as direct, \
             patch.object(app.time, "sleep") as sleep:
            with self.assertRaises(app.requests.ConnectionError) as raised:
                app.get(app.legacy.ARXIV_API)
            self.assertEqual(request.call_count + direct.call_count, 5)
            self.assertEqual(sum(call.args[0] >= 15 for call in sleep.call_args_list), 4)
            self.assertIs(raised.exception.__cause__, failure)

    def test_alternate_host_does_not_rewrite_other_sources(self):
        for url in ("https://api.crossref.org/works", "https://arxiv.org.evil.test/api/query"):
            self.assertEqual(app.alternate_arxiv_url(url), url)

    def test_permanent_http_failure_not_retried(self):
        response = MagicMock(status_code=403)
        response.raise_for_status.side_effect = app.requests.HTTPError(response=response)
        with patch.object(app.SESSION, "get", return_value=response) as request:
            with self.assertRaises(app.requests.HTTPError):
                app.get("https://example.org")
            request.assert_called_once()

    def test_credential_file_is_parsed_without_execution(self):
        from llm_credentials import resolve_key
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "fixture.ps1"
            source.write_text("$env:OPENAI_API_KEY = 'fixture-only'\nthrow 'must not execute'", encoding="utf-8")
            self.assertEqual(resolve_key({"api_key_file": str(source)}), "fixture-only")

    def test_retention_strict_threshold_and_veto(self):
        with tempfile.TemporaryDirectory() as folder:
            paper = {"title": "Candidate", "arxiv_id": "2609.12345v1", "link": "https://example.org"}
            for score in (75, 74, True, "87", float("nan")):
                self.assertIsNone(app.save_candidate(Path(folder), {"paper": paper, "assessment": {"score": score}}))
            record = {"paper": paper, "assessment": {"review": dict(self.review, score=76),
                      "critique": {"uphold": False, "reason": "unfair baseline", "fatal_concerns": []}}}
            note = app.save_candidate(Path(folder), record)
            self.assertIn("unfair baseline", note.read_text(encoding="utf-8"))
            self.assertIn("复核未通过", note.read_text(encoding="utf-8"))
            self.assertEqual(app.save_candidate(Path(folder), record), note)
            self.assertEqual(len(list(note.parent.glob("*.json"))), 1)

    def test_initial_retained_before_critic_failure(self):
        captured = []
        with patch.object(app, "ask", side_effect=[self.review, RuntimeError("service down")]):
            with self.assertRaises(RuntimeError):
                app.review_paper({"interests": [], "selection": {}}, {}, {"text": self.text}, on_initial=captured.append)
        self.assertEqual(captured[0]["score"], 90)


if __name__ == "__main__":
    unittest.main()
