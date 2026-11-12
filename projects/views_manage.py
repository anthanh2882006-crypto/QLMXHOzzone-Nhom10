"""UC-PRJ-03. Mỗi hàm công khai bên dưới là một hành động từ giao diện dự án."""

from accounts.views._chung import ho_ten
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from django.utils import timezone
from projectp.models import (
    MaThietBi,
    MemberStatus,
    PhanCongTriThuc,
    TaiSanThietBi,
    ThanhVienDuAn,
)
from . import forms_manage as forms
from .services_manage import archive_reasons, execute, managed_project, outstanding, revision
from .utils import related_url
from .permissions import project_access
from .policies import curator_limit

logger = logging.getLogger(__name__)


def url(name, project, **kwargs):
    return reverse(f"projects:{name}", kwargs={"pk": project.pk, **kwargs})


def context(project, section, title, user):
    from .presentation import screen

    membership = project.thanh_vien.filter(
        nguoi_dung=user,
        nguoi_dung__is_active=True,
        trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True,
    ).first()
    return screen(project, membership, title, section)


def error(request, exc, status=403):
    text = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
    return render(request, "projects/error.html", {"error_message": text}, status=status)


@login_required(login_url="projects:login")
@require_GET
@timezone.override("Asia/Ho_Chi_Minh")
def management_listing(request, pk, section):
    try:
        project, membership = project_access(request.user, pk)
        can_manage = membership.vai_tro == "quan_ly" and not project.da_luu_tru
        q = request.GET.get("q", "").strip()[:100]
        status = request.GET.get("status", "")
        ctx = context(
            project,
            section,
            (
                "Thành viên & vai trò dự án"
                if section == "members"
                else "Thiết bị & tài sản dự án"
            ),
            request.user,
        )
        if section == "members":
            query = ThanhVienDuAn.objects.filter(du_an=project).select_related("nguoi_dung")
            if q:
                query = query.filter(
                    Q(nguoi_dung__first_name__icontains=q)
                    | Q(nguoi_dung__last_name__icontains=q)
                    | Q(nguoi_dung__username__icontains=q)
                )
            choices = MemberStatus.choices
            if status in MemberStatus.values:
                query = query.filter(trang_thai=status)
            page = Paginator(query.order_by("nguoi_dung__first_name", "pk"), 20).get_page(
                request.GET.get("page")
            )
            rows = []
            for member in page:
                editable = (
                    can_manage
                    and member.trang_thai == MemberStatus.ACTIVE
                    and member.ket_thuc_luc is None
                )
                rows.append(
                    {
                        "cells": [
                            ho_ten(member.nguoi_dung),
                            member.get_vai_tro_display(),
                            member.get_trang_thai_display(),
                        ],
                        "edit_url": (
                            url("member_role", project, target=member.pk) if editable else None
                        ),
                        "end_url": (
                            url("member_end", project, target=member.pk) if editable else None
                        ),
                    }
                )
            ctx.update(
                columns=["Họ tên", "Vai trò", "Trạng thái"],
                add_url=url("member_add", project) if can_manage else None,
                add_label="+ Thêm thành viên",
            )
        else:
            query = MaThietBi.objects.filter(du_an=project).prefetch_related(
                "taisanthietbi_set"
            )
            if q:
                query = query.filter(Q(ma_thiet_bi__icontains=q) | Q(ten_thiet_bi__icontains=q))
            choices = [("1", "Đang sử dụng"), ("0", "Ngừng sử dụng")]
            if status in ("1", "0"):
                query = query.filter(dang_su_dung=(status == "1"))
            page = Paginator(query.order_by("ma_thiet_bi", "pk"), 20).get_page(
                request.GET.get("page")
            )
            rows = []
            for device in page:
                assets = [
                    a for a in device.taisanthietbi_set.all() if a.trang_thai == "dang_su_dung"
                ]
                current = (
                    assets[0].ma_tai_san_noi_bo
                    if len(assets) == 1
                    else ("Lỗi: nhiều tài sản hiện hành" if assets else "Chưa gắn")
                )
                rows.append(
                    {
                        "cells": [
                            device.ma_thiet_bi,
                            device.ten_thiet_bi,
                            current,
                            "Đang sử dụng" if device.dang_su_dung else "Ngừng sử dụng",
                        ],
                        "view_url": url("equipment_detail", project, target=device.pk),
                        "edit_url": (
                            url("equipment_edit", project, target=device.pk)
                            if can_manage
                            else None
                        ),
                    }
                )
            ctx.update(
                columns=["Mã thiết bị", "Tên", "Tài sản hiện hành", "Trạng thái"],
                add_url=url("equipment_add", project) if can_manage else None,
                add_label="+ Thêm thiết bị",
            )
        ctx.update(rows=rows, page_obj=page, q=q, status=status, status_choices=choices)
        return render(request, "projects/manage_table.html", ctx)
    except (PermissionDenied, ValidationError) as exc:
        return error(request, exc)
    except DatabaseError:
        logger.exception("Không tải được quản lý dự án")
        return error(request, "Không tải được dữ liệu. Vui lòng thử lại.", 503)


