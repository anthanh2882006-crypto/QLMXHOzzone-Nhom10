"""OZZONE: 35 model nghiệp vụ trong phạm vi 40 UC."""

from functools import reduce
from operator import or_
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


USER = settings.AUTH_USER_MODEL

# Quy tắc trạng thái phải đi cùng thời điểm kết thúc thực tế.
# Trạng thái tạm dừng chưa đồng nghĩa đã kết thúc tư cách thành viên.
MEMBERSHIP_LIFECYCLE = (
    Q(trang_thai="da_roi", ket_thuc_luc__isnull=False)
    | Q(trang_thai__in=["hoat_dong", "tam_dung"], ket_thuc_luc__isnull=True)
)


def exactly_one(*fields):
    """Điều kiện SQL: đúng một FK có giá trị."""
    return reduce(or_, [Q(**{f"{f}__isnull": f != chosen for f in fields}) for chosen in fields])


def related(instance, field):
    if getattr(instance, f"{field}_id", None) is None:
        return None
    try:
        return getattr(instance, field)
    except ObjectDoesNotExist:
        return None  # full_clean() báo FK không tồn tại ở bước validate_fields.


def same_project(assignment, project_id):
    return assignment is not None and assignment.du_an_id == project_id


class TimeStamped(models.Model):
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleted(TimeStamped):
    da_xoa_mem = models.BooleanField(default=False, db_column="da_xoa")
    ngay_xoa = models.DateTimeField(null=True, blank=True)
    nguoi_xoa = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_xoa',
    )

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.da_xoa_mem and not self.ngay_xoa:
            raise ValidationError({"ngay_xoa": "Cần thời điểm xóa mềm."})
        if not self.da_xoa_mem and (self.ngay_xoa or self.nguoi_xoa_id):
            raise ValidationError("Đối tượng chưa xóa không có thời điểm/người xóa.")


class MemberStatus(models.TextChoices):
    ACTIVE = "hoat_dong", "Hoạt động"
    ENDED = "da_roi", "Đã kết thúc tư cách"
    SUSPENDED = "tam_dung", "Tạm dừng"


class CommunityRole(models.TextChoices):
    OWNER = "chu_so_huu", "Chủ sở hữu (OWNER)"
    MODERATOR = "kiem_duyet_vien", "Kiểm duyệt viên"
    MEMBER = "thanh_vien", "Thành viên"


class ProjectRole(models.TextChoices):
    MANAGER = "quan_ly", "Quản lý dự án (MANAGER)"
    MEMBER = "thanh_vien", "Thành viên"


class SharingScope(models.TextChoices):
    COMPANY = "noi_bo", "Toàn công ty"
    COMMUNITY = "cong_dong", "Cộng đồng"
    PROJECT = "du_an", "Dự án"


class KnowledgeAdminStatus(models.TextChoices):
    """UC-KNW-06, trang 202–203: quản trị khả năng hiển thị, không đổi bản công bố."""
    VISIBLE = "hien_thi", "Hiển thị"
    HIDDEN = "an", "Ẩn"
    ARCHIVED = "luu_tru", "Lưu trữ"


# 1. TÀI KHOẢN NỀN TẢNG, HỒ SƠ VÀ DANH MỤC NHÂN SỰ
# Django quản lý User; OZZONE chỉ bổ sung hồ sơ và thông tin tổ chức.

class PhongBan(TimeStamped):
    ma_phong_ban = models.BigAutoField(primary_key=True)
    ma_nghiep_vu = models.CharField(max_length=50, unique=True)
    ten_phong_ban = models.CharField(max_length=200)
    mo_ta = models.TextField(blank=True)
    dang_hoat_dong = models.BooleanField(default=True)

    class Meta:
        db_table = "PHONG_BAN"

    def __str__(self):
        return self.ten_phong_ban


class ViTriCongViec(TimeStamped):
    ma_vi_tri = models.BigAutoField(primary_key=True)
    ma_nghiep_vu = models.CharField(max_length=50, unique=True)
    ten_vi_tri = models.CharField(max_length=200)
    mo_ta = models.TextField(blank=True)
    dang_hoat_dong = models.BooleanField(default=True)

    class Meta:
        db_table = "VI_TRI_CONG_VIEC"

    def __str__(self):
        return self.ten_vi_tri


class HoSoNhanVien(TimeStamped):
    ma_ho_so = models.BigAutoField(primary_key=True)
    nguoi_dung = models.OneToOneField(
        USER,
        on_delete=models.PROTECT,
        related_name='ho_so_nhan_vien',
        db_column='ma_nguoi_dung',
    )
    phong_ban = models.ForeignKey(PhongBan, on_delete=models.PROTECT, db_column="ma_phong_ban")
    vi_tri = models.ForeignKey(ViTriCongViec, on_delete=models.PROTECT, db_column="ma_vi_tri")
    ma_nhan_vien = models.CharField(max_length=50, unique=True)
    anh_dai_dien = models.ImageField(upload_to="ozzone/ho_so/", max_length=500, blank=True)
    so_dien_thoai = models.CharField(max_length=30, blank=True)
    gioi_thieu = models.TextField(blank=True)
    bat_buoc_doi_mat_khau = models.BooleanField(default=True)

    class Meta:
        db_table = "HO_SO_NHAN_VIEN"

    def __str__(self):
        return self.ma_nhan_vien


class KyNang(TimeStamped):
    ma_ky_nang = models.BigAutoField(primary_key=True)
    ten_ky_nang = models.CharField(max_length=150, unique=True)
    mo_ta = models.TextField(blank=True)

    class Meta:
        db_table = "KY_NANG"

    def __str__(self):
        return self.ten_ky_nang


class KyNangNhanVien(TimeStamped):
    ma_ky_nang_nhan_vien = models.BigAutoField(primary_key=True)
    ho_so = models.ForeignKey(HoSoNhanVien, on_delete=models.CASCADE, db_column="ma_ho_so")
    ky_nang = models.ForeignKey(KyNang, on_delete=models.PROTECT, db_column="ma_ky_nang")
    mo_ta_kinh_nghiem = models.TextField(blank=True)

    class Meta:
        db_table = "KY_NANG_NHAN_VIEN"
        constraints = [models.UniqueConstraint(fields=['ho_so', 'ky_nang'], name='uq_nhan_vien_ky_nang')]

    def __str__(self):
        return f"Hồ sơ {self.ho_so_id} — Kỹ năng {self.ky_nang_id}"


# 2. CỘNG ĐỒNG VÀ VAI TRÒ TRONG TỪNG CỘNG ĐỒNG

class CongDong(SoftDeleted):
    class Type(models.TextChoices):
        GENERAL = "chung", "Thông thường"
        PROJECT = "du_an", "Cộng đồng dự án"

    class JoinRule(models.TextChoices):
        OPEN = "truc_tiep", "Tham gia trực tiếp"
        APPROVAL = "cho_duyet", "Cần duyệt yêu cầu"
        PROJECT_MANAGED = "theo_du_an", "Quản lý qua thành viên dự án"

    ma_cong_dong = models.BigAutoField(primary_key=True)
    ten_cong_dong = models.CharField(max_length=200)
    mo_ta = models.TextField(blank=True)
    loai_cong_dong = models.CharField(max_length=30, choices=Type.choices, default=Type.GENERAL)
    pham_vi_truy_cap = models.CharField(
        max_length=30,
        choices=[('noi_bo', 'Toàn công ty'), ('thanh_vien', 'Chỉ thành viên')],
        default='noi_bo',
    )
    quy_tac_tham_gia = models.CharField(max_length=30, choices=JoinRule.choices, default=JoinRule.APPROVAL)
    nguoi_tao = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_tao')

    class Meta:
        db_table = "CONG_DONG"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(loai_cong_dong='du_an', quy_tac_tham_gia='theo_du_an')
                    | Q(loai_cong_dong='chung') & ~Q(quy_tac_tham_gia='theo_du_an')
                ),
                name='ck_com_join_rule',
            ),
        ]

    def __str__(self):
        return self.ten_cong_dong


