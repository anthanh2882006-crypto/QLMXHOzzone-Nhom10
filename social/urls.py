from django.urls import path

from . import views

app_name = "social"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("tao-bai-viet/", views.create_post, name="create"),
    path("bai-viet-cua-toi/", views.my_posts, name="my_posts"),
    path("noi-dung-da-luu/", views.saved_posts, name="saved"),
    path("bai-viet/<int:pk>/", views.post_detail, name="post_detail"),
    path("bai-viet/<int:pk>/binh-luan/", views.create_comment, name="comment_create"),
    path("bai-viet/<int:pk>/cam-xuc/", views.set_reaction, name="reaction_set"),
    path("bai-viet/<int:pk>/luu/", views.set_saved, name="save_set"),
    path("bai-viet/<int:pk>/sua/", views.edit_post, name="edit"),
    path("bai-viet/<int:pk>/xoa/", views.delete_post, name="delete"),
    path("tep/<int:attachment_id>/tai-xuong/", views.attachment_download, name="attachment_download"),
    path("thong-bao-chinh-thuc/<int:pk>/", views.notice_detail, name="notice_detail"),
]
