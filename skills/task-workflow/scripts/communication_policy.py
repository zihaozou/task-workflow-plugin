"""Load the shared user-facing communication policy for Task Workflow hooks."""
from pathlib import Path


POLICY_PATH = (Path(__file__).resolve().parents[1] /
               "references/communication_policy.md")


def load_policy():
    """Return the English policy shipped with the skill, or an empty string."""
    try:
        return POLICY_PATH.read_bytes().decode("utf-8").strip()
    except (OSError, UnicodeError):
        return ""
