from django.urls import path
from . import views

urlpatterns = [
    path("<str:name>/", views.node_detail, name="node_detail"),
]
