from rest_framework.throttling import ScopedRateThrottle


class ChatThrottle(ScopedRateThrottle):
    """Chat turns, Guide/Review and meal estimates: endpoints that spend money."""

    scope = "chat"
