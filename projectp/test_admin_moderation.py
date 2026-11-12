
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from projectp.models import BaiViet, NhatKyNghiepVu


class CompanyContentModerationAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="moderator-staff", password="test-password", is_staff=True
        )
        self.post = BaiViet.objects.create(
            nguoi_dang=self.staff,
            loai_bai_viet=BaiViet.Kind.STANDARD,
            tieu_de="Nội dung cần kiểm duyệt",
            noi_dung="Bài viết dùng để kiểm tra luồng ẩn và khôi phục.",
            trang_thai="hien",
        )
        self.changelist_url = reverse("admin:projectp_baiviet_changelist")
        self.confirm_url = reverse("admin:projectp_baiviet_moderation_confirm")

    def _grant_moderation_permission(self):
        content_type = ContentType.objects.get_for_model(BaiViet)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="change_baiviet",
        )
        self.staff.user_permissions.add(permission)
        self.staff.refresh_from_db()

    def _start_action(self, action):
        return self.client.post(self.changelist_url, {
            "action": action,
            "_selected_action": [str(self.post.pk)],
            "select_across": "0",
        })

    def test_staff_without_content_permission_cannot_open_moderation(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.changelist_url)
        self.assertEqual(response.status_code, 403)

    def test_hide_requires_reason_and_writes_audit(self):
        self._grant_moderation_permission()
        self.client.force_login(self.staff)
        response = self._start_action("request_hide_selected")
        self.assertEqual(response.status_code, 302)
        self.assertIn("action=hide", response["Location"])

        confirm = self.client.get(response["Location"])
        self.assertEqual(confirm.status_code, 200)
        self.assertContains(confirm, "Lý do kiểm duyệt")

        no_reason = self.client.post(response["Location"], {
            "action": "hide", "post_ids": [str(self.post.pk)], "reason": ""
        })
        self.assertEqual(no_reason.status_code, 400)
        self.post.refresh_from_db()
        self.assertEqual(self.post.trang_thai, "hien")

        hidden = self.client.post(response["Location"], {
            "action": "hide", "post_ids": [str(self.post.pk)], "reason": "Nội dung không phù hợp quy định nội bộ."
        })
        self.assertEqual(hidden.status_code, 302)
        self.post.refresh_from_db()
        self.assertEqual(self.post.trang_thai, "an")
        log = NhatKyNghiepVu.objects.get(ma_tai_nguyen=str(self.post.pk))
        self.assertEqual(log.hanh_dong, "kiem_duyet_an_bai_viet")
        self.assertEqual(log.nguoi_dung_id, self.staff.pk)
        self.assertIn("không phù hợp", log.ly_do)

    def test_restore_soft_deleted_post_and_log(self):
        self._grant_moderation_permission()
        from django.utils import timezone
        self.post.da_xoa_mem = True
        self.post.ngay_xoa = timezone.now()
        self.post.nguoi_xoa = self.staff
        self.post.trang_thai = "an"
        self.post.save(update_fields=["da_xoa_mem", "ngay_xoa", "nguoi_xoa", "trang_thai", "ngay_cap_nhat"])
        self.client.force_login(self.staff)

        response = self._start_action("request_restore_selected")
        self.assertEqual(response.status_code, 302)
        restored = self.client.post(response["Location"], {
            "action": "restore", "post_ids": [str(self.post.pk)], "reason": "Đã kiểm tra và đủ điều kiện hiển thị."
        })
        self.assertEqual(restored.status_code, 302)
        self.post.refresh_from_db()
        self.assertFalse(self.post.da_xoa_mem)
        self.assertIsNone(self.post.ngay_xoa)
        self.assertIsNone(self.post.nguoi_xoa_id)
        self.assertEqual(self.post.trang_thai, "hien")
        log = NhatKyNghiepVu.objects.get(ma_tai_nguyen=str(self.post.pk))
        self.assertEqual(log.hanh_dong, "kiem_duyet_khoi_phuc_bai_viet")

    def test_protected_official_notice_cannot_be_hidden(self):
        self._grant_moderation_permission()
        protected = BaiViet.objects.create(
            nguoi_dang=self.staff,
            loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
            tieu_de="Nguồn thông báo chính thức",
            noi_dung="Không kiểm duyệt qua UC-SOC-10.",
            trang_thai="hien",
        )
        self.client.force_login(self.staff)
        response = self.client.post(self.changelist_url, {
            "action": "request_hide_selected",
            "_selected_action": [str(protected.pk)],
            "select_across": "0",
        })
        self.assertEqual(response.status_code, 302)
        confirm = self.client.get(response["Location"])
        self.assertEqual(confirm.status_code, 200)
        self.assertContains(confirm, "Nguồn được bảo vệ")
        blocked = self.client.post(response["Location"], {
            "action": "hide", "post_ids": [str(protected.pk)], "reason": "Kiểm tra quyền."
        })
        self.assertEqual(blocked.status_code, 400)
        protected.refresh_from_db()
        self.assertEqual(protected.trang_thai, "hien")
        self.assertFalse(NhatKyNghiepVu.objects.filter(ma_tai_nguyen=str(protected.pk)).exists())


class WorkflowAdminPageTests(TestCase):
    def test_staff_can_open_each_authorized_workflow_changelist(self):
        from django.contrib import admin
        from projectp.admin import WorkflowReadOnlyAdmin

        staff = get_user_model().objects.create_user(
            username="workflow-reader", password="test-password", is_staff=True
        )
        permissions = Permission.objects.filter(
            content_type__app_label="projectp", codename__startswith="view_"
        )
        staff.user_permissions.add(*permissions)
        self.client.force_login(staff)
        for model, model_admin in admin.site._registry.items():
            if isinstance(model_admin, WorkflowReadOnlyAdmin):
                with self.subTest(model=model._meta.label):
                    name = f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
