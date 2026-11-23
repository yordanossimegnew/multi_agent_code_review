"""Diff parsing and GitHub fetching."""

from __future__ import annotations

import httpx
import pytest

from src.tools import DiffError, GitHubError, fetch_pr, find_file, parse_diff, parse_pr_url, render_for_review


def test_parses_example_diff_with_new_line_numbers(example_diff):
    [f] = parse_diff(example_diff)
    assert (f.path, f.status, f.additions, f.deletions) == ("app/users.py", "modified", 34, 3)
    assert f.line_text(19).strip().startswith('query = f"SELECT')  # the SQL injection line
    assert 8 in f.added_lines() and 1 not in f.added_lines()
    assert 1 in f.visible_lines()  # context lines count as visible
    text = render_for_review([f])
    assert "   19 +     query = f\"SELECT" in text
    assert "      -     rows = conn.execute(\"SELECT id, name, email FROM users LIMIT ?\"" in text


def test_added_deleted_renamed_and_multi_file():
    diff = """\
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,1 +0,0 @@
-gone = True
diff --git a/a.py b/b.py
similarity index 90%
rename from a.py
rename to b.py
--- a/a.py
+++ b/b.py
@@ -1,2 +1,2 @@
 keep = 1
--- removed line that looks like a header
+++ added line that looks like a header
\\ No newline at end of file
"""
    files = {f.path: f for f in parse_diff(diff)}
    assert files["new.py"].status == "added" and files["new.py"].added_lines() == [1, 2]
    assert files["old.py"].status == "deleted" and files["old.py"].deletions == 1
    renamed = files["b.py"]
    assert renamed.status == "renamed" and renamed.old_path == "a.py"
    assert renamed.deletions == 1 and renamed.additions == 1  # '--- ' and '+++ ' inside a hunk are content
    assert renamed.line_text(2) == "++ added line that looks like a header"


def test_rejects_non_diff():
    with pytest.raises(DiffError):
        parse_diff("just some text\nnot a diff")


def test_find_file_tolerates_prefixes(example_diff):
    files = parse_diff(example_diff)
    assert find_file(files, "./app/users.py").path == "app/users.py"
    assert find_file(files, "users.py").path == "app/users.py"
    assert find_file(files, "nope.py") is None


def test_parse_pr_url():
    assert parse_pr_url("https://github.com/langchain-ai/langgraph/pull/1234") == ("langchain-ai", "langgraph", 1234)
    assert parse_pr_url("https://github.com/o/r/pull/5/files") == ("o", "r", 5)
    with pytest.raises(GitHubError):
        parse_pr_url("https://gitlab.com/o/r/merge_requests/1")


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_pr(example_diff):
    def handler(request: httpx.Request):
        assert request.url.path == "/repos/o/r/pulls/7"
        if request.headers["accept"] == "application/vnd.github.diff":
            return httpx.Response(200, text=example_diff)
        return httpx.Response(200, json={"title": "Add search", "body": "Adds search", "user": {"login": "dev"},
                                         "base": {"ref": "main"}, "head": {"ref": "feat"}})

    pr = fetch_pr("https://github.com/o/r/pull/7", client=_client(handler))
    assert (pr.title, pr.author, pr.base, pr.head) == ("Add search", "dev", "main", "feat")
    assert pr.diff == example_diff


@pytest.mark.parametrize("status, message", [(404, "not found"), (403, "rate limit"), (500, "HTTP 500")])
def test_fetch_pr_errors(status, message):
    with pytest.raises(GitHubError, match=message):
        fetch_pr("https://github.com/o/r/pull/7", client=_client(lambda r: httpx.Response(status)))


def test_fetch_pr_too_large():
    def handler(request):
        if request.headers["accept"] == "application/vnd.github.diff":
            return httpx.Response(200, text="x" * 500)
        return httpx.Response(200, json={"title": "t"})

    with pytest.raises(GitHubError, match="limit"):
        fetch_pr("https://github.com/o/r/pull/7", client=_client(handler), max_chars=100)
