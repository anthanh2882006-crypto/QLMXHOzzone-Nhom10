"""Tạo ngữ cảnh giao diện, điều hướng và thông báo dùng chung cho các Use Case."""

from functools import wraps
import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import render
from django.utils import timezone

from .utils import related_url

logger = logging.getLogger(__name__)


def screen(project=None, membership=None, title="Dự án", section="list"):
    context = {
        "project": project,
        "membership": membership,
        "page_title": title,
        "section": section,
        "active_nav": "projects",
        "back_url": (
            related_url("projects:detail", pk=project.pk)
            if project and section != "detail"
            else related_url("projects:list")
        ),
    }
    if project:
        items = [
            ("detail", "Tổng quan"),
            ("feed", "Bảng tin dự án"),
            ("issues", "Vấn đề kỹ thuật"),
            ("members", "Thành viên & vai trò"),
            ("equipment", "Thiết bị & tài sản"),
            ("history", "Lịch sử dự án"),
        ]
        if membership and membership.vai_tro == "quan_ly" and not project.da_luu_tru:
            items.insert(1, ("manage", "Quản lý dự án"))
            items.insert(-1, ("knowledge", "Phân công tri thức"))
        context["project_nav"] = [
            (key, label, related_url(f"projects:{key}", pk=project.pk)) for key, label in items
        ]
    return context


def handled(view):
    """Lỗi quyền/dữ liệu có phản hồi rõ, lỗi truy vấn trả 503 và cho tải lại."""

    @wraps(view)
    @timezone.override("Asia/Ho_Chi_Minh")
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except PermissionDenied as exc:
            return render(
                request, "projects/error.html", {"error_message": str(exc)}, status=403
            )
        except ValidationError as exc:
            return render(
                request,
                "projects/error.html",
                {"error_message": " ".join(exc.messages)},
                status=400,
            )
        except DatabaseError:
            logger.exception("Không hoàn tất chức năng dự án")
            return render(
                request,
                "projects/error.html",
                {
                    "error_message": "Chưa tải/lưu được dữ liệu. Vui lòng thử lại.",
                    "retry_url": request.get_full_path(),
                },
                status=503,
            )

    return wrapped


def form_page(
    request, form, title, cancel_url, project=None, membership=None, status=200, **extra
):
    context = screen(project, membership, title, extra.pop("section", "detail"))
    context.update(
        form=form, cancel_url=cancel_url, submit_label=extra.pop("submit_label", "Lưu"), **extra
    )
    template = "projects/asset_context_error.html" if context.get("asset_error") else "projects/action_form.html"
    return render(request, template, context, status=status)
