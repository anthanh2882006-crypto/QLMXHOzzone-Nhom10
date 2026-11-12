from django.urls import path
from . import views
from . import uc04_views
from .files import download
from django.contrib.auth.decorators import login_required
from .handling import database_errors

app_name = "knowledge"

urlpatterns = [
    path("files/<int:attachment_id>/", download, name="attachment_download"),
    path("references/<int:reference_id>/file/", download, name="reference_download"),
    path("", views.knowledge_list, name="list"),
    path("search/", views.knowledge_search, name="search"),
    path("filter/", views.knowledge_filter, name="filter"),
    path("lesson/<int:pk>/", views.lesson_detail, name="lesson_detail"),
    path("article/<int:pk>/", views.article_detail, name="article_detail"),
    path("lesson/<int:pk>/save/", views.toggle_lesson_saved, name="toggle_lesson_saved"),
    path("article/<int:pk>/save/", views.toggle_article_saved, name="toggle_article_saved"),
    path("saved/", views.saved_content, name="saved"),
    path("support/", views.support_finder, name="support"),
    path("support/profile/<int:user_id>/", views.support_profile, name="support_profile"),
    path("saved/remove/<int:saved_id>/", views.remove_saved_item, name="remove_saved_item"),
    path(
        "review-queue/",
        uc04_views.review_queue,
        name="review_queue",
    ),
    path(
        "review/<int:pk>/",
        uc04_views.normalize_lesson,
        name="normalize_lesson",
    ),
    path(
        "review/<int:pk>/reopen/",
        uc04_views.reopen_review,
        name="reopen_review",
    ),
    path("viet-bai/", views.article_editor, name="create"),
]

for pattern in urlpatterns:
    pattern.callback = login_required(database_errors(pattern.callback), login_url="accounts:login")
