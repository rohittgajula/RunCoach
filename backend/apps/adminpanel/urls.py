from django.urls import path

from . import ai, system, users

urlpatterns = [
    path("users/", users.users, name="admin-users"),
    path("users/<int:pk>/", users.user_detail, name="admin-user"),
    path("invites/", users.invites, name="admin-invites"),
    path("invites/<int:pk>/revoke/", users.invite_revoke, name="admin-invite-revoke"),
    path("ai/providers/", ai.providers, name="admin-ai-providers"),
    path("ai/config/", ai.config, name="admin-ai-config"),
    path("ai/test/", ai.test_prompt, name="admin-ai-test"),
    path("ai/prices/", ai.prices, name="admin-ai-prices"),
    path("ai/prices/<int:pk>/", ai.price_detail, name="admin-ai-price"),
    path("ai/stats/", ai.stats, name="admin-ai-stats"),
    path("system/", system.system, name="admin-system"),
]
