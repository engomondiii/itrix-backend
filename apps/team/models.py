"""
Team models.

Intentionally empty: a "team member" *is* an ``apps.authentication.User``. The team
app exposes management views over that user table rather than introducing a second,
divergent model. (This mirrors the spec's note that there is no separate model here.)
"""

from __future__ import annotations

# No models. See apps.authentication.models.User.
