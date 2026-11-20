"""Hàm dùng chung của phân hệ Cộng đồng: quyền trong 1 cộng đồng, nhật ký, sidebar."""

from contextlib import contextmanager
from functools import wraps
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, render
from projects.permissions import active_memberships, readable_projects
from django.utils import timezone

from accounts.views import can_doi_mat_khau, ho_ten  # noqa: F401 — re-export cho các file use case
from projectp.models import (
    BaiViet, CommunityRole, CongDong, DuAn, MemberStatus, NhatKyNghiepVu, ThanhVienCongDong, YeuCauThamGia,
)


logger = logging.getLogger(__name__)


def handled(view):
    """Hiển thị lỗi truy vấn/ghi để người dùng có thể tải lại theo đặc tả."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValidationError as error:
            return render(request, "communities/error.html", {
                "error_message": " ".join(error.messages), "retry_url": request.path,
            }, status=400)
        except DatabaseError:
            logger.exception("Chưa hoàn tất thao tác Cộng đồng")
            return render(request, "communities/error.html", {
                "error_message": "Chưa tải hoặc lưu được dữ liệu. Vui lòng tải lại và thử lại.",
                "retry_url": request.path,
            }, status=503)
    return wrapped


@contextmanager
def community_change(user, pk):
    """Giữ cùng thứ tự khóa với Dự án và kiểm tra lại trước mỗi lần ghi."""
    with transaction.atomic():
        DuAn.objects.filter(cong_dong_id=pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
        CongDong.objects.filter(pk=pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))
        if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists():
            raise PermissionDenied("Tài khoản không còn hoạt động.")
        yield lay_cong_dong(user, pk)


def active_community_memberships(user):
    if not user.is_authenticated or not user.is_active:
        return ThanhVienCongDong.objects.none()
    project_communities = readable_projects(user).values("cong_dong_id")
    return ThanhVienCongDong.objects.filter(
        nguoi_dung=user, nguoi_dung__is_active=True,
        trang_thai=MemberStatus.ACTIVE, ket_thuc_luc__isnull=True,
        cong_dong__da_xoa_mem=False,
    ).filter(Q(cong_dong__loai_cong_dong=CongDong.Type.GENERAL)
             | Q(cong_dong_id__in=project_communities))


def tu_cach(user, cong_dong):
    """Tư cách thành viên ĐANG HOẠT ĐỘNG của user trong đúng cộng đồng này (hoặc None)."""
    return active_community_memberships(user).filter(cong_dong=cong_dong).first()


def du_an_lien_ket(cong_dong):
    """Cộng đồng loại dự án gắn với 1 dự án; cộng đồng thường trả None."""
    return DuAn.objects.filter(cong_dong=cong_dong).first()


def community_posts(community):
    """Bài nằm đúng cộng đồng và đúng dự án liên kết, kể cả dữ liệu cũ chưa gắn dự án."""
    posts = BaiViet.objects.filter(cong_dong=community, da_xoa_mem=False)
    project = du_an_lien_ket(community)
    if community.loai_cong_dong == CongDong.Type.PROJECT:
        if project is None:
            return posts.none()
        return posts.filter(Q(du_an=project) | Q(du_an__isnull=True))
    return posts.filter(du_an__isnull=True)


def duoc_doc(cong_dong, tv):
    """Đọc bảng tin/thành viên: là thành viên; hoặc cộng đồng thường phạm vi 'Toàn công ty'."""
    if cong_dong.da_xoa_mem:
        return False
    if cong_dong.loai_cong_dong == CongDong.Type.PROJECT:
        project = du_an_lien_ket(cong_dong)
        return bool(tv and project and active_memberships(tv.nguoi_dung).filter(du_an=project).exists())
    if tv:
        return True
    return cong_dong.loai_cong_dong == CongDong.Type.GENERAL and cong_dong.pham_vi_truy_cap == "noi_bo"


def duoc_dang(cong_dong, tv):
    """Đăng bài: là thành viên, và dự án liên kết (nếu có) chưa lưu trữ."""
    du_an = du_an_lien_ket(cong_dong)
    if tv is None or cong_dong.da_xoa_mem:
        return False
    if cong_dong.loai_cong_dong == CongDong.Type.PROJECT:
        return bool(du_an and not du_an.da_luu_tru
                    and active_memberships(tv.nguoi_dung).filter(du_an=du_an).exists())
    return True


def la_quan_tri_noi_dung(tv):
    """Chủ sở hữu hoặc kiểm duyệt viên (tác nhân 'Quản trị nội dung cộng đồng')."""
    return bool(tv and tv.vai_tro in (CommunityRole.OWNER, CommunityRole.MODERATOR)
                and duoc_dang(tv.cong_dong, tv))


def la_chu_so_huu(tv):
    return tv is not None and tv.vai_tro == CommunityRole.OWNER


def ghi_nhat_ky(request, hanh_dong, loai, ma, truoc=None, sau=None, ly_do=""):
    """Ghi 1 dòng NHAT_KY_NGHIEP_VU: ai, làm gì, trên đối tượng nào, lúc nào."""
    NhatKyNghiepVu.objects.create(
        nguoi_dung=request.user, hanh_dong=hanh_dong, loai_tai_nguyen=loai, ma_tai_nguyen=str(ma),
        du_lieu_truoc=truoc, du_lieu_sau=sau, ly_do=ly_do, dia_chi_ip=request.META.get("REMOTE_ADDR"),
    )


def cong_dong_xem_duoc(user, *, include_project_introductions=False):
    """Chỉ Khám phá và Giới thiệu mở phạm vi công khai của cộng đồng dự án."""
    if not user.is_authenticated or not user.is_active:
        return CongDong.objects.none()
    cua_toi = active_community_memberships(user).values("cong_dong_id")
    visibility = Q(loai_cong_dong=CongDong.Type.GENERAL) | Q(pk__in=cua_toi)
    if include_project_introductions:
        visibility |= Q(loai_cong_dong=CongDong.Type.PROJECT, pham_vi_truy_cap="noi_bo",
                        du_an_lien_ket__isnull=False)
    return CongDong.objects.filter(da_xoa_mem=False).filter(visibility)


def lay_cong_dong(user, pk, *, include_project_introductions=False):
    """Lấy cộng đồng hoặc trả 404 nếu không tồn tại / không được thấy."""
    return get_object_or_404(cong_dong_xem_duoc(
        user, include_project_introductions=include_project_introductions,
    ), pk=pk)


KHOA_CD_GAN_NHAT = "cong_dong_gan_nhat"   # session: cộng đồng (đã tham gia) mở gần nhất


def cong_dong_cua_toi(request, cong_dong=None):
    """Xác định cộng đồng hiện tại hoặc cộng đồng đã truy cập gần nhất.

    1. Đang xem cộng đồng -> chính cộng đồng đó; ghi nhớ nếu có tư cách thành viên.
    2. Không thì cộng đồng mở gần nhất (lưu trong session), nếu vẫn còn là thành viên.
    3. Chưa mở cộng đồng nào -> cộng đồng tham gia sớm nhất.
    4. Chưa tham gia cộng đồng nào -> None (sidebar ẩn mục này và mục Thành viên).
    """
    cua_toi = active_community_memberships(request.user).select_related("cong_dong")
    if cong_dong is not None:
        if cua_toi.filter(cong_dong=cong_dong).exists():
            request.session[KHOA_CD_GAN_NHAT] = cong_dong.pk
        return cong_dong

    gan_nhat = cua_toi.filter(cong_dong_id=request.session.get(KHOA_CD_GAN_NHAT)).first()
    if gan_nhat is None:
        gan_nhat = cua_toi.order_by("ngay_tham_gia", "pk").first()
    return gan_nhat.cong_dong if gan_nhat else None


def sidebar(request, active, cong_dong=None):
    """Tạo điều hướng cộng đồng và các mục quản trị theo quyền của người dùng."""
    cua_toi = cong_dong_cua_toi(request, cong_dong)

    # Mục 2 / Thành viên chỉ tô đậm khi trang đang mở thuộc đúng cộng đồng của tôi
    if active in ("community", "members") and (cong_dong is None or cua_toi != cong_dong):
        active = ""

    # 'Kiểm duyệt cộng đồng' chỉ hiện cho Chủ sở hữu / Kiểm duyệt viên (GD-034: "Quản trị ... theo quyền")
    phu_trach = active_community_memberships(request.user).filter(
        vai_tro__in=[CommunityRole.OWNER, CommunityRole.MODERATOR],
    ).exclude(cong_dong__du_an_lien_ket__trang_thai=DuAn.Status.ARCHIVED)
    # Đang ở trong cộng đồng mình phụ trách -> vào thẳng trang kiểm duyệt của cộng đồng đó
    kiem_duyet_tai = cong_dong.pk if cong_dong is not None and phu_trach.filter(cong_dong=cong_dong).exists() else None

    # Cùng điều kiện với trang Yêu cầu tham gia (join_requests) để số trên badge khớp danh sách
    so_huu = active_community_memberships(request.user).filter(
        vai_tro=CommunityRole.OWNER, cong_dong__loai_cong_dong=CongDong.Type.GENERAL,
    ).values("cong_dong_id")
    cho = YeuCauThamGia.objects.filter(cong_dong_id__in=so_huu, trang_thai=YeuCauThamGia.Status.PENDING).count()

    return {
        "active_side": active,
        "side_community": cua_toi,
        "side_can_moderate": phu_trach.exists(),
        "side_moderation_pk": kiem_duyet_tai,
        "side_pending": cho,
    }


def kich_hoat_thanh_vien(cong_dong, user):
    """Tạo mới tư cách thành viên, hoặc mở lại dòng cũ nếu người này từng rời
    (bảng chỉ cho mỗi người 1 dòng trong 1 cộng đồng)."""
    tv = ThanhVienCongDong.objects.filter(cong_dong=cong_dong, nguoi_dung=user).first()
    if tv is None:
        return ThanhVienCongDong.objects.create(cong_dong=cong_dong, nguoi_dung=user)
    tv.trang_thai = MemberStatus.ACTIVE
    tv.vai_tro = CommunityRole.MEMBER
    tv.ngay_tham_gia = timezone.now()
    tv.ket_thuc_luc = None
    tv.save()
    return tv
