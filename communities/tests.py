"""Test phân hệ Cộng đồng — mỗi lớp ứng với một use case. Chạy: python manage.py test communities"""

import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from projectp.models import BaiViet, CommunityRole, CongDong, DuAn, MemberStatus, ThanhVienCongDong, YeuCauThamGia

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="x", first_name="Đức", last_name="Phạm Minh")
        self.mod = User.objects.create_user("mod", password="x")
        self.alice = User.objects.create_user("alice", password="x")
        self.bob = User.objects.create_user("bob", password="x")
        self.kin = CongDong.objects.create(ten_cong_dong="PLC", nguoi_tao=self.owner,
                                           quy_tac_tham_gia="cho_duyet", pham_vi_truy_cap="thanh_vien")
        self.mo = CongDong.objects.create(ten_cong_dong="Đo lường", nguoi_tao=self.owner,
                                          quy_tac_tham_gia="truc_tiep", pham_vi_truy_cap="noi_bo")
        for c in (self.kin, self.mo):
            ThanhVienCongDong.objects.create(cong_dong=c, nguoi_dung=self.owner, vai_tro=CommunityRole.OWNER)
            ThanhVienCongDong.objects.create(cong_dong=c, nguoi_dung=self.mod, vai_tro=CommunityRole.MODERATOR)

    def la_thanh_vien(self, user, c):
        return ThanhVienCongDong.objects.filter(cong_dong=c, nguoi_dung=user, trang_thai=MemberStatus.ACTIVE).exists()

    def post_as(self, user, name, args, data=None):
        self.client.force_login(user)
        return self.client.post(reverse(f"communities:{name}", args=args), data or {})


class UC_COM_01_KhamPha(Base):
    def test_thay_cong_dong_thuong_khong_thay_cong_dong_du_an_kin(self):
        CongDong.objects.create(ten_cong_dong="DA kín", nguoi_tao=self.owner, loai_cong_dong="du_an",
                                quy_tac_tham_gia="theo_du_an", pham_vi_truy_cap="thanh_vien")
        self.client.force_login(self.bob)
        r = self.client.get(reverse("communities:list"))
        self.assertContains(r, "PLC")
        self.assertNotContains(r, "DA kín")


class SidebarCongDong(Base):
    """Sidebar cố định như Figma: Khám phá · <cộng đồng của tôi> · Thành viên · Yêu cầu tham gia · Kiểm duyệt."""

    def sidebar_cua(self, user, name, args=None):
        self.client.force_login(user)
        return self.client.get(reverse(f"communities:{name}", args=args or [])).context

    def test_kham_pha_hien_cong_dong_mo_gan_nhat(self):
        ctx = self.sidebar_cua(self.owner, "list")
        self.assertEqual(ctx["side_community"], self.kin)                  # chưa mở gì -> tham gia sớm nhất
        self.client.get(reverse("communities:detail", args=[self.mo.pk]))  # mở cộng đồng Đo lường
        ctx = self.client.get(reverse("communities:list")).context
        self.assertEqual(ctx["side_community"], self.mo)                   # -> nhớ cộng đồng mở gần nhất
        self.assertEqual(ctx["active_side"], "explore")

    def test_xem_cong_dong_chua_tham_gia_giu_dung_ngu_canh_dang_mo(self):
        self.post_as(self.alice, "join", [self.mo.pk])
        ctx = self.sidebar_cua(self.alice, "detail", [self.kin.pk])       # alice chưa ở PLC
        self.assertEqual(ctx["side_community"], self.kin)
        self.assertEqual(ctx["active_side"], "community")
        self.assertFalse(ctx["can_read"])  # ngữ cảnh không tự cấp quyền vào bảng tin kín

    def test_kiem_duyet_chi_hien_cho_nguoi_co_quyen(self):
        self.post_as(self.alice, "join", [self.mo.pk])
        r = self.client.get(reverse("communities:list"))
        self.assertFalse(r.context["side_can_moderate"])
        self.assertNotContains(r, "Kiểm duyệt cộng đồng")
        ctx = self.sidebar_cua(self.mod, "detail", [self.mo.pk])
        self.assertTrue(ctx["side_can_moderate"])
        self.assertEqual(ctx["side_moderation_pk"], self.mo.pk)

    def test_chua_tham_gia_cong_dong_nao(self):
        ctx = self.sidebar_cua(self.bob, "list")
        self.assertIsNone(ctx["side_community"])                           # ẩn mục 2 và Thành viên