@login_required(login_url="projects:login")
@require_http_methods(["GET", "POST"])
@timezone.override("Asia/Ho_Chi_Minh")
def management_form(request, pk, action, target=None):
    try:
        project = managed_project(request.user, pk)
        section = {
            "info": "manage",
            "member_add": "members",
            "member_role": "members",
            "member_end": "members",
            "equipment": "equipment",
            "knowledge": "knowledge",
            "knowledge_end": "knowledge",
            "archive": "manage",
        }[action]
        titles = {
            "info": "Quản lý dự án",
            "member_add": "Thêm thành viên dự án",
            "member_role": "Điều chỉnh vai trò tại dự án",
            "member_end": "Kết thúc tư cách thành viên",
            "equipment": "Thông tin thiết bị",
            "knowledge": "Phân công tri thức dự án",
            "knowledge_end": "Kết thúc phân công tri thức",
            "archive": "Lưu trữ dự án",
        }
        ctx = context(project, section, titles[action], request.user)
        ctx["submit_label"] = {
            "info": "Lưu thông tin",
            "member_add": "Thêm thành viên",
            "member_role": "Lưu vai trò",
            "member_end": "Kết thúc tư cách",
            "equipment": "Lưu thông tin",
            "knowledge": "Lưu phân công",
            "knowledge_end": "Kết thúc phân công",
            "archive": "Xác nhận lưu trữ",
        }[action]
        initial = {"revision": revision(project)}
        form_class, kwargs = forms.ConfirmForm, {}
        if action == "info":
            form_class = forms.ProjectInfoForm
            initial.update(ten_du_an=project.ten_du_an, mo_ta=project.mo_ta)
        elif action == "member_add":
            form_class, kwargs = forms.AddMemberForm, {"project": project}
            initial["vai_tro"] = "thanh_vien"
        elif action in ("member_role", "member_end"):
            member = get_object_or_404(
                ThanhVienDuAn.objects.select_related("nguoi_dung"), pk=target, du_an=project
            )
            if request.method == "GET" and (
                member.trang_thai != MemberStatus.ACTIVE or member.ket_thuc_luc is not None
            ):
                messages.info(
                    request,
                    "Tư cách thành viên đã thay đổi. Xem trạng thái hiện hành trong danh sách.",
                )
                return redirect("projects:members", pk=pk)
            ctx["subject"] = (
                ho_ten(member.nguoi_dung)
            )
            if action == "member_role":
                form_class = forms.RoleForm
                initial["vai_tro"] = member.vai_tro
                ctx["as_dialog"] = True
            ctx["explanation"] = (
                "Vai trò chỉ đổi tại dự án này. Cần duy trì quản lý; rời dự án phải bàn giao trách nhiệm và OWNER nếu có."
            )
        elif action == "equipment":
            form_class = forms.EquipmentForm
            initial["dang_su_dung"] = "1"
            if target:
                device = get_object_or_404(MaThietBi, pk=target, du_an=project)
                initial.update(
                    ma_thiet_bi=device.ma_thiet_bi,
                    ten_thiet_bi=device.ten_thiet_bi,
                    mo_ta=device.mo_ta,
                    dang_su_dung="1" if device.dang_su_dung else "0",
                )
                ctx["history_columns"] = [
                    "Mã tài sản",
                    "Serial",
                    "Trạng thái",
                    "Bắt đầu",
                    "Kết thúc",
                ]
                ctx["history_rows"] = [
                    {
                        "cells": [
                            a.ma_tai_san_noi_bo,
                            a.so_serial or "—",
                            a.get_trang_thai_display(),
                            a.ngay_bat_dau_su_dung,
                            a.ngay_ket_thuc_su_dung or "—",
                        ]
                    }
                    for a in TaiSanThietBi.objects.filter(ma_the_thiet_bi=device).order_by(
                        "-ngay_bat_dau_su_dung", "-pk"
                    )
                ]
            ctx["explanation"] = (
                "Tài sản hiện hành được giữ nếu không chọn thay/ngừng. Lịch sử và cập nhật cũ không chuyển sang tài sản mới."
            )
        elif action == "knowledge":
            ctx["policy_warning"] = (
                "Chưa có quy tắc số phân công đồng thời được áp dụng cho dự án này."
                if curator_limit() is None
                else ""
            )
            form_class, kwargs = forms.KnowledgeForm, {"project": project}
            ctx["explanation"] = (
                "Phạm vi: nguồn đủ điều kiện trong dự án. Phân công không tự cấp quyền đọc nguồn; UC-KNW-04 phải kiểm tra lại quyền trên từng nguồn."
            )
            ctx["history_columns"] = ["Người phụ trách", "Bắt đầu", "Kết thúc", "Căn cứ"]
            ctx["history_rows"] = [
                {
                    "cells": [
                        ho_ten(a.nguoi_phu_trach),
                        a.ngay_phan_cong,
                        a.ket_thuc_luc or "Đang hiệu lực",
                        a.ghi_chu,
                    ],
                    "end_url": (
                        url("knowledge_end", project, target=a.pk)
                        if a.ket_thuc_luc is None
                        else None
                    ),
                }
                for a in PhanCongTriThuc.objects.filter(du_an=project)
                .select_related("nguoi_phu_trach")
                .order_by("-ngay_phan_cong", "-pk")
            ]
        elif action == "knowledge_end":
            assignment = get_object_or_404(
                PhanCongTriThuc.objects.select_related("nguoi_phu_trach"),
                pk=target,
                du_an=project,
            )
            ctx["subject"] = (
                ho_ten(assignment.nguoi_phu_trach)
            )
            ctx["explanation"] = (
                "Kết thúc hiệu lực, giữ phân công và lịch sử. Nếu còn nguồn đang chờ, phải thay người và bàn giao."
            )
        elif action == "archive":
            ctx.update(work=outstanding(project), archive_reasons=archive_reasons(project))
            ctx["explanation"] = (
                "Lưu trữ giữ lịch sử, chặn ghi mới trong dự án; UC này không có mở lại. Chuẩn hóa nguồn lịch sử theo UC-KNW-04 vẫn cần đủ quyền và điều kiện."
            )
        ctx["cancel_url"] = url(
            "detail" if action == "info" else "manage" if action == "archive" else section,
            project,
        )
        form = form_class(
            request.POST if request.method == "POST" else None, initial=initial, **kwargs
        )
        status_code = 200
        if request.method == "POST" and form.is_valid():
            try:
                execute(
                    request.user,
                    pk,
                    form.cleaned_data["revision"],
                    action,
                    form.cleaned_data,
                    target,
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            except PermissionDenied as exc:
                form.add_error(None, str(exc))
                status_code = 403
            except DatabaseError:
                logger.exception("Không lưu được UC-PRJ-03")
                form.add_error(
                    None,
                    "Chưa lưu được thay đổi. Trạng thái trước thao tác được giữ; tải lại và đối chiếu trước khi thử lại.",
                )
                status_code = 503
            else:
                messages.success(request, "Đã hoàn tất thao tác.")
                if action == "archive":
                    return redirect("projects:detail", pk=pk)
                if not ThanhVienDuAn.objects.filter(
                    du_an_id=pk,
                    nguoi_dung=request.user,
                    trang_thai=MemberStatus.ACTIVE,
                    ket_thuc_luc__isnull=True,
                    vai_tro="quan_ly",
                ).exists():
                    return redirect("projects:list")
                return redirect(
                    "projects:manage" if action == "info" else f"projects:{section}", pk=pk
                )
        ctx["form"] = form
        return render(
            request,
            "projects/manage_info.html" if action == "info" else "projects/manage_form.html",
            ctx,
            status=status_code,
        )
    except (PermissionDenied, ValidationError) as exc:
        return error(request, exc)
    except DatabaseError:
        logger.exception("Không mở được biểu mẫu quản lý dự án")
        return error(request, "Không tải được dữ liệu. Vui lòng thử lại.", 503)


# Các URL gọi hàm có tên nghiệp vụ, views.py tổng chỉ import lại các hàm này.
def project_manage(request, pk):
    """GD-047, xem và cập nhật tên/mô tả của dự án được giao."""
    return management_form(request, pk, "info")


def member_list(request, pk):
    """GD-048, xem danh sách tư cách và các thao tác quản lý thành viên."""
    return management_listing(request, pk, "members")


def member_add(request, pk):
    """Thêm thành viên và đồng bộ tư cách cộng đồng dự án."""
    return management_form(request, pk, "member_add")


def member_role_update(request, pk, target):
    """GD-049, đổi vai trò tại đúng dự án, giữ người quản lý cần thiết."""
    return management_form(request, pk, "member_role", target)


def member_end(request, pk, target):
    """Kết thúc tư cách sau khi đã xử lý trách nhiệm và OWNER nếu có."""
    return management_form(request, pk, "member_end", target)


def equipment_list(request, pk):
    """GD-050, danh sách thiết bị và tài sản hiện hành."""
    return management_listing(request, pk, "equipment")


def equipment_create(request, pk):
    """GD-051, thêm mã thiết bị vào đúng dự án."""
    return management_form(request, pk, "equipment")


def equipment_update(request, pk, target):
    """GD-051, đổi thông tin hoặc thay tài sản và giữ lịch sử cũ."""
    return management_form(request, pk, "equipment", target)


def knowledge_assign(request, pk):
    """GD-052, phân công/thay người và kiểm tra quyền đọc nguồn bàn giao."""
    return management_form(request, pk, "knowledge")


def knowledge_end(request, pk, target):
    """Kết thúc phân công không còn công việc đang chờ bàn giao."""
    return management_form(request, pk, "knowledge_end", target)


def project_archive(request, pk):
    """Kiểm tra ảnh hưởng, điều kiện tổ chức rồi xác nhận lưu trữ."""
    return management_form(request, pk, "archive")
