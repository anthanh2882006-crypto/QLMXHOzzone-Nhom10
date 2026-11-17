from projectp.models import (
    BaiViet,
    DuAn,
    MemberStatus,
    ThanhVienDuAn,
)

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404


def active_memberships(user):
    """Lấy tư cách thành viên dự án đang có hiệu lực."""

    if not user.is_authenticated or not user.is_active:
        return ThanhVienDuAn.objects.none()

    return ThanhVienDuAn.objects.filter(
        nguoi_dung=user,
        nguoi_dung__is_active=True,
        trang_thai=MemberStatus.ACTIVE,
        ket_thuc_luc__isnull=True,
    )


def readable_projects(user):
    """Lấy danh sách dự án người dùng được phép xem."""

    project_ids = active_memberships(user).values_list(
        "du_an_id",
        flat=True,
    )

    return DuAn.objects.filter(
        pk__in=project_ids,
        cong_dong__da_xoa_mem=False,
    )


def readable_project_posts(user, project):
    """Lấy các hoạt động đang hiển thị trong dự án."""

    has_access = (
        active_memberships(user)
        .filter(
            du_an=project,
        )
        .exists()
    )

    if not has_access:
        return BaiViet.objects.none()

    return (
        BaiViet.objects.filter(
            du_an=project,
            trang_thai="hien",
            da_xoa_mem=False,
        )
        .filter(Q(cong_dong__isnull=True) | Q(cong_dong_id=project.cong_dong_id))
        .order_by(
            "-ngay_tao",
            "-ma_bai_viet",
        )
    )


def explicit_permission(user, codename):
    """Quyền nghiệp vụ phải được gán rõ qua User/Group, kể cả tài khoản superuser."""
    if not user.is_authenticated:
        return False
    return (
        get_user_model()
        .objects.filter(
            pk=user.pk,
            is_active=True,
        )
        .filter(
            Q(
                user_permissions__content_type__app_label="projectp",
                user_permissions__codename=codename,
            )
            | Q(
                groups__permissions__content_type__app_label="projectp",
                groups__permissions__codename=codename,
            )
        )
        .exists()
    )


def project_access(user, pk, write=False, manager=False):
    """Giữ phạm vi dự án ở mọi URL và kiểm tra lại khi thực hiện ghi."""
    project = get_object_or_404(DuAn.objects.select_related("cong_dong"), pk=pk)
    membership = active_memberships(user).filter(du_an=project).first()
    account_active = get_user_model().objects.filter(pk=user.pk, is_active=True).exists()
    if not account_active or membership is None or project.cong_dong.da_xoa_mem:
        raise PermissionDenied("Bạn không còn tư cách truy cập dự án này.")
    if manager and membership.vai_tro != "quan_ly":
        raise PermissionDenied("Thao tác cần vai trò quản lý trong đúng dự án.")
    if write and project.da_luu_tru:
        raise PermissionDenied("Dự án đã lưu trữ. Bạn có thể xem dữ liệu lịch sử theo quyền.")
    return project, membership


def can_choose_trial(user, project):
    """UC-PRJ-07 cho phép thành viên hợp lệ chọn thử và xác định người thực hiện."""
    return readable_projects(user).filter(pk=project.pk).exists()


def can_resolve(user, project):
    """UC-PRJ-09 dành cho thành viên hợp lệ; căn cứ và trạng thái xét khi ghi."""
    return readable_projects(user).filter(pk=project.pk).exists()