class ThanhVienCongDong(TimeStamped):
    ma_thanh_vien = models.BigAutoField(primary_key=True)
    cong_dong = models.ForeignKey(
        CongDong,
        on_delete=models.PROTECT,
        related_name='thanh_vien',
        db_column='ma_cong_dong',
    )
    nguoi_dung = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='ma_nguoi_dung')
    vai_tro = models.CharField(max_length=30, choices=CommunityRole.choices, default=CommunityRole.MEMBER)
    trang_thai = models.CharField(max_length=30, choices=MemberStatus.choices, default=MemberStatus.ACTIVE)
    ngay_tham_gia = models.DateTimeField(default=timezone.now, db_column="tham_gia_luc")
    ket_thuc_luc = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "THANH_VIEN_CONG_DONG"
        constraints = [
            models.UniqueConstraint(fields=['cong_dong', 'nguoi_dung'], name='uq_tv_cong_dong'),
            models.CheckConstraint(
                condition=Q(vai_tro__in=CommunityRole.values),
                name='ck_tv_com_role',
            ),
            models.CheckConstraint(condition=MEMBERSHIP_LIFECYCLE, name='ck_tv_com_lifecycle'),
            models.CheckConstraint(
                condition=Q(ket_thuc_luc__isnull=True) | Q(ket_thuc_luc__gte=F('ngay_tham_gia')),
                name='ck_tv_com_dates',
            ),
        ]

    def __str__(self):
        return f"Người dùng {self.nguoi_dung_id} — Cộng đồng {self.cong_dong_id}: {self.get_vai_tro_display()}"


class YeuCauThamGia(TimeStamped):
    class Status(models.TextChoices):
        PENDING = "cho_duyet", "Chờ duyệt"
        ACCEPTED = "da_duyet", "Đã duyệt"
        REJECTED = "da_tu_choi", "Đã từ chối"
        CANCELLED = "da_huy", "Đã hủy"

    ma_yeu_cau = models.BigAutoField(primary_key=True)
    cong_dong = models.ForeignKey(CongDong, on_delete=models.PROTECT, db_column="ma_cong_dong")
    nguoi_dung = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='ma_nguoi_dung')
    loi_nhan = models.TextField(blank=True)
    trang_thai = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    nguoi_xu_ly = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_xu_ly',
    )
    ngay_xu_ly = models.DateTimeField(null=True, blank=True, db_column="xu_ly_luc")
    ly_do_xu_ly = models.TextField(blank=True)

    class Meta:
        db_table = "YEU_CAU_THAM_GIA"
        constraints = [
            models.UniqueConstraint(
                fields=['cong_dong', 'nguoi_dung'],
                condition=Q(trang_thai='cho_duyet'),
                name='uq_join_pending',
            ),
            models.CheckConstraint(
                condition=(
                    Q(trang_thai='cho_duyet', ngay_xu_ly__isnull=True, nguoi_xu_ly__isnull=True)
                    | Q(
                        trang_thai__in=['da_duyet', 'da_tu_choi', 'da_huy'],
                        ngay_xu_ly__isnull=False,
                        nguoi_xu_ly__isnull=False,
                    )
                ),
                name='ck_join_decision',
            ),
        ]

    def clean(self):
        super().clean()
        community = related(self, "cong_dong")
        if community and community.loai_cong_dong == CongDong.Type.PROJECT:
            raise ValidationError({"cong_dong": "Cộng đồng dự án quản lý tư cách qua dự án."})

    def __str__(self):
        return f"Yêu cầu #{self.pk or 'mới'} — {self.get_trang_thai_display()}"


# 3. DỰ ÁN, THÀNH VIÊN, THIẾT BỊ VÀ PHÂN CÔNG TRI THỨC

class DuAn(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "dang_thuc_hien", "Đang thực hiện"
        COMPLETED = "hoan_thanh", "Hoàn thành"
        ARCHIVED = "luu_tru", "Lưu trữ"

    ma_du_an = models.BigAutoField(primary_key=True)
    ma_du_an_nghiep_vu = models.CharField(max_length=50, unique=True)
    ten_du_an = models.CharField(max_length=200)
    mo_ta = models.TextField(blank=True)
    cong_dong = models.OneToOneField(
        CongDong,
        on_delete=models.PROTECT,
        related_name='du_an_lien_ket',
        db_column='ma_cong_dong',
    )
    nguoi_tao = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_tao')
    trang_thai = models.CharField(max_length=30, choices=Status.choices, default=Status.ACTIVE)
    ngay_bat_dau = models.DateField()
    ngay_ket_thuc = models.DateField(null=True, blank=True)
    luu_tru_luc = models.DateTimeField(null=True, blank=True)
    nguoi_luu_tru = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_luu_tru',
    )

    class Meta:
        db_table = "DU_AN"
        constraints = [
            models.CheckConstraint(
                condition=Q(ngay_ket_thuc__isnull=True) | Q(ngay_ket_thuc__gte=F('ngay_bat_dau')),
                name='ck_prj_dates',
            ),
            models.CheckConstraint(
                condition=(
                    Q(trang_thai='luu_tru', luu_tru_luc__isnull=False, nguoi_luu_tru__isnull=False)
                    | (
                        ~Q(trang_thai='luu_tru')
                        & Q(luu_tru_luc__isnull=True, nguoi_luu_tru__isnull=True)
                    )
                ),
                name='ck_prj_archive',
            ),
        ]

    def clean(self):
        super().clean()
        community = related(self, "cong_dong")
        if community and community.loai_cong_dong != CongDong.Type.PROJECT:
            raise ValidationError({"cong_dong": "Dự án phải liên kết cộng đồng loại dự án."})

    def __str__(self):
        return f"{self.ma_du_an_nghiep_vu} — {self.ten_du_an}"

    @property
    def da_luu_tru(self):
        """Suy ra từ trạng thái, không lưu thêm cột trùng thông tin."""
        return self.trang_thai == self.Status.ARCHIVED


class ThanhVienDuAn(TimeStamped):
    ma_thanh_vien = models.BigAutoField(primary_key=True)
    du_an = models.ForeignKey(
        DuAn,
        on_delete=models.PROTECT,
        related_name='thanh_vien',
        db_column='ma_du_an',
    )
    nguoi_dung = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='ma_nguoi_dung')
    vai_tro = models.CharField(max_length=30, choices=ProjectRole.choices, default=ProjectRole.MEMBER)
    trang_thai = models.CharField(max_length=30, choices=MemberStatus.choices, default=MemberStatus.ACTIVE)
    ngay_tham_gia = models.DateTimeField(default=timezone.now, db_column="tham_gia_luc")
    ket_thuc_luc = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "THANH_VIEN_DU_AN"
        constraints = [
            models.UniqueConstraint(fields=['du_an', 'nguoi_dung'], name='uq_tv_du_an'),
            models.CheckConstraint(
                condition=Q(vai_tro__in=ProjectRole.values),
                name='ck_tv_prj_role',
            ),
            models.CheckConstraint(condition=MEMBERSHIP_LIFECYCLE, name='ck_tv_prj_lifecycle'),
            models.CheckConstraint(
                condition=Q(ket_thuc_luc__isnull=True) | Q(ket_thuc_luc__gte=F('ngay_tham_gia')),
                name='ck_tv_prj_dates',
            ),
        ]

    def __str__(self):
        return f"Người dùng {self.nguoi_dung_id} — Dự án {self.du_an_id}: {self.get_vai_tro_display()}"


class MaThietBi(TimeStamped):
    ma_the_thiet_bi = models.BigAutoField(primary_key=True)
    du_an = models.ForeignKey(DuAn, on_delete=models.PROTECT, db_column="ma_du_an")
    ma_thiet_bi = models.CharField(max_length=100)
    ten_thiet_bi = models.CharField(max_length=200)
    mo_ta = models.TextField(blank=True)
    dang_su_dung = models.BooleanField(default=True)

    class Meta:
        db_table = "MA_THIET_BI"
        constraints = [models.UniqueConstraint(fields=['du_an', 'ma_thiet_bi'], name='uq_ma_thiet_bi_du_an')]

    def __str__(self):
        return self.ma_thiet_bi