class UC_COM_02_ThamGia(Base):
    def test_tham_gia_truc_tiep(self):
        self.post_as(self.alice, "join", [self.mo.pk])
        self.assertTrue(self.la_thanh_vien(self.alice, self.mo))

    def test_gui_yeu_cau_roi_chu_so_huu_duyet(self):
        self.post_as(self.alice, "join", [self.kin.pk], {"loi_nhan": "Muốn học PLC"})
        self.post_as(self.alice, "join", [self.kin.pk])                       # gửi lại không tạo trùng
        self.assertEqual(YeuCauThamGia.objects.filter(nguoi_dung=self.alice).count(), 1)
        yc = YeuCauThamGia.objects.get(nguoi_dung=self.alice)
        self.post_as(self.mod, "decide", [yc.pk], {"decision": "approve"})     # kiểm duyệt viên không được duyệt
        self.assertFalse(self.la_thanh_vien(self.alice, self.kin))
        self.post_as(self.owner, "decide", [yc.pk], {"decision": "approve"})
        self.assertTrue(self.la_thanh_vien(self.alice, self.kin))

    def test_tu_choi_can_ly_do_gui_lai_tao_yeu_cau_moi(self):
        self.post_as(self.alice, "join", [self.kin.pk])
        yc = YeuCauThamGia.objects.get(nguoi_dung=self.alice)
        self.post_as(self.owner, "decide", [yc.pk], {"decision": "reject", "ly_do": ""})
        yc.refresh_from_db()
        self.assertEqual(yc.trang_thai, "cho_duyet")
        self.post_as(self.owner, "decide", [yc.pk], {"decision": "reject", "ly_do": "Chưa phù hợp"})
        self.post_as(self.alice, "join", [self.kin.pk])
        self.assertEqual(YeuCauThamGia.objects.filter(nguoi_dung=self.alice).count(), 2)

    def test_duyet_yeu_cau_cu_khong_ha_quyen_kiem_duyet_vien(self):
        yc = YeuCauThamGia.objects.create(cong_dong=self.kin, nguoi_dung=self.alice)
        ThanhVienCongDong.objects.create(cong_dong=self.kin, nguoi_dung=self.alice, vai_tro=CommunityRole.MODERATOR)
        self.post_as(self.owner, "decide", [yc.pk], {"decision": "approve"})
        yc.refresh_from_db()
        self.assertEqual(yc.trang_thai, "da_duyet")
        tv = ThanhVienCongDong.objects.get(cong_dong=self.kin, nguoi_dung=self.alice)
        self.assertEqual(tv.vai_tro, CommunityRole.MODERATOR)               # vẫn giữ vai trò cũ

    def test_khong_duyet_yeu_cau_cua_cong_dong_da_xoa(self):
        yc = YeuCauThamGia.objects.create(cong_dong=self.kin, nguoi_dung=self.alice)
        CongDong.objects.filter(pk=self.kin.pk).update(da_xoa_mem=True)
        r = self.post_as(self.owner, "decide", [yc.pk], {"decision": "approve"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(ThanhVienCongDong.objects.filter(cong_dong=self.kin, nguoi_dung=self.alice).exists())

    def test_tham_gia_truc_tiep_dong_yeu_cau_dang_cho(self):
        yc = YeuCauThamGia.objects.create(cong_dong=self.mo, nguoi_dung=self.alice)  # gửi khi còn 'cần duyệt'
        self.post_as(self.alice, "join", [self.mo.pk])
        self.assertTrue(self.la_thanh_vien(self.alice, self.mo))
        yc.refresh_from_db()
        self.assertEqual(yc.trang_thai, "da_huy")

    def test_sidebar_khong_dem_yeu_cau_cua_cong_dong_da_xoa(self):
        YeuCauThamGia.objects.create(cong_dong=self.kin, nguoi_dung=self.alice)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("communities:list")).context["side_pending"], 1)
        CongDong.objects.filter(pk=self.kin.pk).update(da_xoa_mem=True)
        self.assertEqual(self.client.get(reverse("communities:list")).context["side_pending"], 0)

    def test_cong_dong_du_an_khong_tu_tham_gia(self):
        pc = CongDong.objects.create(ten_cong_dong="DA", nguoi_tao=self.owner, loai_cong_dong="du_an",
                                     quy_tac_tham_gia="theo_du_an", pham_vi_truy_cap="thanh_vien")
        ThanhVienCongDong.objects.create(cong_dong=pc, nguoi_dung=self.mod)
        self.post_as(self.mod, "leave", [pc.pk])
        self.assertTrue(self.la_thanh_vien(self.mod, pc))                       # không tự rời được


class UC_COM_03_Roi(Base):
    def test_roi_roi_vao_lai(self):
        self.post_as(self.alice, "join", [self.mo.pk])
        self.post_as(self.alice, "leave", [self.mo.pk])
        self.assertFalse(self.la_thanh_vien(self.alice, self.mo))
        self.post_as(self.alice, "join", [self.mo.pk])
        self.assertTrue(self.la_thanh_vien(self.alice, self.mo))

    def test_chu_so_huu_duy_nhat_phai_ban_giao_truoc(self):
        self.post_as(self.owner, "leave", [self.kin.pk])
        self.assertTrue(self.la_thanh_vien(self.owner, self.kin))
        tv_mod = ThanhVienCongDong.objects.get(cong_dong=self.kin, nguoi_dung=self.mod)
        self.post_as(self.owner, "transfer", [self.kin.pk], {"member_id": tv_mod.pk, "confirm": "1"})
        tv_mod.refresh_from_db()
        self.assertEqual(tv_mod.vai_tro, CommunityRole.OWNER)
        self.post_as(self.owner, "leave", [self.kin.pk])
        self.assertFalse(self.la_thanh_vien(self.owner, self.kin))


