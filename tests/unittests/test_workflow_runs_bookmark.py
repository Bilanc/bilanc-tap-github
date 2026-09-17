"""The workflow_runs bookmark is one value per repo, shared by every workflow.

Regression test for the bug where get_all_workflows re-read the bookmark for
each workflow and advanced it after every record, so only the first workflow in
a repo got a full pull and every later one stopped on its first page.
"""
import unittest
from unittest import mock

import tap_github


class MockResponse:
    def __init__(self, payload):
        self._payload = payload
        self.links = {}

    def json(self):
        return self._payload


SCHEMAS = {"workflows": {"type": "object"}, "workflow_runs": {"type": "object"}}
MDATA = {"workflows": {}, "workflow_runs": {}}


@mock.patch("tap_github.write_record")
@mock.patch("tap_github.singer.Transformer")
@mock.patch("tap_github.authed_get_all_pages")
class TestWorkflowRunsBookmark(unittest.TestCase):
    def test_every_workflow_uses_the_same_cutoff(
        self, mocked_pages, mocked_transformer, mocked_write_record
    ):
        mocked_pages.return_value = iter(
            [MockResponse({"workflows": [{"id": 1}, {"id": 2}, {"id": 3}]})]
        )
        mocked_transformer.return_value.__enter__.return_value.transform.return_value = {}
        state = {
            "bookmarks": {
                "org/repo": {"workflow_runs": {"since": "2026-09-01T00:00:00Z"}}
            }
        }
        seen_cutoffs = []

        def fake_runs(workflow_id, schemas, repo_path, st, mdata, start_date, bookmark_time=None):
            seen_cutoffs.append(bookmark_time)
            yield {"id": workflow_id * 10}

        with mock.patch("tap_github.get_workflow_runs_for_workflow", side_effect=fake_runs):
            with mock.patch("tap_github.singer.write_bookmark") as mocked_bookmark:
                tap_github.get_all_workflows(SCHEMAS, "org/repo", state, MDATA, None)

        expected = tap_github.singer.utils.strptime_to_utc("2026-09-01T00:00:00Z")
        self.assertEqual(seen_cutoffs, [expected, expected, expected])
        # Runs from all three workflows were written, not just the first.
        run_writes = [c for c in mocked_write_record.call_args_list if c.args[0] == "workflow_runs"]
        self.assertEqual(len(run_writes), 3)
        # The bookmark moves exactly once, after every workflow has been walked.
        self.assertEqual(mocked_bookmark.call_count, 1)
        self.assertEqual(mocked_bookmark.call_args.args[2], "workflow_runs")

    def test_no_bookmark_write_when_runs_not_selected(
        self, mocked_pages, mocked_transformer, mocked_write_record
    ):
        mocked_pages.return_value = iter([MockResponse({"workflows": [{"id": 1}]})])
        mocked_transformer.return_value.__enter__.return_value.transform.return_value = {}
        with mock.patch("tap_github.singer.write_bookmark") as mocked_bookmark:
            tap_github.get_all_workflows({"workflows": {}}, "org/repo", {}, {"workflows": {}}, None)
        mocked_bookmark.assert_not_called()

    def test_runs_older_than_cutoff_stop_the_page_walk(
        self, mocked_pages, mocked_transformer, mocked_write_record
    ):
        cutoff = tap_github.singer.utils.strptime_to_utc("2026-09-10T00:00:00Z")
        mocked_pages.return_value = iter(
            [
                MockResponse(
                    {
                        "workflow_runs": [
                            {"id": 1, "updated_at": "2026-09-12T00:00:00Z", "url": "u"},
                            {"id": 2, "updated_at": "2026-09-11T00:00:00Z", "url": "u"},
                            {"id": 3, "updated_at": "2026-09-01T00:00:00Z", "url": "u"},
                        ]
                    }
                )
            ]
        )
        mocked_transformer.return_value.__enter__.return_value.transform.side_effect = lambda run, *a, **k: run
        with mock.patch("tap_github.authed_get") as mocked_get:
            mocked_get.return_value.json.return_value = {}
            runs = list(
                tap_github.get_workflow_runs_for_workflow(
                    7, {"workflow_runs": {"type": "object"}}, "org/repo", {}, {"workflow_runs": {}}, None,
                    bookmark_time=cutoff,
                )
            )
        self.assertEqual([r["id"] for r in runs], [1, 2])


if __name__ == "__main__":
    unittest.main()