class TaiSanThietBi(TimeStamped):
    ma_tai_san = models.BigAutoField(primary_key=True)
    ma_the_thiet_bi = models.ForeignKey(MaThietBi, on_delete=models.PROTECT, db_column='ma_the_thiet_bi')
    ma_tai_san_noi_bo = models.CharField(max_length=100, unique=True, db_column='ma_tai_san_nghiep_vu')
    so_serial = models.CharField(max_length=150, blank=True)
    trang_thai = models.CharField(
        max_length=30,
        choices=[('dang_su_dung', 'Đang sử dụng'), ('ngung_su_dung', 'Ngừng sử dụng')],
        default='dang_su_dung',
    )
    ngay_bat_dau_su_dung = models.DateField(default=timezone.localdate)
    ngay_ket_thuc_su_dung = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "TAI_SAN_THIET_BI"
        constraints = [
            models.UniqueConstraint(
                fields=['ma_the_thiet_bi'],
                condition=Q(trang_thai='dang_su_dung'),
                name='uq_asset_active',
            ),
            models.CheckConstraint(
                condition=(
                    Q(ngay_ket_thuc_su_dung__isnull=True)
                    | Q(ngay_ket_thuc_su_dung__gte=F('ngay_bat_dau_su_dung'))
                ),
                name='ck_asset_dates',
            ),
            models.CheckConstraint(
                condition=(
                    Q(trang_thai='dang_su_dung', ngay_ket_thuc_su_dung__isnull=True)
                    | Q(trang_thai='ngung_su_dung', ngay_ket_thuc_su_dung__isnull=False)
                ),
                name='ck_asset_lifecycle',
            ),
        ]

    def __str__(self):
        return self.ma_tai_san_noi_bo


class PhanCongTriThuc(TimeStamped):
    ma_phan_cong = models.BigAutoField(primary_key=True)
    du_an = models.ForeignKey(DuAn, on_delete=models.PROTECT, db_column="ma_du_an")
    nguoi_phu_trach = models.ForeignKey(
        USER,
        on_delete=models.PROTECT,
        related_name='nhiem_vu_tri_thuc',
        db_column='ma_nguoi_dung',
    )
    nguoi_phan_cong = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_phan_cong')
    ngay_phan_cong = models.DateTimeField(default=timezone.now, db_column="bat_dau_luc")
    ket_thuc_luc = models.DateTimeField(null=True, blank=True)
    nguoi_ket_thuc = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_ket_thuc',
    )
    ghi_chu = models.TextField(blank=True, db_column="ly_do")

    class Meta:
        db_table = "PHAN_CONG_TRI_THUC"
        constraints = [
            models.UniqueConstraint(
                fields=['du_an'],
                condition=Q(ket_thuc_luc__isnull=True),
                name='uq_curator_project_active',
            ),
            models.CheckConstraint(
                condition=Q(ket_thuc_luc__isnull=True) | Q(ket_thuc_luc__gte=F('ngay_phan_cong')),
                name='ck_curator_dates',
            ),
            models.CheckConstraint(
                condition=(
                    Q(ket_thuc_luc__isnull=True, nguoi_ket_thuc__isnull=True)
                    | Q(ket_thuc_luc__isnull=False, nguoi_ket_thuc__isnull=False)
                ),
                name='ck_curator_end_actor',
            ),
        ]

    def __str__(self):
        return f"Dự án {self.du_an_id} — Phụ trách {self.nguoi_phu_trach_id}"


# 4. NỘI DUNG XÃ HỘI, TƯƠNG TÁC VÀ THÔNG BÁO CHÍNH THỨC

class BaiViet(SoftDeleted):
    class Kind(models.TextChoices):
        STANDARD = "chia_se", "Chia sẻ/thảo luận"
        FIELD_UPDATE = "cap_nhat_hien_truong", "Cập nhật hiện trường"
        ANNOUNCEMENT = "thong_bao", "Thông báo chính thức"

    class TechnicalStatus(models.TextChoices):
        NONE = "khong_ap_dung", "Không áp dụng"
        OPEN = "chua_giai_quyet", "Chưa giải quyết"
        RESOLVED = "da_giai_quyet", "Đã giải quyết"

    ma_bai_viet = models.BigAutoField(primary_key=True)
    nguoi_dang = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_dang')
    cong_dong = models.ForeignKey(
        CongDong,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_cong_dong',
    )
    du_an = models.ForeignKey(DuAn, null=True, blank=True, on_delete=models.PROTECT, db_column='ma_du_an')
    ma_the_thiet_bi = models.ForeignKey(
        MaThietBi,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_the_thiet_bi',
    )
    tai_san = models.ForeignKey(
        TaiSanThietBi,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_tai_san',
    )
    loai_bai_viet = models.CharField(max_length=50, choices=Kind.choices, default=Kind.STANDARD)
    che_do_xu_ly = models.BooleanField(default=False)
    tieu_de = models.CharField(max_length=250, blank=True)
    noi_dung = models.TextField()
    trang_thai = models.CharField(max_length=30, choices=[('hien', 'Hiển thị'), ('an', 'Đã ẩn')], default='hien')
    trang_thai_xu_ly = models.CharField(max_length=30, choices=TechnicalStatus.choices, default=TechnicalStatus.NONE)
    ly_do_chua_giai_quyet = models.TextField(blank=True)
    chua_giai_quyet_luc = models.DateTimeField(null=True, blank=True)
    giai_quyet_boi = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='giai_quyet_boi',
    )
    giai_quyet_luc = models.DateTimeField(null=True, blank=True)
    phien_ban_noi_dung = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    # UC-COM-07: ghim bài trong cộng đồng; không phải ghim riêng theo cá nhân.
    da_ghim = models.BooleanField(default=False)
    ghim_luc = models.DateTimeField(null=True, blank=True)
    nguoi_ghim = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_ghim',
    )

    class Meta:
        db_table = "BAI_VIET"
        ordering = ["-ngay_tao", "-ma_bai_viet"]
        indexes = [
            models.Index(fields=['du_an', 'trang_thai_xu_ly']),
            models.Index(fields=['cong_dong', 'ngay_tao']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(da_ghim=False, ghim_luc__isnull=True, nguoi_ghim__isnull=True)
                    | Q(
                        da_ghim=True,
                        cong_dong__isnull=False,
                        ghim_luc__isnull=False,
                        nguoi_ghim__isnull=False,
                    )
                ),
                name='ck_post_pin',
            ),
            models.CheckConstraint(
                condition=Q(phien_ban_noi_dung__gte=1),
                name='ck_post_content_version',
            ),
            models.CheckConstraint(
                condition=(
                    (
                        Q(
                            che_do_xu_ly=False,
                            trang_thai_xu_ly='khong_ap_dung',
                            chua_giai_quyet_luc__isnull=True,
                            giai_quyet_luc__isnull=True,
                            giai_quyet_boi__isnull=True,
                        )
                        | Q(
                            che_do_xu_ly=True,
                            du_an__isnull=False,
                            trang_thai_xu_ly='chua_giai_quyet',
                            chua_giai_quyet_luc__isnull=False,
                            giai_quyet_luc__isnull=True,
                            giai_quyet_boi__isnull=True,
                        )
                    )
                    | Q(
                        che_do_xu_ly=True,
                        du_an__isnull=False,
                        trang_thai_xu_ly='da_giai_quyet',
                        giai_quyet_luc__isnull=False,
                        giai_quyet_boi__isnull=False,
                    )
                ),
                name='ck_post_technical_state',
            ),
        ]

    def clean(self):
        super().clean()
        project, device, asset = related(self, "du_an"), related(self, "ma_the_thiet_bi"), related(self, "tai_san")
        errors = {}
        if project and self.cong_dong_id and project.cong_dong_id != self.cong_dong_id:
            errors["cong_dong"] = "Cộng đồng không khớp dự án."
        if device and device.du_an_id != self.du_an_id:
            errors["ma_the_thiet_bi"] = "Mã thiết bị phải thuộc đúng dự án."
        if asset and asset.ma_the_thiet_bi_id != self.ma_the_thiet_bi_id:
            errors["tai_san"] = "Tài sản không khớp mã thiết bị."
        if self.loai_bai_viet == self.Kind.FIELD_UPDATE and not (self.du_an_id and self.ma_the_thiet_bi_id):
            errors["loai_bai_viet"] = "Cập nhật hiện trường cần dự án và mã thiết bị."
        if self.che_do_xu_ly:
            if not self.du_an_id or self.trang_thai_xu_ly == self.TechnicalStatus.NONE:
                errors["trang_thai_xu_ly"] = "Vấn đề kỹ thuật cần dự án và trạng thái xử lý."
        elif self.trang_thai_xu_ly != self.TechnicalStatus.NONE:
            errors["trang_thai_xu_ly"] = "Bài thông thường không có trạng thái kỹ thuật."
        if self.che_do_xu_ly and self.loai_bai_viet == self.Kind.ANNOUNCEMENT:
            errors["che_do_xu_ly"] = "Thông báo chính thức không phải vấn đề kỹ thuật."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.tieu_de or (self.noi_dung or "")[:60] or f"Bài viết #{self.pk or 'mới'}"


