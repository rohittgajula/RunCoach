"""R14 §14: the in-app admin page's API (`/api/admin/…`, staff only).

No models of its own: it reads across tenants on purpose, which is exactly why every
view here is `IsAdminUser` and nothing else. Never returns a key or secret — only
whether one is configured.
"""
