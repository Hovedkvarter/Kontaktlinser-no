"""Classify the complete event diff; never suppress unknown site inputs."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT_DOCS = {"AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "README.md"}

ROOT_DOCS.add("data/store_price_history/README.md")


def documentation(path):
    # Only reviewed non-runtime documentation locations, not all *.md files.
    p = PurePosixPath(path)
    return (path in ROOT_DOCS or
            (p.suffix == ".md" and
             (path.startswith("docs/") or path.startswith(".claude/rules/"))))


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE)


def commit(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value) or set(value) == {"0"}:
        raise ValueError("Missing or invalid event commit; refusing operational work")
    git("cat-file", "-e", value + "^{commit}")
    return value


def classify(event_name, event):
    if event_name in {"schedule", "workflow_dispatch"}:
        return True, True
    if event_name == "push" and event.get("created") is True and event.get("before") == "0" * 40:
        # A new branch has no prior published tree. Preserve initial builds.
        commit(event.get("after"))
        return True, True
    if event_name == "push":
        before, after = commit(event.get("before")), commit(event.get("after"))
    elif event_name == "pull_request":
        pr = event["pull_request"]
        base, after = commit(pr["base"]["sha"]), commit(pr["head"]["sha"])
        before = git("merge-base", base, after).decode("ascii").strip()
    else:
        raise ValueError("Unsupported event; refusing operational work")
    # No API pagination/file limit; no HEAD~1 shortcut. Disable rename detection
    # so moving a site input into docs still exposes the deleted original path.
    raw = git("diff", "--name-only", "--no-renames", "-z", before, after, "--")
    paths = [p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p]
    changed = any(not documentation(p) for p in paths)
    return changed, event_name == "push" and changed


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    changed, operational = classify(os.environ["GITHUB_EVENT_NAME"], event)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"site_changed={str(changed).lower()}\n")
        output.write(f"operational={str(operational).lower()}\n")
    print(f"site_changed={changed}; operational={operational}")


if __name__ == "__main__":
    main()
