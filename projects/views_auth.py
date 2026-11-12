"""Cổng đăng nhập cho các trang Dự án, dùng phiên và tài khoản Django hiện có."""

from django.contrib.auth.views import LogoutView
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


def project_login(request):
    target = request.GET.get("next") or reverse("projects:list")
    return redirect(reverse("accounts:login") + "?" + urlencode({"next": target}))

project_logout = LogoutView.as_view(next_page="accounts:login")
