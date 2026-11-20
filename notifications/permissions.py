from django.contrib.auth import get_user_model

from projectp.models import (
    BaiViet,
    CongDong,
    DuAn,
    HoSoNhanVien,
    MemberStatus,
    ThanhVienCongDong,
    ThanhVienDuAn,
)


PUBLISH_PERMISSION = "projectp.cong_bo_thong_bao"
TRACK_PERMISSION = "projectp.theo_doi_tiep_nhan"
PUBLISH_GROUP_PREFIX = "OZZONE:SOC-06:"
TRACK_GROUP_PREFIX = "OZZONE:SOC-09:"
NOTICE_SCOPE_PREFIXES = (PUBLISH_GROUP_PREFIX, TRACK_GROUP_PREFIX)
TRACK_COMPANY_GROUP = f"{TRACK_GROUP_PREFIX}toan_cong_ty"
TRACK_TARGETS = ("phong_ban", "cong_dong", "du_an", "nguoi_dung")


def has_distribution_scope(user, prefix, scope, criteria):
    scopes = set(user.groups.filter(name__startswith=prefix).values_list("name", flat=True))
    if f"{prefix}toan_cong_ty" in scopes:
        return True
    if scope == "toan_cong_ty" or not scopes:
        return False
    required = set()
    for item in criteria:
        kind = item.loai_tieu_chi
        target_id = getattr(item, f"{kind}_id", None) if kind in TRACK_TARGETS else None
        if target_id is None:
            return False
        required.add(f"{prefix}{kind}:{target_id}")
    return bool(required) and required.issubset(scopes)


def can_publish_notices(user):
    """Quyền nghiệp vụ UC-SOC-06; is_staff tự nó không cấp quyền này."""
    return bool(user and user.is_authenticated and user.is_active and user.has_perm(PUBLISH_PERMISSION))


def can_track_notices(user):
    return bool(user and user.is_authenticated and user.is_active and user.has_perm(TRACK_PERMISSION))


def can_track_notice(user, notice):
    """Apply the dedicated internal-distribution role to published ACK notices."""
    if not can_track_notices(user):
        return False
    if not notice or notice.trang_thai != "da_cong_bo" or not notice.yeu_cau_xac_nhan:
        return False
    if not has_distribution_scope(
        user, TRACK_GROUP_PREFIX, notice.che_do_phan_phoi,
        notice.tieu_chi.filter(muc_dich="phan_phoi").only("loai_tieu_chi", *TRACK_TARGETS),
    ):
        return False
    return BaiViet.objects.filter(
        pk=notice.bai_viet_id,
        da_xoa_mem=False,
        trang_thai="hien",
        loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
    ).exists()


def can_manage_draft(user, notice):
    if not can_publish_notices(user):
        return False
    if notice.trang_thai != "ban_nhap" or notice.bai_viet.da_xoa_mem:
        return False
    return (
        notice.nguoi_phu_trach_id == user.pk
        or user.has_perm("projectp.change_thongbaochinhthuc")
    )


def _active_user_ids(queryset=None):
    User = get_user_model()
    qs = queryset if queryset is not None else User.objects.filter(is_active=True)
    return set(qs.filter(is_active=True).values_list("pk", flat=True))


def _criterion_user_ids(criteria, *, distribution=False):
    """Tập người dùng khớp tiêu chí; distribution chỉ lấy thành viên thực tế."""
    result = set()
    User = get_user_model()
    for item in criteria:
        kind = item.loai_tieu_chi
        if kind == "phong_ban" and item.phong_ban_id:
            result.update(
                HoSoNhanVien.objects.filter(
                    phong_ban_id=item.phong_ban_id,
                    phong_ban__dang_hoat_dong=True,
                    nguoi_dung__is_active=True,
                ).values_list("nguoi_dung_id", flat=True)
            )
        elif kind == "cong_dong" and item.cong_dong_id:
            community = item.cong_dong
            members = ThanhVienCongDong.objects.filter(
                cong_dong_id=item.cong_dong_id,
                trang_thai=MemberStatus.ACTIVE,
                ket_thuc_luc__isnull=True,
                nguoi_dung__is_active=True,
                cong_dong__da_xoa_mem=False,
            )
            if community.loai_cong_dong == CongDong.Type.PROJECT:
                project_members = ThanhVienDuAn.objects.filter(
                    du_an__cong_dong=community,
                    trang_thai=MemberStatus.ACTIVE,
                    ket_thuc_luc__isnull=True,
                    nguoi_dung__is_active=True,
                ).values("nguoi_dung_id")
                members = members.filter(nguoi_dung_id__in=project_members)
            result.update(members.values_list("nguoi_dung_id", flat=True))
            # Quyền đọc cộng đồng nội bộ áp dụng cho toàn công ty theo quy tắc UC-SOC-02.
            if not distribution:
                if (
                    community.loai_cong_dong == CongDong.Type.GENERAL
                    and community.pham_vi_truy_cap == "noi_bo"
                    and not community.da_xoa_mem
                ):
                    result.update(_active_user_ids())
        elif kind == "du_an" and item.du_an_id:
            result.update(
                ThanhVienDuAn.objects.filter(
                    du_an_id=item.du_an_id,
                    trang_thai=MemberStatus.ACTIVE,
                    ket_thuc_luc__isnull=True,
                    nguoi_dung__is_active=True,
                    du_an__trang_thai__in=[DuAn.Status.ACTIVE, DuAn.Status.COMPLETED],
                ).values_list("nguoi_dung_id", flat=True)
            )
        elif kind == "nguoi_dung" and item.nguoi_dung_id:
            if User.objects.filter(pk=item.nguoi_dung_id, is_active=True).exists():
                result.add(item.nguoi_dung_id)
    return result


def resolve_scope_user_ids(*, scope, criteria, purpose):
    """Resolve current read or distribution audience from persisted criteria."""
    if scope == "toan_cong_ty":
        if purpose == "doc":
            return _active_user_ids()
        return set(
            HoSoNhanVien.objects.filter(nguoi_dung__is_active=True)
            .values_list("nguoi_dung_id", flat=True)
        )
    return _criterion_user_ids(criteria, distribution=(purpose == "phan_phoi"))


def can_read_notice(user, notice):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if notice.trang_thai != "da_cong_bo":
        return False
    post = notice.bai_viet
    if post.da_xoa_mem or post.trang_thai != "hien" or post.loai_bai_viet != post.Kind.ANNOUNCEMENT:
        return False
    criteria = list(notice.tieu_chi.filter(muc_dich="doc").select_related(
        "phong_ban", "cong_dong", "du_an", "nguoi_dung"
    ))
    allowed = resolve_scope_user_ids(
        scope=notice.che_do_doc,
        criteria=criteria,
        purpose="doc",
    )
    return user.pk in allowed