class BinhLuan(SoftDeleted):
    ma_binh_luan = models.BigAutoField(primary_key=True)
    bai_viet = models.ForeignKey(BaiViet, on_delete=models.PROTECT, db_column="ma_bai_viet")
    nguoi_dung = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_viet')
    binh_luan_cha = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_binh_luan_cha',
    )
    noi_dung = models.TextField()

    class Meta:
        db_table = "BINH_LUAN"

    def clean(self):
        super().clean()
        parent = related(self, "binh_luan_cha")
        seen = {self.pk} if self.pk else set()
        while parent:
            if parent.pk in seen:
                raise ValidationError({"binh_luan_cha": "Không được tạo chu kỳ bình luận."})
            seen.add(parent.pk)
            if parent.bai_viet_id != self.bai_viet_id:
                raise ValidationError({"binh_luan_cha": "Bình luận cha phải thuộc cùng bài."})
            parent = related(parent, "binh_luan_cha")

    def __str__(self):
        return (self.noi_dung or "")[:60] or f"Bình luận #{self.pk or 'mới'}"


class CamXuc(TimeStamped):
    ma_cam_xuc = models.BigAutoField(primary_key=True)
    bai_viet = models.ForeignKey(BaiViet, on_delete=models.CASCADE, db_column="ma_bai_viet")
    nguoi_dung = models.ForeignKey(USER, on_delete=models.CASCADE, related_name='+', db_column='ma_nguoi_dung')
    loai_cam_xuc = models.CharField(
        max_length=30,
        choices=[
            ('thich', 'Thích'),
            ('yeu_thich', 'Yêu thích'),
            ('cam_on', 'Cảm ơn'),
            ('ngac_nhien', 'Ngạc nhiên'),
        ],
        default='thich',
    )

    class Meta:
        db_table = "CAM_XUC"
        constraints = [models.UniqueConstraint(fields=['bai_viet', 'nguoi_dung'], name='uq_cam_xuc_bai_viet')]

    def __str__(self):
        return f"{self.get_loai_cam_xuc_display()} — Bài {self.bai_viet_id} — Người {self.nguoi_dung_id}"


class BaiVietDaLuu(TimeStamped):
    ma_bai_viet_da_luu = models.BigAutoField(primary_key=True, db_column="ma_luu")
    bai_viet = models.ForeignKey(
        BaiViet,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        db_column='ma_bai_viet',
    )
    bai_hoc = models.ForeignKey(
        'BaiHocKinhNghiem',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        db_column='ma_bai_hoc',
    )
    bai_viet_tri_thuc = models.ForeignKey(
        'BaiVietTriThuc',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        db_column='ma_bai_tri_thuc',
    )
    nguoi_dung = models.ForeignKey(USER, on_delete=models.CASCADE, related_name='+', db_column='ma_nguoi_dung')
    ngay_luu = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "BAI_VIET_DA_LUU"
        constraints = [
            models.CheckConstraint(
                condition=exactly_one('bai_viet', 'bai_hoc', 'bai_viet_tri_thuc'),
                name='ck_saved_one_target',
            ),
            models.UniqueConstraint(fields=['bai_viet', 'nguoi_dung'], name='uq_bai_viet_da_luu'),
            models.UniqueConstraint(fields=['bai_hoc', 'nguoi_dung'], name='uq_saved_lesson'),
            models.UniqueConstraint(
                fields=['bai_viet_tri_thuc', 'nguoi_dung'],
                name='uq_saved_article',
            ),
        ]

    def __str__(self):
        return f"Mục lưu #{self.pk or 'mới'} — Người {self.nguoi_dung_id}"


class ThongBaoChinhThuc(TimeStamped):
    # Bảng mở rộng dùng chung PK với bài viết, đúng ERD trang 221/233.
    bai_viet = models.OneToOneField(
        BaiViet,
        primary_key=True,
        db_column='ma_bai_viet',
        on_delete=models.PROTECT,
        related_name='thong_bao_chinh_thuc',
    )
    nguoi_phu_trach = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_phu_trach')
    nguoi_xuat_ban = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_xuat_ban',
    )
    che_do_doc = models.CharField(
        max_length=30,
        choices=[('toan_cong_ty', 'Toàn công ty'), ('theo_tieu_chi', 'Theo tiêu chí')],
        default='toan_cong_ty',
    )
    che_do_phan_phoi = models.CharField(
        max_length=30,
        choices=[('toan_cong_ty', 'Toàn công ty'), ('theo_tieu_chi', 'Theo tiêu chí')],
        default='toan_cong_ty',
    )
    yeu_cau_xac_nhan = models.BooleanField(default=False)
    ngay_xuat_ban = models.DateTimeField(null=True, blank=True, db_column="xuat_ban_luc")
    trang_thai = models.CharField(
        max_length=30,
        choices=[('ban_nhap', 'Bản nháp'), ('da_cong_bo', 'Đã công bố')],
        default='ban_nhap',
    )
    phien_ban_cau_hinh = models.PositiveIntegerField(default=1)
    kiem_tra_luc = models.DateTimeField(null=True, blank=True)
    khoa_yeu_cau_xuat_ban = models.UUIDField(null=True, blank=True, unique=True)
    thong_bao_tham_chieu = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="thong_bao_dinh_chinh",
        db_column="ma_thong_bao_tham_chieu",
    )

    class Meta:
        db_table = "THONG_BAO_CHINH_THUC"
        permissions = [
            ('cong_bo_thong_bao', 'Được công bố thông báo chính thức'),
            ('theo_doi_tiep_nhan', 'Được theo dõi tiếp nhận thông báo'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(trang_thai='ban_nhap')
                    | Q(
                        trang_thai='da_cong_bo',
                        nguoi_xuat_ban__isnull=False,
                        ngay_xuat_ban__isnull=False,
                        kiem_tra_luc__isnull=False,
                        khoa_yeu_cau_xuat_ban__isnull=False,
                    )
                ),
                name='ck_announcement_publish',
            ),
            models.CheckConstraint(
                condition=Q(phien_ban_cau_hinh__gte=1),
                name='ck_ann_config_version',
            ),
        ]

    def clean(self):
        super().clean()
        post = related(self, "bai_viet")
        if post and (post.loai_bai_viet != BaiViet.Kind.ANNOUNCEMENT or post.du_an_id or post.cong_dong_id):
            raise ValidationError({"bai_viet": "Cần bài loại thông báo chính thức ở phạm vi công ty."})
        reference = related(self, "thong_bao_tham_chieu")
        if reference:
            if self.pk and reference.pk == self.pk:
                raise ValidationError({
                    "thong_bao_tham_chieu": "Không thể đính chính chính thông báo này."
                })
            if reference.trang_thai != "da_cong_bo":
                raise ValidationError({
                    "thong_bao_tham_chieu": "Chỉ được tham chiếu thông báo đã công bố."
                })
    def __str__(self):
        return f"Thông báo của bài #{self.bai_viet_id}"


class TieuChiThongBao(TimeStamped):
    ma_tieu_chi = models.BigAutoField(primary_key=True)
    thong_bao = models.ForeignKey(
        ThongBaoChinhThuc,
        on_delete=models.PROTECT,
        related_name='tieu_chi',
        db_column='ma_thong_bao',
    )
    ten_tieu_chi = models.CharField(max_length=150, blank=True)
    muc_dich = models.CharField(max_length=20, choices=[('doc', 'Quyền đọc'), ('phan_phoi', 'Phân phối')])
    loai_tieu_chi = models.CharField(
        max_length=30,
        choices=[
            ('phong_ban', 'Phòng ban'),
            ('cong_dong', 'Cộng đồng'),
            ('du_an', 'Dự án'),
            ('nguoi_dung', 'Người dùng'),
        ],
        db_column='loai_doi_tuong',
    )
    phong_ban = models.ForeignKey(
        PhongBan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_phong_ban',
    )
    cong_dong = models.ForeignKey(
        CongDong,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_cong_dong',
    )
    du_an = models.ForeignKey(DuAn, null=True, blank=True, on_delete=models.PROTECT, db_column='ma_du_an')
    nguoi_dung = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='ma_nguoi_dung',
    )

    class Meta:
        db_table = "TIEU_CHI_THONG_BAO"
        constraints = [
            models.CheckConstraint(
                condition=exactly_one('phong_ban', 'cong_dong', 'du_an', 'nguoi_dung'),
                name='ck_ann_criterion_target',
            ),
        ]

    def clean(self):
        super().clean()
        if self.loai_tieu_chi in {"phong_ban", "cong_dong", "du_an", "nguoi_dung"} and not getattr(self, f"{self.loai_tieu_chi}_id"):
            raise ValidationError({"loai_tieu_chi": "Đối tượng không khớp loại tiêu chí."})

    def __str__(self):
        return f"{self.get_muc_dich_display()} — {self.get_loai_tieu_chi_display()}"


