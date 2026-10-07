from rest_framework.throttling import ScopedRateThrottle


class FixedScopeThrottle(ScopedRateThrottle):
    """ScopedRateThrottle whose scope is set on the class, not the view.

    Plain ScopedRateThrottle reads `view.throttle_scope` and, finding none on an
    @api_view function, silently allows everything — so a subclass that only set
    `scope = "chat"` throttled nothing. This uses the class scope when there is one.
    """

    def allow_request(self, request, view):
        scope = getattr(type(self), "scope", None)  # the class's, not a past call's
        if not scope:
            return super().allow_request(request, view)
        self.scope = scope
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super(ScopedRateThrottle, self).allow_request(request, view)


class ChatThrottle(FixedScopeThrottle):
    """Chat turns, Guide/Review and meal estimates: endpoints that spend money."""

    scope = "chat"


class ChatWriteThrottle(ChatThrottle):
    """R13: the chat scope for POST only — a GET on the same path is a free read."""

    def allow_request(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return super().allow_request(request, view)
