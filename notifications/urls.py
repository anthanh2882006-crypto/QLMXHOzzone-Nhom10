from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notice_list, name="list"),
    path("tao/", views.notice_create, name="create"),
    path("tao/dinh-chinh/<int:reference_id>/", views.notice_create, name="correction"),
    path("ban-nhap/<int:pk>/sua/", views.notice_edit_draft, name="edit_draft"),
    path("ban-nhap/<int:pk>/huy/", views.notice_cancel_draft, name="cancel_draft"),
    path("<int:pk>/xac-nhan/", views.notice_ack_confirm, name="ack_confirm"),
    path("<int:pk>/theo-doi/", views.notice_tracking, name="tracking"),
    path("<int:pk>/", views.notice_detail, name="detail"),
    path("tep/<int:attachment_id>/tai-xuong/", views.notice_attachment_download, name="attachment_download"),
]
