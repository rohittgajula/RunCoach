from django.urls import path

from . import views

urlpatterns = [
    path("reminders/", views.reminders, name="reminders"),
    path("reminders/subscribe/", views.subscribe, name="reminders-subscribe"),
    path("reminders/unsubscribe/", views.unsubscribe, name="reminders-unsubscribe"),
    path("reminders/test/", views.test_push, name="reminders-test"),
]
