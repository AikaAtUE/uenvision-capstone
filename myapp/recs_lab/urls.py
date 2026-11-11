"""/recs-lab/ pages (developers only, never linked from the site). Included from myapp/urls.py."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.index_view, name="recs_lab"),
    path("faculty/", views.faculty_view, name="recs_lab_faculty"),
    path("admin/", views.admin_view, name="recs_lab_admin"),
    path("student/", views.student_view, name="recs_lab_student"),
    path("alumni/", views.alumni_view, name="recs_lab_alumni"),
    path("blueprints/", views.blueprints_view, name="recs_lab_blueprints"),
    path("skills/", views.skills_view, name="recs_lab_skills"),
    path("resources/", views.resources_view, name="recs_lab_resources"),
    path("data/", views.data_switch_view, name="recs_lab_data"),
]