class NguoiNhanThongBao(TimeStamped):
    ma_nguoi_nhan = models.BigAutoField(primary_key=True)
    thong_bao = models.ForeignKey(
        ThongBaoChinhThuc,
        on_delete=models.PROTECT,
        related_name='nguoi_nhan',
        db_column='ma_thong_bao',
    )
    nguoi_dung = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='ma_nguoi_dung')
    ngay_phan_phoi = models.DateTimeField(default=timezone.now, db_column="duoc_phan_phoi_luc")
    bat_buoc_xac_nhan = models.BooleanField(default=False)
    ngay_xac_nhan = models.DateTimeField(null=True, blank=True, db_column="xac_nhan_luc")
    trang_thai_tiep_nhan = models.CharField(
        max_length=30,
        choices=[('chua_xac_nhan', 'Chưa xác nhận'), ('da_xac_nhan', 'Đã xác nhận')],
        default='chua_xac_nhan',
    )

    class Meta:
        db_table = "NGUOI_NHAN_THONG_BAO"
        constraints = [
            models.UniqueConstraint(
                fields=['thong_bao', 'nguoi_dung'],
                name='uq_nguoi_nhan_thong_bao',
            ),
            models.CheckConstraint(
                condition=(
                    Q(trang_thai_tiep_nhan='chua_xac_nhan', ngay_xac_nhan__isnull=True)
                    | Q(
                        trang_thai_tiep_nhan='da_xac_nhan',
                        ngay_xac_nhan__isnull=False,
                        bat_buoc_xac_nhan=True,
                    )
                ),
                name='ck_ack_state',
            ),
        ]

    def __str__(self):
        return f"Thông báo {self.thong_bao_id} — Người nhận {self.nguoi_dung_id}"


# 5. CHUỖI XỬ LÝ KỸ THUẬT TRONG DỰ ÁN

class PhuongAnXuLy(TimeStamped):
    ma_phuong_an = models.BigAutoField(primary_key=True)
    bai_viet = models.ForeignKey(
        BaiViet,
        on_delete=models.PROTECT,
        related_name='phuong_an',
        db_column='ma_bai_viet',
    )
    nguoi_de_xuat = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_de_xuat')
    binh_luan_nguon = models.ForeignKey(
        BinhLuan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_binh_luan_nguon',
    )
    noi_dung_phuong_an = models.TextField()
    # UC-PRJ-07, trang 132–133: phương án phải có nội dung và cơ sở đề xuất.
    co_so_de_xuat = models.TextField()
    trang_thai = models.CharField(
        max_length=30,
        choices=[('de_xuat', 'Đề xuất'), ('da_chon_thu', 'Đã chọn thử'), ('ngung_dung', 'Ngừng dùng')],
        default='de_xuat',
    )

    class Meta:
        db_table = "PHUONG_AN_XU_LY"

    def clean(self):
        super().clean()
        post, comment = related(self, "bai_viet"), related(self, "binh_luan_nguon")
        if post and not (post.du_an_id and post.che_do_xu_ly):
            raise ValidationError({"bai_viet": "Phương án cần một vấn đề kỹ thuật của dự án."})
        if comment and comment.bai_viet_id != self.bai_viet_id:
            raise ValidationError({"binh_luan_nguon": "Bình luận phải thuộc bài nguồn."})

    def __str__(self):
        return (self.noi_dung_phuong_an or "")[:60] or f"Phương án #{self.pk or 'mới'}"


class LanThuPhuongAn(TimeStamped):
    ma_lan_thu = models.BigAutoField(primary_key=True)
    phuong_an = models.ForeignKey(
        PhuongAnXuLy,
        on_delete=models.PROTECT,
        related_name='lan_thu',
        db_column='ma_phuong_an',
    )
    nguoi_khoi_tao = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_khoi_tao')
    nguoi_thuc_hien = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_thuc_hien',
    )
    so_lan = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    mo_ta_thuc_hien = models.TextField(blank=True)
    trang_thai = models.CharField(
        max_length=30,
        choices=[
            ('cho_ket_qua', 'Chờ kết quả thực tế'),
            ('dang_thuc_hien', 'Đang thực hiện'),
            ('da_co_ket_qua', 'Đã có kết quả'),
            ('dung_thu', 'Dừng việc thử'),
            ('da_huy', 'Đã hủy'),
        ],
        default='cho_ket_qua',
    )
    ngay_thu = models.DateTimeField(default=timezone.now, db_column="bat_dau_luc")
    ket_thuc_luc = models.DateTimeField(null=True, blank=True)
    ly_do_huy = models.TextField(blank=True)
    nguoi_xac_nhan_dung = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    ket_luan_dung = models.ForeignKey(
        'KetLuanXuLy', null=True, blank=True, on_delete=models.PROTECT, related_name='lan_thu_dung',
    )
    # Mỗi lần thử có định danh; request gửi lại phải dùng lại khóa đã cấp.
    khoa_yeu_cau = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        db_table = "LAN_THU_PHUONG_AN"
        constraints = [
            models.UniqueConstraint(fields=['phuong_an', 'so_lan'], name='uq_lan_thu_phuong_an'),
            models.CheckConstraint(condition=Q(so_lan__gte=1), name='ck_trial_number'),
            models.CheckConstraint(
                condition=Q(ket_thuc_luc__isnull=True) | Q(ket_thuc_luc__gte=F('ngay_thu')),
                name='ck_trial_dates',
            ),
            models.CheckConstraint(
                condition=(
                    (
                        Q(
                            trang_thai__in=['cho_ket_qua', 'dang_thuc_hien'],
                            ket_thuc_luc__isnull=True,
                        )
                        | Q(
                            trang_thai='da_co_ket_qua',
                            nguoi_thuc_hien__isnull=False,
                            ket_thuc_luc__isnull=False,
                        )
                    )
                    | Q(trang_thai='da_huy', ket_thuc_luc__isnull=False) & ~Q(ly_do_huy='')
                    | Q(
                        trang_thai='dung_thu', ket_thuc_luc__isnull=False,
                        nguoi_xac_nhan_dung__isnull=False, ket_luan_dung__isnull=False,
                    ) & ~Q(ly_do_huy='')
                ),
                name='ck_trial_lifecycle',
            ),
        ]

    def __str__(self):
        return f"Phương án {self.phuong_an_id} — Lần thử {self.so_lan}"


class KetQuaThu(TimeStamped):
    ma_ket_qua = models.BigAutoField(primary_key=True)
    lan_thu = models.OneToOneField(
        LanThuPhuongAn,
        on_delete=models.PROTECT,
        related_name='ket_qua',
        db_column='ma_lan_thu',
    )
    nguoi_ghi_nhan = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_ghi_nhan')
    mo_ta_ket_qua = models.TextField()
    thanh_cong = models.BooleanField(default=False, db_column="ket_qua")
    ngay_ghi_nhan = models.DateTimeField(default=timezone.now)
    hoan_tat_luc = models.DateTimeField(default=timezone.now)
    ly_do_hieu_chinh = models.TextField(blank=True)
    # Minh chứng nằm ở TepTin/DinhKem; không lưu đường dẫn bằng chứng thứ hai.

    class Meta:
        db_table = "KET_QUA_THU"

    def clean(self):
        super().clean()
        trial = related(self, "lan_thu")
        if trial and not trial.nguoi_thuc_hien_id:
            raise ValidationError({"lan_thu": "Cần xác định người thực hiện trước khi ghi kết quả."})
        if trial and trial.trang_thai in ("da_huy", "dung_thu"):
            raise ValidationError({"lan_thu": "Lần thử đã dừng hoặc hủy không được ghi kết quả."})

    def __str__(self):
        return f"Lần thử {self.lan_thu_id} — {'Thành công' if self.thanh_cong else 'Thất bại'}"


