"""Test phân hệ Tài khoản — mỗi lớp ứng với một use case. Chạy: python manage.py test accounts"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from projectp.models import HoSoNhanVien, KyNang, PhongBan, ViTriCongViec

User = get_user_model()
PW = "Mat-khau-Test-2026"


def tao_nhan_vien(username, bat_doi=False, **extra):
    user = User.objects.create_user(
        username, f"{username}@ozzone.vn", PW, first_name="An", last_name="Nguyễn Văn", **extra
    )
    pb, _ = PhongBan.objects.get_or_create(ma_nghiep_vu="KT", defaults={"ten_phong_ban": "Kỹ thuật"})
    vt, _ = ViTriCongViec.objects.get_or_create(ma_nghiep_vu="KS", defaults={"ten_vi_tri": "Kỹ sư điện"})
    HoSoNhanVien.objects.create(
        nguoi_dung=user, phong_ban=pb, vi_tri=vt, ma_nhan_vien=f"NV-{username}", bat_buoc_doi_mat_khau=bat_doi
    )
    return user


class UC_ACC_01_DangNhap(TestCase):
    def test_dang_nhap_bang_username_email_chi_la_lien_he(self):
        tao_nhan_vien("an")
        r = self.client.post(reverse("accounts:login"), {"username": "an", "password": PW})
        self.assertEqual(r.status_code, 302)
        self.client.logout()
        r = self.client.post(reverse("accounts:login"), {"username": "an@ozzone.vn", "password": PW})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_sai_mat_khau_va_tai_khoan_bi_khoa(self):
        tao_nhan_vien("an")
        r = self.client.post(reverse("accounts:login"), {"username": "an", "password": "sai"})
        self.assertContains(r, "Tài khoản hoặc mật khẩu không đúng")
        tao_nhan_vien("binh", is_active=False)
        r = self.client.post(reverse("accounts:login"), {"username": "binh", "password": PW})
        self.assertContains(r, "vô hiệu hóa")

    def test_bat_buoc_doi_mat_khau_lan_dau(self):
        user = tao_nhan_vien("an", bat_doi=True)
        self.client.force_login(user)
        r = self.client.get(reverse("accounts:profile"))
        self.assertIn(reverse("accounts:first_password"), r.url)  # bị chuyển sang trang đổi mật khẩu
        r = self.client.post(
            reverse("accounts:first_password"),
            {"old_password": PW, "new_password1": "a1", "new_password2": "b2"},
        )
        self.assertContains(r, "không khớp")
        r = self.client.post(
            reverse("accounts:first_password"),
            {"old_password": PW, "new_password1": "Ozz-Moi-2026!", "new_password2": "Ozz-Moi-2026!"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertFalse(HoSoNhanVien.objects.get(nguoi_dung=user).bat_buoc_doi_mat_khau)
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)


class UC_ACC_02_DangXuat(TestCase):
    def test_get_hoi_lai_post_moi_dang_xuat(self):
        self.client.force_login(tao_nhan_vien("an"))
        self.assertContains(self.client.get(reverse("accounts:logout")), "Xác nhận đăng xuất")
        self.client.post(reverse("accounts:logout"))
        r = self.client.get(reverse("accounts:profile"))
        self.assertIn(reverse("accounts:login"), r.url)


class UC_ACC_03_HoSo(TestCase):
    def test_sua_ho_so_khong_doi_duoc_phong_ban(self):
        user = tao_nhan_vien("an")
        k = KyNang.objects.create(ten_ky_nang="PLC")
        khac = PhongBan.objects.create(ma_nghiep_vu="X", ten_phong_ban="Khác")
        self.client.force_login(user)
        r = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "last_name": "Trần",
                "first_name": "Minh  Anh",
                "gioi_thieu": "Xin chào",
                "so_dien_thoai": "0236 388 0240",
                "ky_nang": [k.pk],
                "phong_ban": khac.pk,
            },
        )
        self.assertRedirects(r, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Minh Anh")
        self.assertEqual(user.ho_so_nhan_vien.phong_ban.ma_nghiep_vu, "KT")
        self.assertEqual(user.ho_so_nhan_vien.kynangnhanvien_set.count(), 1)

    def test_ten_trong_bi_tu_choi(self):
        self.client.force_login(tao_nhan_vien("an"))
        r = self.client.post(reverse("accounts:profile_edit"), {"last_name": "A", "first_name": "   "})
        self.assertTrue(r.context["form"].errors.get("first_name"))


class UC_ACC_04_TraCuu(TestCase):
    def test_tim_theo_ten(self):
        me = tao_nhan_vien("an")
        b = tao_nhan_vien("binh")
        b.first_name, b.last_name = "Bình", "Trần Thị"
        b.save()
        self.client.force_login(me)
        r = self.client.get(reverse("accounts:directory"), {"q": "  Bình  "})
        self.assertContains(r, "Trần Thị Bình")
        self.assertEqual(len(r.context["people"]), 1)

    def test_chua_dang_nhap_bi_chuyen_trang(self):
        self.assertEqual(self.client.get(reverse("accounts:directory")).status_code, 302)


class AccountDisplayNameTests(TestCase):
    def test_templates_use_account_name_order_and_username_fallback(self):
        from django.template import Context, Template

        person = get_user_model()(username="ngothimai", first_name="Mai", last_name="Ngô Thị")
        template = Template("{% load ozzone_names %}{{ person|ho_ten }}")
        self.assertEqual(template.render(Context({"person": person})), "Ngô Thị Mai")
        person.first_name = ""
        person.last_name = ""
        self.assertEqual(template.render(Context({"person": person})), "ngothimai")
