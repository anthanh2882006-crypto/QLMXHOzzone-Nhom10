"""Hàm dùng chung của phân hệ Tài khoản (không thuộc riêng use case nào)."""

from django.contrib.auth.decorators import user_passes_test

from projectp.models import HoSoNhanVien, KyNangNhanVien, MemberStatus, ThanhVienCongDong, ThanhVienDuAn


def da_doi_mat_khau(user):
    """Kiểm tra tài khoản đã hoàn tất yêu cầu đổi mật khẩu lần đầu."""
    ho_so = HoSoNhanVien.objects.filter(nguoi_dung_id=user.pk).first()
    return ho_so is None or not ho_so.bat_buoc_doi_mat_khau


# Kiểm tra yêu cầu đổi mật khẩu trước khi sử dụng các chức năng nghiệp vụ.
can_doi_mat_khau = user_passes_test(da_doi_mat_khau, login_url="accounts:first_password")


def ho_ten(user):
    """Họ tên kiểu Việt: 'Trần Thị Bình' (họ trước, tên sau)."""
    return f"{user.last_name} {user.first_name}".strip() or user.username


def thong_tin_ho_so(user, viewer=None):
    """Dữ liệu dùng chung cho trang Hồ sơ của tôi (GD-006) và Hồ sơ nhân viên (GD-009)."""
    from projects.permissions import readable_projects
    from communities.views._chung import active_community_memberships, cong_dong_xem_duoc
    from django.db.models import Q

    viewer = viewer or user
    communities = cong_dong_xem_duoc(viewer).filter(
        Q(loai_cong_dong="chung", pham_vi_truy_cap="noi_bo")
        | Q(pk__in=active_community_memberships(viewer).values("cong_dong_id"))
    )
    ho_so = HoSoNhanVien.objects.filter(nguoi_dung=user).first()
    return {
        "person": user,
        "profile": ho_so,
        "skills": (
            KyNangNhanVien.objects.filter(ho_so=ho_so).order_by("ky_nang__ten_ky_nang") if ho_so else []
        ),
        "projects": ThanhVienDuAn.objects.filter(
            nguoi_dung=user,
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
            du_an__in=readable_projects(viewer),
        ).order_by("du_an__ten_du_an"),
        "communities": ThanhVienCongDong.objects.filter(
            nguoi_dung=user,
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
            cong_dong__in=communities,
        ).order_by("cong_dong__ten_cong_dong"),
    }