class KetLuanXuLy(TimeStamped):
    ma_ket_luan = models.BigAutoField(primary_key=True)
    bai_viet_nguon = models.OneToOneField(
        BaiViet,
        on_delete=models.PROTECT,
        related_name='ket_luan_xu_ly',
        db_column='ma_bai_viet',
    )
    ket_qua = models.OneToOneField(
        KetQuaThu,
        on_delete=models.PROTECT,
        related_name='ket_luan_xu_ly',
        db_column='ma_ket_qua',
    )
    nguoi_de_nghi = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_de_nghi')
    noi_dung_ket_luan = models.TextField(db_column="tom_tat_ket_luan")
    # UC-PRJ-09 không có bước chờ một người duyệt khác.
    trang_thai = models.CharField(
        max_length=30,
        choices=[('da_xac_nhan', 'Đã ghi nhận kết luận')],
        default='da_xac_nhan',
    )
    ngay_de_nghi = models.DateTimeField(default=timezone.now)
    ngay_xac_nhan = models.DateTimeField(default=timezone.now, db_column="xac_nhan_luc")
    khoa_yeu_cau = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        db_table = "KET_LUAN_XU_LY"
        constraints = [models.CheckConstraint(condition=Q(trang_thai='da_xac_nhan'), name='ck_resolution_final')]

    def clean(self):
        super().clean()
        result = related(self, "ket_qua")
        if result:
            if not result.thanh_cong:
                raise ValidationError({"ket_qua": "Chỉ dùng kết quả thành công để kết luận."})
            if result.lan_thu.phuong_an.bai_viet_id != self.bai_viet_nguon_id:
                raise ValidationError({"ket_qua": "Kết quả không thuộc bài nguồn này."})

    def __str__(self):
        return f"Kết luận bài {self.bai_viet_nguon_id}"


# 6. BÀI HỌC KINH NGHIỆM VÀ PHIÊN BẢN BÀI VIẾT TRI THỨC

class ChoDanhGiaTriThuc(TimeStamped):
    ma_cho_danh_gia = models.BigAutoField(primary_key=True)
    bai_viet_nguon = models.OneToOneField(
        BaiViet,
        on_delete=models.PROTECT,
        related_name='muc_cho_tri_thuc',
        db_column='ma_bai_viet_nguon',
    )
    ket_luan = models.OneToOneField(KetLuanXuLy, on_delete=models.PROTECT, db_column="ma_ket_luan")
    # Chưa phân công không được làm mất nguồn cần xem xét tri thức.
    phan_cong = models.ForeignKey(
        PhanCongTriThuc,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_phan_cong',
    )
    trang_thai = models.CharField(
        max_length=30,
        choices=[
            ('cho_danh_gia', 'Chờ đánh giá'),
            ('cho_danh_gia_lai', 'Chờ đánh giá lại'),
            ('khong_tao_bai_hoc', 'Không chuyển thành bài học'),
            ('da_tao_bai_hoc', 'Đã chuẩn hóa bài học'),
        ],
        default='cho_danh_gia',
    )
    ly_do_cho = models.TextField(blank=True)
    nguoi_danh_gia = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_danh_gia',
    )
    danh_gia_luc = models.DateTimeField(null=True, blank=True)
    ly_do_danh_gia = models.TextField(blank=True)
    ket_luan_danh_gia = models.TextField(blank=True)
    bai_hoc = models.OneToOneField(
        'BaiHocKinhNghiem',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='muc_cho_da_xu_ly',
        db_column='ma_bai_hoc',
    )
    ghi_chu = models.TextField(blank=True)

    class Meta:
        db_table = "CHO_DANH_GIA_TRI_THUC"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(trang_thai__in=['cho_danh_gia', 'cho_danh_gia_lai'], bai_hoc__isnull=True)
                        | Q(
                            trang_thai='khong_tao_bai_hoc',
                            bai_hoc__isnull=True,
                            nguoi_danh_gia__isnull=False,
                            danh_gia_luc__isnull=False,
                        )
                    )
                    | Q(
                        trang_thai='da_tao_bai_hoc',
                        bai_hoc__isnull=False,
                        nguoi_danh_gia__isnull=False,
                        danh_gia_luc__isnull=False,
                    )
                ),
                name='ck_review_outcome',
            ),
        ]

    def clean(self):
        super().clean()
        conclusion, assignment, lesson = related(self, "ket_luan"), related(self, "phan_cong"), related(self, "bai_hoc")
        if conclusion and conclusion.bai_viet_nguon_id != self.bai_viet_nguon_id:
            raise ValidationError({"ket_luan": "Kết luận không thuộc nguồn chờ."})
        post = related(self, "bai_viet_nguon")
        if assignment and post and not same_project(assignment, post.du_an_id):
            raise ValidationError({"phan_cong": "Phân công không thuộc dự án nguồn."})
        if lesson and lesson.bai_viet_nguon_id != self.bai_viet_nguon_id:
            raise ValidationError({"bai_hoc": "Bài học không thuộc nguồn chờ."})
        # Không chặn tạo/đánh giá lại chỉ vì đã từng khong_tao_bai_hoc.

    def __str__(self):
        return f"Nguồn {self.bai_viet_nguon_id} — {self.get_trang_thai_display()}"


class BaiHocKinhNghiem(SoftDeleted):
    ma_bai_hoc = models.BigAutoField(primary_key=True)
    bai_viet_nguon = models.OneToOneField(
        BaiViet,
        on_delete=models.PROTECT,
        related_name='bai_hoc_kinh_nghiem',
        db_column='ma_bai_viet_nguon',
    )
    ket_luan = models.OneToOneField(KetLuanXuLy, on_delete=models.PROTECT, db_column="ma_ket_luan")
    phan_cong = models.ForeignKey(PhanCongTriThuc, on_delete=models.PROTECT, db_column='ma_phan_cong')
    nguoi_tao = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_tao')
    tieu_de = models.CharField(max_length=250)
    van_de = models.TextField()
    nguyen_nhan = models.TextField()
    giai_phap = models.TextField()
    ket_qua = models.TextField()
    pham_vi_ap_dung = models.TextField()
    pham_vi_chia_se = models.CharField(
        max_length=30,
        choices=[('du_an', 'Trong dự án'), ('noi_bo', 'Nội bộ công ty')],
        default='du_an',
    )
    # UC-KNW-04: chỉ ghi bài học khi đã chuẩn hóa; bản đang soạn ở biểu mẫu.
    # Người chuẩn hóa tự kiểm tra nội dung, không thêm actor phê duyệt mới.
    nguoi_kiem_tra_noi_dung = models.ForeignKey(
        USER,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_kiem_tra_noi_dung',
    )
    ghi_chu_cong_bo = models.TextField(blank=True)
    kiem_tra_cong_bo_luc = models.DateTimeField(null=True, blank=True)
    ngay_luu_tri_thuc = models.DateTimeField(null=True, blank=True)
    phien_ban_noi_dung = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    # UC-KNW-06: đây là trạng thái quản trị của bài đã chuẩn hóa,
    # không phải trạng thái nháp/duyệt nội dung của UC-KNW-04.
    trang_thai_quan_tri = models.CharField(
        max_length=20,
        choices=KnowledgeAdminStatus.choices,
        default=KnowledgeAdminStatus.VISIBLE,
    )

    class Meta:
        db_table = "BAI_HOC_KINH_NGHIEM"
        constraints = [
            models.CheckConstraint(
                condition=Q(trang_thai_quan_tri__in=KnowledgeAdminStatus.values),
                name='ck_lesson_admin_state',
            ),
            models.CheckConstraint(
                condition=Q(phien_ban_noi_dung__gte=1),
                name='ck_lesson_content_version',
            ),
            models.CheckConstraint(
                condition=Q(kiem_tra_cong_bo_luc__isnull=False, ngay_luu_tri_thuc__isnull=False),
                name='ck_lesson_complete',
            ),
        ]

    def clean(self):
        super().clean()
        conclusion, assignment, post = related(self, "ket_luan"), related(self, "phan_cong"), related(self, "bai_viet_nguon")
        if conclusion and conclusion.bai_viet_nguon_id != self.bai_viet_nguon_id:
            raise ValidationError({"ket_luan": "Kết luận không thuộc nguồn bài học."})
        if assignment and post and not same_project(assignment, post.du_an_id):
            raise ValidationError({"phan_cong": "Phân công không thuộc dự án nguồn."})
        if conclusion and not conclusion.ket_qua.thanh_cong:
            raise ValidationError({"ket_luan": "Căn cứ cần kết quả thành công."})

    def __str__(self):
        return self.tieu_de or f"Bài học #{self.pk or 'mới'}"


