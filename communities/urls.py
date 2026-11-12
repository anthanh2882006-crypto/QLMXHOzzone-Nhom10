from django.urls import path

from . import views

app_name = "communities"

urlpatterns = [
    path("", views.community_list, name="list"),
    path("yeu-cau-tham-gia/", views.join_requests, name="requests"),
    path("yeu-cau-tham-gia/<int:request_id>/xu-ly/", views.decide, name="decide"),
    path("yeu-cau-tham-gia/<int:request_id>/huy/", views.cancel_request, name="cancel_request"),
    path("kiem-duyet/", views.moderation_home, name="moderation_home"),
    path("<int:pk>/", views.community_detail, name="detail"),
    path("<int:pk>/gioi-thieu/", views.community_about, name="about"),
    path("<int:pk>/tham-gia/", views.join, name="join"),
    path("<int:pk>/roi/", views.leave, name="leave"),
    path("<int:pk>/thanh-vien/", views.members, name="members"),
    path("<int:pk>/thanh-vien/ban-giao/", views.transfer, name="transfer"),
    path("<int:pk>/bai-viet/moi/", views.post_create, name="post_create"),
    path("<int:pk>/bai-viet/<int:post_id>/", views.post_detail, name="post"),
    path("<int:pk>/kiem-duyet/", views.moderation, name="moderation"),
    path("<int:pk>/kiem-duyet/<int:post_id>/", views.moderate, name="moderate"),
]
