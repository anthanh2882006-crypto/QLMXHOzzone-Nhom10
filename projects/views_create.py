"""UC-PRJ-01, mở biểu mẫu và tạo dự án qua một giao dịch đầy đủ."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .forms_create import ProjectCreateForm
from .permissions import explicit_permission
from .presentation import form_page, handled
from .services_common import request_token
from .services_posts import create_project


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def project_create(request):
    """GD-044. Kiểm tra biểu mẫu và khởi tạo đủ dự án cùng trách nhiệm ban đầu."""
    if request.method == "GET" and not explicit_permission(request.user, "add_duan"):
        raise PermissionDenied("Tài khoản cần được gán quyền tạo dự án của tổ chức.")
    form = ProjectCreateForm(
        request.POST if request.method == "POST" else None,
        initial={
            "request_token": request_token(request.user, "UC-PRJ-01"),
            "ngay_bat_dau": timezone.localdate(),
            "pham_vi_truy_cap": "thanh_vien",
        },
    )
    status_code = 200
    if request.method == "POST" and form.is_valid():
        try:
            pk = create_project(request.user, form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        except PermissionDenied as exc:
            form.add_error(None, str(exc))
            status_code = 403
        except DatabaseError:
            form.add_error(
                None,
                "Chưa tạo được dự án. Các dữ liệu khởi tạo được hoàn tác, bạn có thể thử lại.",
            )
        else:
            messages.success(
                request, "Đã tạo dự án và cộng đồng liên kết. Bạn là quản lý và OWNER ban đầu."
            )
            return redirect("projects:detail", pk=pk)
    return form_page(
        request,
        form,
        "Tạo dự án mới",
        reverse("projects:list"),
        submit_label="Tạo dự án",
        status=status_code,
        notice="Người tạo đảm nhận Quản lý dự án và Chủ sở hữu cộng đồng ban đầu. Hai vai trò được quản lý độc lập sau khi tạo.",
    )