class BaiVietTriThuc(SoftDeleted):
    ma_bai_viet_tri_thuc = models.BigAutoField(primary_key=True, db_column="ma_bai_tri_thuc")
    nguoi_tao = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_tao')
    khoa_khoi_tao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Cột có trong ERD, được suy ra từ trạng thái quản trị khi validation.
    an_khoi_tra_cuu = models.BooleanField(default=False, editable=False)
    trang_thai_quan_tri = models.CharField(
        max_length=20,
        choices=KnowledgeAdminStatus.choices,
        default=KnowledgeAdminStatus.VISIBLE,
    )
    phien_ban_dang_cong_bo = models.OneToOneField(
        'PhienBanTriThuc',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='bai_dang_cong_bo',
        db_column='ma_phien_ban_dang_cong_bo',
    )
    # Nội dung/tiêu đề/tóm tắt thuộc PhienBanTriThuc.
    # Bản hiện hành được xác định chỉ từ phien_ban_dang_cong_bo.

    class Meta:
        db_table = "BAI_VIET_TRI_THUC"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(trang_thai_quan_tri='hien_thi', an_khoi_tra_cuu=False)
                    | Q(trang_thai_quan_tri__in=['an', 'luu_tru'], an_khoi_tra_cuu=True)
                ),
                name='ck_article_admin_state',
            ),
        ]

    def clean(self):
        super().clean()
        self.an_khoi_tra_cuu = self.trang_thai_quan_tri != KnowledgeAdminStatus.VISIBLE
        current = related(self, "phien_ban_dang_cong_bo")
        if current:
            if current.bai_viet_tri_thuc_id != self.pk:
                raise ValidationError({"phien_ban_dang_cong_bo": "Phiên bản hiện hành phải thuộc chính bài viết này."})
            if current.trang_thai != "da_cong_bo":
                raise ValidationError({"phien_ban_dang_cong_bo": "Chỉ trỏ tới phiên bản đã công bố."})

    def __str__(self):
        return f"Bài viết tri thức #{self.pk or 'mới'}"


class PhienBanTriThuc(TimeStamped):
    ma_phien_ban = models.BigAutoField(primary_key=True)
    bai_viet_tri_thuc = models.ForeignKey(
        BaiVietTriThuc,
        on_delete=models.PROTECT,
        related_name='phien_ban',
        db_column='ma_bai_tri_thuc',
    )
    so_phien_ban = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    tieu_de = models.CharField(max_length=250)
    tom_tat = models.TextField(blank=True)
    noi_dung = models.TextField()
    loai_nguon = models.CharField(
        max_length=30,
        choices=[
            ('noi_bo', 'Tri thức chung nội bộ'),
            ('ben_ngoai', 'Nguồn bên ngoài'),
            ('ket_hop', 'Kết hợp'),
        ],
        default='noi_bo',
    )
    pham_vi_ap_dung = models.TextField(blank=True)
    pham_vi_chia_se = models.CharField(max_length=30, choices=SharingScope.choices, default=SharingScope.COMPANY)
    cong_dong = models.ForeignKey(
        CongDong,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_cong_dong',
    )
    du_an = models.ForeignKey(DuAn, null=True, blank=True, on_delete=models.PROTECT, db_column='ma_du_an')
    nguoi_bien_tap = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_bien_tap')
    nguoi_xuat_ban = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_xuat_ban',
    )
    trang_thai = models.CharField(
        max_length=30,
        choices=[('ban_nhap', 'Bản nháp'), ('da_cong_bo', 'Đã công bố'), ('lich_su', 'Phiên bản lịch sử')],
        default='ban_nhap',
    )
    xuat_ban_luc = models.DateTimeField(null=True, blank=True)
    kiem_tra_cong_bo_luc = models.DateTimeField(null=True, blank=True)
    ghi_chu_cong_bo = models.TextField(blank=True)

    class Meta:
        db_table = "PHIEN_BAN_TRI_THUC"
        permissions = [("cong_bo_tri_thuc", "Được công bố bài viết tri thức")]
        constraints = [
            models.UniqueConstraint(
                fields=['bai_viet_tri_thuc', 'so_phien_ban'],
                name='uq_phien_ban_tri_thuc',
            ),
            models.CheckConstraint(condition=Q(so_phien_ban__gte=1), name='ck_version_number'),
            models.CheckConstraint(
                condition=(
                    Q(trang_thai='ban_nhap', xuat_ban_luc__isnull=True, nguoi_xuat_ban__isnull=True)
                    | Q(
                        trang_thai__in=['da_cong_bo', 'lich_su'],
                        xuat_ban_luc__isnull=False,
                        nguoi_xuat_ban__isnull=False,
                        kiem_tra_cong_bo_luc__isnull=False,
                    )
                ),
                name='ck_version_publish',
            ),
            models.CheckConstraint(
                condition=(
                    (
                        Q(pham_vi_chia_se='noi_bo', cong_dong__isnull=True, du_an__isnull=True)
                        | Q(pham_vi_chia_se='cong_dong', cong_dong__isnull=False, du_an__isnull=True)
                    )
                    | Q(pham_vi_chia_se='du_an', du_an__isnull=False)
                ),
                name='ck_version_scope',
            ),
        ]

    def clean(self):
        super().clean()
        project = related(self, "du_an")
        if project and self.cong_dong_id and project.cong_dong_id != self.cong_dong_id:
            raise ValidationError({"cong_dong": "Phạm vi cộng đồng không khớp dự án."})
        if self.trang_thai in {"da_cong_bo", "lich_su"}:
            errors = {}
            if not self.tom_tat.strip():
                errors["tom_tat"] = "Cần tóm tắt khi công bố."
            if not self.pham_vi_ap_dung.strip():
                errors["pham_vi_ap_dung"] = "Cần phạm vi áp dụng khi công bố."
            if errors:
                raise ValidationError(errors)

    def __str__(self):
        return f"{self.tieu_de or 'Bài tri thức'} — Phiên bản {self.so_phien_ban}"


class NguonThamKhao(TimeStamped):
    ma_nguon_tham_khao = models.BigAutoField(primary_key=True, db_column="ma_nguon")
    phien_ban = models.ForeignKey(
        PhienBanTriThuc,
        on_delete=models.PROTECT,
        related_name='nguon_tham_khao',
        db_column='ma_phien_ban',
    )
    loai_tham_chieu = models.CharField(
        max_length=30,
        choices=[
            ('url', 'Đường dẫn'),
            ('bai_viet', 'Bài viết nội bộ'),
            ('tep', 'Tệp tài liệu'),
            ('tai_lieu', 'Trích dẫn tài liệu'),
        ],
        default='url',
    )
    tieu_de_nguon = models.CharField(max_length=250, blank=True)
    tac_gia = models.CharField(max_length=200, blank=True)
    url = models.URLField(max_length=2000, blank=True)
    bai_viet_nguon = models.ForeignKey(
        BaiViet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_bai_viet_nguon',
    )
    tep_nguon = models.ForeignKey(
        'TepTin',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_tep_nguon',
    )
    trich_dan = models.TextField(blank=True)
    du_lieu_bien_tap = models.JSONField(default=dict, blank=True)
    thu_tu = models.PositiveIntegerField(default=0)
    ngay_truy_cap = models.DateField(null=True, blank=True)
    ghi_chu = models.TextField(blank=True)
    # Giá trị triển khai cho nguyên tắc quyền nguồn hiện hành trong báo cáo.
    # Trường này không cấp quyền mở URL/tệp/bài nguồn.
    che_do_hien_thi = models.CharField(
        max_length=30,
        choices=[('theo_quyen_nguon', 'Hiển thị theo quyền đọc nguồn')],
        default='theo_quyen_nguon',
    )

    class Meta:
        db_table = "NGUON_THAM_KHAO"
        ordering = ["thu_tu", "ma_nguon_tham_khao"]

    def clean(self):
        super().clean()
        required = {"url": bool(self.url), "bai_viet": bool(self.bai_viet_nguon_id), "tep": bool(self.tep_nguon_id), "tai_lieu": bool(self.trich_dan)}
        if not required.get(self.loai_tham_chieu, False):
            raise ValidationError({"loai_tham_chieu": "Thiếu dữ liệu của loại nguồn tham khảo."})
        if self.loai_tham_chieu != "bai_viet" and self.bai_viet_nguon_id:
            raise ValidationError({"bai_viet_nguon": "Chỉ loại bài viết mới có FK bài nguồn."})
        if self.loai_tham_chieu != "tep" and self.tep_nguon_id:
            raise ValidationError({"tep_nguon": "Chỉ loại tệp mới có FK tệp nguồn."})

    def __str__(self):
        return self.tieu_de_nguon or self.url or f"Nguồn tham khảo #{self.pk or 'mới'}"


