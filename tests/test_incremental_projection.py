"""Page boundaries must not change the retained donor grouping semantics."""

from collections import defaultdict
import unittest

from test_hermes_adapter import hermes_adapter, row


class IncrementalProjectionTests(unittest.TestCase):
    def test_group_boundary_and_persistent_occurrences_match_full_projection(self):
        rows = [row(1, "user", "first", 1), row(2, "assistant", "reply", 2),
                row(3, "assistant", "notice", 3), row(4, "user", "part one", 4),
                row(5, "user", "part two", 5), row(6, "assistant", "done", 6)]
        project = hermes_adapter._project_canonical_source
        full = project("session-1", rows, full_prefix=True)
        message_counts, group_counts = defaultdict(int), defaultdict(int)
        first = project("session-1", rows[:2], full_prefix=False,
                        identity_occurrences=message_counts, group_occurrences=group_counts,
                        include_group_boundaries=True)
        second = project("session-1", rows[2:], full_prefix=False,
                         identity_occurrences=message_counts, group_occurrences=group_counts,
                         prior_group_count=1, include_group_boundaries=True)
        self.assertEqual(first["groups"] + second["groups"], full["groups"])
        self.assertEqual(first["_group_ends"], [2])
        self.assertEqual(second["_group_ends"], [1, 4])

    def test_pending_user_is_not_consumed_at_page_end(self):
        rows = [row(1, "user", "first", 1), row(2, "assistant", "reply", 2),
                row(3, "user", "unfinished", 3), row(4, "tool", "tool", 4)]
        result = hermes_adapter._project_canonical_source(
            "session-1", rows, full_prefix=False, include_group_boundaries=True)
        self.assertEqual(result["_consumed_rows"], 2)
        self.assertEqual(result["_group_ends"], [2])
        self.assertTrue(result["stats"]["tail_user_incomplete"])


if __name__ == "__main__":
    unittest.main()
