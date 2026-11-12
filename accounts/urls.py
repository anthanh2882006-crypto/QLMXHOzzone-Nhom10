from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("dang-nhap/", views.OzzoneLoginView.as_view(), name="login"),
    path("dang-xuat/", views.logout_view, name="logout"),
    path("doi-mat-khau-lan-dau/", views.first_password, name="first_password"),
    path("vao-he-thong/", views.after_login, name="after_login"),
    path("ho-so/", views.profile, name="profile"),
    path("ho-so/chinh-sua/", views.profile_edit, name="profile_edit"),
    path("cai-dat/", views.account_settings, name="settings"),
    path("nhan-vien/", views.directory, name="directory"),
    path("nhan-vien/<str:username>/", views.employee_detail, name="employee"),
]