class ChuDeTriThuc(TimeStamped):
    ma_chu_de = models.BigAutoField(primary_key=True)
    ten_chu_de = models.CharField(max_length=150, unique=True)
    mo_ta = models.TextField(blank=True)

    class Meta:
        db_table = "CHU_DE_TRI_THUC"

    def __str__(self):
        return self.ten_chu_de


class GanChuDePhienBan(TimeStamped):
    ma_gan_chu_de = models.BigAutoField(primary_key=True)
    phien_ban = models.ForeignKey(
        PhienBanTriThuc,
        on_delete=models.PROTECT,
        related_name='gan_chu_de',
        db_column='ma_phien_ban',
    )
    chu_de = models.ForeignKey(ChuDeTriThuc, on_delete=models.PROTECT, db_column="ma_chu_de")

    class Meta:
        db_table = "GAN_CHU_DE_PHIEN_BAN"
        constraints = [models.UniqueConstraint(fields=['phien_ban', 'chu_de'], name='uq_chu_de_phien_ban')]

    def __str__(self):
        return f"Phiên bản {self.phien_ban_id} — Chủ đề {self.chu_de_id}"


# 7. TỆP DÙNG CHUNG, ĐÍNH KÈM, THÔNG BÁO HỆ THỐNG VÀ NHẬT KÝ

class TepTin(TimeStamped):
    ma_tep_tin = models.BigAutoField(primary_key=True, db_column="ma_tep")
    ten_tep = models.CharField(max_length=255, db_column="ten_tep_goc")
    tep = models.FileField(upload_to='ozzone/', max_length=500, unique=True, db_column='khoa_luu_tru')
    loai_tep = models.CharField(max_length=150, blank=True, db_column="mime_type")
    kich_thuoc = models.PositiveBigIntegerField(default=0, db_column="kich_thuoc_byte")
    sha256 = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        validators=[RegexValidator('\\A[0-9a-fA-F]{64}\\Z', 'Mã SHA-256 phải có đúng 64 ký tự hệ 16.')],
    )
    trang_thai = models.CharField(
        max_length=30,
        choices=[('tam', 'Tệp tạm'), ('san_sang', 'Sẵn sàng sử dụng'), ('da_go', 'Đã gỡ')],
        default='tam',
    )
    het_han_tam_luc = models.DateTimeField(null=True, blank=True)
    nguoi_tai_len = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_tai_len')
    ngay_tai_len = models.DateTimeField(default=timezone.now)
    da_xoa_mem = models.BooleanField(default=False)

    class Meta:
        db_table = "TEP_TIN"
        constraints = [
            models.CheckConstraint(
                condition=~Q(trang_thai='san_sang') | ~Q(loai_tep='') & ~Q(sha256=''),
                name='ck_file_ready_metadata',
            ),
        ]

    def clean(self):
        super().clean()
        if self.trang_thai == "san_sang" and (not self.loai_tep.strip() or not self.sha256.strip()):
            raise ValidationError("Tệp sẵn sàng cần MIME type và mã SHA-256 đã được máy chủ kiểm tra.")

    def __str__(self):
        return self.ten_tep


class DinhKem(TimeStamped):
    ma_dinh_kem = models.BigAutoField(primary_key=True)
    tep_tin = models.ForeignKey(TepTin, on_delete=models.PROTECT, related_name='dinh_kem', db_column='ma_tep')
    bai_viet = models.ForeignKey(
        BaiViet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_bai_viet',
    )
    binh_luan = models.ForeignKey(
        BinhLuan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='binh_luan',
    )
    ket_qua_thu = models.ForeignKey(
        KetQuaThu,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ket_qua_thu',
    )
    bai_hoc = models.ForeignKey(
        BaiHocKinhNghiem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_bai_hoc',
    )
    phien_ban_tri_thuc = models.ForeignKey(
        PhienBanTriThuc,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_phien_ban',
    )
    phuong_an = models.ForeignKey(
        PhuongAnXuLy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_phuong_an',
    )
    nguoi_dinh_kem = models.ForeignKey(USER, on_delete=models.PROTECT, related_name='+', db_column='nguoi_dinh_kem')
    ngay_dinh_kem = models.DateTimeField(default=timezone.now)
    mo_ta = models.TextField(blank=True, db_column="chu_thich")
    thu_tu = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "DINH_KEM"
        constraints = [
            models.CheckConstraint(
                condition=exactly_one(
                    'bai_viet',
                    'binh_luan',
                    'ket_qua_thu',
                    'bai_hoc',
                    'phien_ban_tri_thuc',
                    'phuong_an',
                ),
                name='ck_attachment_one_owner',
            ),
        ]

    def __str__(self):
        return f"Tệp {self.tep_tin_id} — Đính kèm #{self.pk or 'mới'}"


class ThongBaoHeThong(TimeStamped):
    ma_thong_bao_he_thong = models.BigAutoField(primary_key=True)
    nguoi_nhan = models.ForeignKey(
        USER,
        on_delete=models.PROTECT,
        related_name='thong_bao_he_thong',
        db_column='nguoi_nhan',
    )
    nguoi_tao_hanh_dong = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_tao_hanh_dong',
    )
    tieu_de = models.CharField(max_length=250)
    noi_dung = models.TextField()
    loai_thong_bao = models.CharField(max_length=80)
    khoa_su_kien = models.CharField(max_length=150)
    bai_viet = models.ForeignKey(
        BaiViet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_bai_viet',
    )
    binh_luan = models.ForeignKey(
        BinhLuan,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='binh_luan',
    )
    bai_hoc = models.ForeignKey(
        BaiHocKinhNghiem,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_bai_hoc',
    )
    bai_viet_tri_thuc = models.ForeignKey(
        BaiVietTriThuc,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_bai_tri_thuc',
    )
    cho_danh_gia = models.ForeignKey(
        ChoDanhGiaTriThuc,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_column='ma_cho_danh_gia',
    )
    duong_dan = models.CharField(max_length=500, blank=True)
    da_doc = models.BooleanField(default=False)
    ngay_doc = models.DateTimeField(null=True, blank=True, db_column="da_doc_luc")

    class Meta:
        db_table = "THONG_BAO_HE_THONG"
        ordering = ["-ngay_tao", "-ma_thong_bao_he_thong"]
        constraints = [
            models.UniqueConstraint(
                fields=['nguoi_nhan', 'khoa_su_kien'],
                name='uq_notification_event',
            ),
            models.CheckConstraint(condition=~Q(khoa_su_kien=''), name='ck_notification_event_key'),
            models.CheckConstraint(
                condition=Q(da_doc=False, ngay_doc__isnull=True) | Q(da_doc=True, ngay_doc__isnull=False),
                name='ck_notification_read',
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        bai_viet__isnull=True,
                        binh_luan__isnull=True,
                        bai_hoc__isnull=True,
                        bai_viet_tri_thuc__isnull=True,
                        cho_danh_gia__isnull=True,
                    )
                    | exactly_one(
                        'bai_viet',
                        'binh_luan',
                        'bai_hoc',
                        'bai_viet_tri_thuc',
                        'cho_danh_gia',
                    )
                ),
                name='ck_notification_target',
            ),
        ]

    def __str__(self):
        return self.tieu_de or f"Thông báo #{self.pk or 'mới'}"


class NhatKyNghiepVu(models.Model):
    ma_nhat_ky = models.BigAutoField(primary_key=True)
    nguoi_dung = models.ForeignKey(
        USER,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        db_column='nguoi_thuc_hien',
    )
    hanh_dong = models.CharField(max_length=100)
    loai_tai_nguyen = models.CharField(max_length=100, db_column="loai_doi_tuong")
    ma_tai_nguyen = models.CharField(max_length=100, db_column="dinh_danh_doi_tuong")
    du_lieu_truoc = models.JSONField(null=True, blank=True, db_column="truoc_thay_doi")
    du_lieu_sau = models.JSONField(null=True, blank=True, db_column="sau_thay_doi")
    ly_do = models.TextField(blank=True)
    # Các log của cùng một giao dịch có thể dùng chung ma_yeu_cau.
    ma_yeu_cau = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    dia_chi_ip = models.GenericIPAddressField(null=True, blank=True)
    thoi_diem = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "NHAT_KY_NGHIEP_VU"
        ordering = ["-thoi_diem", "-ma_nhat_ky"]
        indexes = [models.Index(fields=["loai_tai_nguyen", "ma_tai_nguyen", "thoi_diem"])]

    def __str__(self):
        return f"{self.hanh_dong} — {self.loai_tai_nguyen} {self.ma_tai_nguyen}"
