"""Các lối vào bình thường của UC-PRJ-01 đến UC-PRJ-10."""

from django.urls import path
from social import views as interaction_views
from . import views

app_name = "projects"
urlpatterns = [
    path("<int:project_id>/posts/<int:pk>/binh-luan/", interaction_views.create_comment, name="comment_create"),
    path("<int:project_id>/posts/<int:pk>/cam-xuc/", interaction_views.set_reaction, name="reaction_set"),
    path("<int:project_id>/posts/<int:pk>/luu/", interaction_views.set_saved, name="save_set"),

    path("login/", views.project_login, name="login"),
    path("logout/", views.project_logout, name="logout"),
    path("", views.project_list, name="list"),
    path("create/", views.project_create, name="create"),
    path("<int:pk>/", views.project_detail, name="detail"),
    path("<int:pk>/manage/", views.project_manage, name="manage"),
    path("<int:pk>/members/", views.member_list, name="members"),
    path("<int:pk>/members/add/", views.member_add, name="member_add"),
    path("<int:pk>/members/<int:target>/role/", views.member_role_update, name="member_role"),
    path("<int:pk>/members/<int:target>/end/", views.member_end, name="member_end"),
    path("<int:pk>/equipment/", views.equipment_list, name="equipment"),
    path("<int:pk>/equipment/add/", views.equipment_create, name="equipment_add"),
    path("<int:pk>/equipment/<int:target>/", views.equipment_detail, name="equipment_detail"),
    path("<int:pk>/equipment/<int:target>/edit/", views.equipment_update, name="equipment_edit"),
    path(
        "<int:pk>/equipment/<int:target>/field-update/",
        views.field_update_create,
        name="field_create",
    ),
    path("<int:pk>/knowledge/", views.knowledge_assign, name="knowledge"),
    path("<int:pk>/knowledge/<int:target>/end/", views.knowledge_end, name="knowledge_end"),
    path("<int:pk>/archive/", views.project_archive, name="archive"),
    path("<int:pk>/feed/", views.project_feed, name="feed"),
    path("<int:pk>/posts/create/", views.project_post_create, name="post_create"),
    path("<int:pk>/posts/<int:post_id>/", views.post_detail, name="post_detail"),
    path("<int:pk>/issues/", views.issue_list, name="issues"),
    path("<int:pk>/issues/<int:post_id>/", views.issue_detail, name="issue"),
    path("<int:pk>/issues/<int:post_id>/analysis/", views.analysis_create, name="analysis_create"),
    path(
        "<int:pk>/issues/<int:post_id>/solutions/add/",
        views.solution_create,
        name="solution_create",
    ),
    path("<int:pk>/solutions/<int:target>/trial/", views.trial_create, name="trial_create"),
    path("<int:pk>/trials/<int:target>/performer/", views.trial_assign, name="trial_assign"),
    path("<int:pk>/trials/<int:target>/result/", views.result_create, name="result_create"),
    path(
        "<int:pk>/issues/<int:post_id>/resolution/",
        views.resolution_create,
        name="resolution_create",
    ),
    path("<int:pk>/history/", views.project_history, name="history"),
    path("<int:pk>/history/<int:log_id>/", views.history_detail, name="history_detail"),
    path("<int:pk>/files/<int:file_id>/", views.attachment_download, name="file"),
]
