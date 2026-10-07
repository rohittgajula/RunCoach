from django.urls import path

from . import views

urlpatterns = [
    path("gear/", views.shoes, name="gear"),
    path("gear/<int:pk>/", views.shoe_detail, name="gear-detail"),
]
