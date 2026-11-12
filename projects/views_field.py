"""UC-PRJ-06, xem thiết bị và ghi hiện trạng với ngữ cảnh tài sản được đối chiếu."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from projectp.models import MaThietBi
from .forms_field import FieldUpdateForm
from .permissions import project_access, readable_project_posts
from .presentation import form_page, handled, screen
from .services_common import request_token
from .services_posts import create_post, current_asset, device_context


@login_required(login_url="projects:login")
@require_GET
@handled
def equipment_detail(request, pk, target):
    """GD-055. Đối chiếu thiết bị, tài sản hiện hành và lịch sử tài sản."""
    project, membership = project_access(request.user, pk)
    device = get_object_or_404(MaThietBi, pk=target, du_an=project)
    context = screen(project, membership, device.ten_thiet_bi, "equipment")
    try:
        context["current_asset"] = current_asset(device)
    except ValidationError as exc:
        context["asset_error"] = " ".join(exc.messages)
    context.update(
        device=device,
        assets=device.taisanthietbi_set.order_by("-ngay_bat_dau_su_dung", "-pk"),
        updates=readable_project_posts(request.user, project)
        .filter(ma_the_thiet_bi=device)
        .select_related("tai_san", "nguoi_dang")[:10],
    )
    return render(request, "projects/equipment_detail.html", context)


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@handled
def field_update_create(request, pk, target):
    """GD-056. Ghi hiện trạng sau khi kiểm tra lại thiết bị/tài sản lúc gửi."""
    project, membership = project_access(request.user, pk, write=request.method == "GET")
    devices = MaThietBi.objects.filter(du_an=project)
    if request.method == "GET":
        devices = devices.filter(dang_su_dung=True)
    device = get_object_or_404(devices, pk=target)
    asset, asset_error, context_value = None, "", ""
    try:
        asset = current_asset(device)
        context_value = device_context(device)
    except ValidationError as exc:
        asset_error = " ".join(exc.messages)
    form = FieldUpdateForm(
        request.POST if request.method == "POST" else None,
        request.FILES or None,
        initial={
            "request_token": request_token(request.user, "UC-PRJ-06", pk, target),
            "asset_context": context_value,
        },
    )
    status_code = 200
    if request.method == "POST" and form.is_valid():
        try:
            # Dịch vụ phân biệt yêu cầu đã hoàn tất với lệnh ghi mới, rồi mới kiểm tra tài sản.
            post_id = create_post(request.user, project, form.cleaned_data, device)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            # Hiển thị ngữ cảnh mới để người dùng đối chiếu, giữ nguyên phần nội dung đã nhập.
            device.refresh_from_db()
            try:
                asset = current_asset(device)
                context_value = device_context(device)
            except ValidationError as context_error:
                asset_error = " ".join(context_error.messages)
            form.data = form.data.copy()
            form.data["asset_context"] = context_value
        except PermissionDenied as exc:
            form.add_error(None, str(exc))
            status_code = 403
        except DatabaseError:
            form.add_error(
                None,
                "Chưa ghi được hiện trạng. Các thay đổi được hoàn tác, bạn có thể thử lại.",
            )
        else:
            messages.success(
                request, "Đã ghi nhận hiện trường và giữ ngữ cảnh tài sản tại thời điểm ghi."
            )
            if form.cleaned_data["che_do_xu_ly"]:
                return redirect("projects:issue", pk=pk, post_id=post_id)
            return redirect(reverse("projects:feed", kwargs={"pk": pk}) + f"#post-{post_id}")
    return form_page(
        request,
        form,
        "Tạo cập nhật hiện trường",
        reverse("projects:equipment_detail", kwargs={"pk": pk, "target": target}),
        project,
        membership,
        section="equipment",
        submit_label="Đăng cập nhật",
        device=device,
        current_asset=asset,
        asset_error=asset_error,
        confirm_leave=True,
        status=status_code,
    )