class UC_COM_04_BangTin(Base):
    def test_cong_dong_kin_nguoi_ngoai_khong_doc_duoc(self):
        post = BaiViet.objects.create(nguoi_dang=self.owner, cong_dong=self.kin, noi_dung="Bí mật thành viên")
        self.client.force_login(self.bob)
        r = self.client.get(reverse("communities:detail", args=[self.kin.pk]))
        self.assertNotContains(r, "Bí mật thành viên")
        self.assertContains(r, "Gửi yêu cầu")
        r = self.client.get(reverse("communities:post", args=[self.kin.pk, post.pk]))
        self.assertContains(r, "Nội dung không khả dụng")

    def test_pham_vi_toan_cong_ty_ai_cung_doc_duoc(self):
        BaiViet.objects.create(nguoi_dang=self.owner, cong_dong=self.mo, noi_dung="Bài công khai nội bộ")
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(reverse("communities:detail", args=[self.mo.pk])), "Bài công khai nội bộ")


class UC_COM_05_ThanhVien(Base):
    def test_trang_thanh_vien(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse("communities:members", args=[self.kin.pk]))
        self.assertContains(r, "Chủ sở hữu")
        self.assertContains(r, "Bàn giao chủ sở hữu")


class UC_COM_06_DangBai(Base):
    def test_nguoi_ngoai_khong_dang_duoc(self):
        self.post_as(self.bob, "post_create", [self.mo.pk], {"noi_dung": "x"})
        self.assertFalse(BaiViet.objects.filter(nguoi_dang=self.bob).exists())

    @override_settings(MEDIA_ROOT="/tmp/oz_test_media")
    def test_dang_bai_kem_tep(self):
        self.post_as(self.alice, "join", [self.mo.pk])
        tep = SimpleUploadedFile("checklist.txt", b"hello", content_type="text/plain")
        self.post_as(self.alice, "post_create", [self.mo.pk], {"tieu_de": "T", "noi_dung": "kèm tệp", "tep": tep})
        post = BaiViet.objects.get(nguoi_dang=self.alice)
        self.assertEqual(len(post.dinhkem_set.get().tep_tin.sha256), 64)
        bad = SimpleUploadedFile("virus.exe", b"x")
        r = self.post_as(self.alice, "post_create", [self.mo.pk], {"noi_dung": "x", "tep": bad})
        self.assertContains(r, "Định dạng tệp không được phép")

    def test_du_an_luu_tru_chi_doc(self):
        pc = CongDong.objects.create(ten_cong_dong="DA", nguoi_tao=self.owner, loai_cong_dong="du_an",
                                     quy_tac_tham_gia="theo_du_an", pham_vi_truy_cap="thanh_vien")
        ThanhVienCongDong.objects.create(cong_dong=pc, nguoi_dung=self.alice)
        DuAn.objects.create(ma_du_an_nghiep_vu="DA1", ten_du_an="DA1", cong_dong=pc, nguoi_tao=self.owner,
                            trang_thai="luu_tru", ngay_bat_dau=datetime.date(2026, 1, 1),
                            luu_tru_luc="2026-02-01T00:00:00Z", nguoi_luu_tru=self.owner)
        self.post_as(self.alice, "post_create", [pc.pk], {"noi_dung": "x"})
        self.assertFalse(BaiViet.objects.filter(cong_dong=pc).exists())


class UC_COM_07_KiemDuyet(Base):
    def test_ghim_an_va_quyen(self):
        post = BaiViet.objects.create(nguoi_dang=self.owner, cong_dong=self.mo, noi_dung="x")
        self.post_as(self.alice, "join", [self.mo.pk])
        self.post_as(self.alice, "moderate", [self.mo.pk, post.pk], {"action": "pin"})   # thành viên thường
        post.refresh_from_db()
        self.assertFalse(post.da_ghim)
        self.post_as(self.mod, "moderate", [self.mo.pk, post.pk], {"action": "pin"})
        post.refresh_from_db()
        self.assertTrue(post.da_ghim)
        self.post_as(self.mod, "moderate", [self.mo.pk, post.pk], {"action": "hide"})
        post.refresh_from_db()
        self.assertEqual((post.trang_thai, post.da_ghim), ("an", False))

    def test_khong_kiem_duyet_cheo_cong_dong(self):
        post = BaiViet.objects.create(nguoi_dang=self.owner, cong_dong=self.kin, noi_dung="x")
        r = self.post_as(self.mod, "moderate", [self.mo.pk, post.pk], {"action": "hide"})
        self.assertEqual(r.status_code, 404)
