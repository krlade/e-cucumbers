from django.urls import path
from . import views

urlpatterns = [
    path("<str:name>/", views.node_detail, name="node_detail"),
    path("<str:name>/pins/", views.node_get_pins, name="node_get_pins"),
    path("<str:name>/format/", views.node_get_format, name="node_get_format"),
    # Scheduler CRUD
    path("<str:name>/schedule/add/", views.schedule_add, name="schedule_add"),
    path("<str:name>/schedule/<int:sc_id>/delete/", views.schedule_delete, name="schedule_delete"),
    path("<str:name>/schedule/<int:sc_id>/toggle/", views.schedule_toggle, name="schedule_toggle"),
]

