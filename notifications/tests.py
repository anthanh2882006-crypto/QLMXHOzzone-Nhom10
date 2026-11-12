import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from projectp.models import (
    BaiViet,
    HoSoNhanVien,
    NguoiNhanThongBao,
    PhongBan,
    TieuChiThongBao,
    ThongBaoChinhThuc,
    ThongBaoHeThong,
    ViTriCongViec,
)

from .permissions import can_publish_notices, can_track_notice
from .services import acknowledge_notice, publish_notice, save_notice_draft


class OfficialNoticePublishingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="notice-publisher", password="test-password")
        self.other_user = User.objects.create_user(username="notice-recipient", password="test-password")
        self.department = PhongBan.objects.create(
            ma_nghiep_vu="PB-TEST", ten_phong_ban="Phòng thử nghiệm"
        )
        self.other_department = PhongBan.objects.create(
            ma_nghiep_vu="PB-OTHER", ten_phong_ban="Phòng khác"
        )
        self.position = ViTriCongViec.objects.create(
            ma_nghiep_vu="VT-TEST", ten_vi_tri="Nhân viên thử nghiệm"
        )
        HoSoNhanVien.objects.create(
            nguoi_dung=self.user,
            phong_ban=self.department,
            vi_tri=self.position,
            ma_nhan_vien="NV-TEST-SOC06",
            bat_buoc_doi_mat_khau=False,
        )
        HoSoNhanVien.objects.create(
            nguoi_dung=self.other_user,
            phong_ban=self.other_department,
            vi_tri=self.position,
            ma_nhan_vien="NV-OTHER-SOC06",
            bat_buoc_doi_mat_khau=False,
        )

    def _grant_publish_permission(self):
        content_type = ContentType.objects.get_for_model(ThongBaoChinhThuc)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="cong_bo_thong_bao",
        )
        self.user.user_permissions.add(permission)
        self.user = get_user_model().objects.get(pk=self.user.pk)

    def _draft(self, *, title="Thông báo kiểm thử UC-SOC-06", ack=False):
        post = BaiViet(
            nguoi_dang=self.user,
            loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
            tieu_de=title,
            noi_dung="Nội dung thông báo kiểm thử.",
            trang_thai="an",
        )
        post.full_clean()
        post.save()
        notice = ThongBaoChinhThuc(
            bai_viet=post,
            nguoi_phu_trach=self.user,
            che_do_doc="toan_cong_ty",
            che_do_phan_phoi="toan_cong_ty",
            yeu_cau_xac_nhan=ack,
            trang_thai="ban_nhap",
        )
        notice.full_clean()
        notice.save()
        return notice

    def test_user_without_publish_permission_is_denied(self):
        self.assertFalse(can_publish_notices(self.user))
        notice = self._draft()
        with self.assertRaises(PermissionDenied):
            publish_notice(notice_id=notice.pk, user=self.user, request_key=uuid.uuid4())

    def test_publish_without_ack_creates_unique_actual_recipient_set_and_is_idempotent(self):
        self._grant_publish_permission()
        notice = self._draft(ack=False)
        request_key = uuid.uuid4()

        published, created = publish_notice(
            notice_id=notice.pk,
            user=self.user,
            request_key=request_key,
        )
        self.assertTrue(created)
        self.assertEqual(published.trang_thai, "da_cong_bo")
        self.assertIsNotNone(published.ngay_xuat_ban)
        self.assertEqual(NguoiNhanThongBao.objects.filter(thong_bao=published).count(), 2)
        self.assertEqual(
            NguoiNhanThongBao.objects.filter(thong_bao=published)
            .values("nguoi_dung_id").distinct().count(),
            2,
        )
        self.assertFalse(
            NguoiNhanThongBao.objects.filter(thong_bao=published, bat_buoc_xac_nhan=True).exists()
        )
        self.assertEqual(
            ThongBaoHeThong.objects.filter(
                bai_viet=published.bai_viet,
                loai_thong_bao="thong_bao_chinh_thuc",
            ).count(),
            2,
        )

        retried, created_again = publish_notice(
            notice_id=notice.pk,
            user=self.user,
            request_key=request_key,
        )
        self.assertFalse(created_again)
        self.assertEqual(retried.pk, published.pk)
        self.assertEqual(NguoiNhanThongBao.objects.filter(thong_bao=published).count(), 2)
        self.assertEqual(ThongBaoHeThong.objects.filter(bai_viet=published.bai_viet).count(), 2)

    def test_publish_with_ack_creates_pending_ack_rows(self):
        self._grant_publish_permission()
        notice = self._draft(ack=True)
        published, created = publish_notice(
            notice_id=notice.pk,
            user=self.user,
            request_key=uuid.uuid4(),
        )
        self.assertTrue(created)
        recipients = NguoiNhanThongBao.objects.filter(thong_bao=published)
        self.assertEqual(recipients.count(), 2)
        self.assertEqual(recipients.filter(bat_buoc_xac_nhan=True).count(), 2)
        self.assertEqual(recipients.filter(trang_thai_tiep_nhan="chua_xac_nhan", ngay_xac_nhan__isnull=True).count(), 2)

    def test_b3_rejects_distribution_outside_read_scope_before_saving_invalid_draft(self):
        self._grant_publish_permission()
        cleaned = {
            "tieu_de": "Thông báo giới hạn phòng ban",
            "noi_dung": "Nội dung chỉ được phân phối trong phạm vi có quyền đọc.",
            "che_do_doc": "theo_tieu_chi",
            "doc_phong_ban": [self.department],
            "doc_cong_dong": [],
            "doc_du_an": [],
            "doc_nguoi_dung": [],
            "che_do_phan_phoi": "theo_tieu_chi",
            "phan_phoi_phong_ban": [],
            "phan_phoi_cong_dong": [],
            "phan_phoi_du_an": [],
            "phan_phoi_nguoi_dung": [self.other_user],
            "yeu_cau_xac_nhan": False,
            "thong_bao_tham_chieu": None,
            "remove_attachment_ids": [],
        }
        with self.assertRaises(ValidationError):
            save_notice_draft(user=self.user, cleaned=cleaned)
        self.assertFalse(ThongBaoChinhThuc.objects.exists())
        self.assertFalse(BaiViet.objects.filter(loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT).exists())

    def test_recipient_outside_read_scope_is_rejected_and_draft_is_preserved(self):
        self._grant_publish_permission()
        notice = self._draft()
        notice.che_do_doc = "theo_tieu_chi"
        notice.che_do_phan_phoi = "theo_tieu_chi"
        notice.save(update_fields=["che_do_doc", "che_do_phan_phoi", "ngay_cap_nhat"])
        TieuChiThongBao.objects.create(
            thong_bao=notice,
            muc_dich="doc",
            loai_tieu_chi="phong_ban",
            phong_ban=self.department,
        )
        TieuChiThongBao.objects.create(
            thong_bao=notice,
            muc_dich="phan_phoi",
            loai_tieu_chi="nguoi_dung",
            nguoi_dung=self.other_user,
        )

        with self.assertRaises(ValidationError):
            publish_notice(notice_id=notice.pk, user=self.user, request_key=uuid.uuid4())

        notice.refresh_from_db()
        self.assertEqual(notice.trang_thai, "ban_nhap")
        self.assertFalse(NguoiNhanThongBao.objects.filter(thong_bao=notice).exists())
        self.assertFalse(ThongBaoHeThong.objects.filter(bai_viet=notice.bai_viet).exists())

    def test_published_notice_cannot_be_edited_as_a_draft(self):
        self._grant_publish_permission()
        notice = self._draft()
        published, _ = publish_notice(
            notice_id=notice.pk,
            user=self.user,
            request_key=uuid.uuid4(),
        )
        cleaned = {
            "tieu_de": "Nội dung sửa đè",
            "noi_dung": "Không được phép sửa thông báo đã công bố.",
            "che_do_doc": "toan_cong_ty",
            "che_do_phan_phoi": "toan_cong_ty",
            "yeu_cau_xac_nhan": False,
        }
        with self.assertRaises(PermissionDenied):
            save_notice_draft(user=self.user, cleaned=cleaned, notice=published)

        published.bai_viet.refresh_from_db()
        self.assertEqual(published.bai_viet.tieu_de, "Thông báo kiểm thử UC-SOC-06")

    def _grant_track_permission(self):
        content_type = ContentType.objects.get_for_model(ThongBaoChinhThuc)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="theo_doi_tiep_nhan",
        )
        self.user.user_permissions.add(permission)
        self.user = get_user_model().objects.get(pk=self.user.pk)

    def test_acknowledgement_is_explicit_and_idempotent(self):
        self._grant_publish_permission()
        notice = self._draft(ack=True)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        recipient = NguoiNhanThongBao.objects.get(
            thong_bao=published, nguoi_dung=self.other_user
        )
        self.assertEqual(recipient.trang_thai_tiep_nhan, "chua_xac_nhan")
        self.assertIsNone(recipient.ngay_xac_nhan)

        first, created = acknowledge_notice(notice_id=published.pk, user=self.other_user)
        self.assertTrue(created)
        self.assertEqual(first.trang_thai_tiep_nhan, "da_xac_nhan")
        self.assertIsNotNone(first.ngay_xac_nhan)
        first_time = first.ngay_xac_nhan

        second, created_again = acknowledge_notice(notice_id=published.pk, user=self.other_user)
        self.assertFalse(created_again)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.ngay_xac_nhan, first_time)
        self.assertEqual(
            NguoiNhanThongBao.objects.filter(
                thong_bao=published, nguoi_dung=self.other_user,
                trang_thai_tiep_nhan="da_xac_nhan",
            ).count(),
            1,
        )

    def test_no_ack_notice_cannot_be_acknowledged(self):
        self._grant_publish_permission()
        notice = self._draft(ack=False)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        with self.assertRaises(PermissionDenied):
            acknowledge_notice(notice_id=published.pk, user=self.other_user)
        self.assertEqual(
            NguoiNhanThongBao.objects.get(thong_bao=published, nguoi_dung=self.other_user)
            .trang_thai_tiep_nhan,
            "chua_xac_nhan",
        )

    def test_acknowledgement_is_denied_after_read_access_is_removed(self):
        self._grant_publish_permission()
        notice = self._draft(ack=True)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        published.che_do_doc = "theo_tieu_chi"
        published.save(update_fields=["che_do_doc", "ngay_cap_nhat"])
        TieuChiThongBao.objects.create(
            thong_bao=published,
            muc_dich="doc",
            loai_tieu_chi="nguoi_dung",
            nguoi_dung=self.user,
        )
        with self.assertRaises(PermissionDenied):
            acknowledge_notice(notice_id=published.pk, user=self.other_user)
        self.assertEqual(
            NguoiNhanThongBao.objects.get(thong_bao=published, nguoi_dung=self.other_user)
            .trang_thai_tiep_nhan,
            "chua_xac_nhan",
        )

    def test_tracking_requires_the_dedicated_internal_distribution_permission(self):
        self._grant_publish_permission()
        notice = self._draft(ack=True)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        self._grant_track_permission()
        self.assertTrue(can_track_notice(self.user, published))

        other_content_type = ContentType.objects.get_for_model(ThongBaoChinhThuc)
        track_permission = Permission.objects.get(
            content_type=other_content_type, codename="theo_doi_tiep_nhan"
        )
        self.other_user.user_permissions.add(track_permission)
        self.other_user.refresh_from_db()
        self.assertTrue(can_track_notice(self.other_user, published))

    def test_tracking_view_returns_actual_recipient_set_and_search_filter(self):
        self._grant_publish_permission()
        self._grant_track_permission()
        notice = self._draft(ack=True)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        self.client.force_login(self.user)
        response = self.client.get(
            f"/notifications/{published.pk}/theo-doi/?q=notice-recipient&status=pending"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tracking"]["total"], 2)
        self.assertEqual(len(response.context["recipient_rows"]), 1)
        self.assertEqual(response.context["recipient_rows"][0].nguoi_dung_id, self.other_user.pk)

    def test_ack_confirmation_view_requires_explicit_post(self):
        self._grant_publish_permission()
        notice = self._draft(ack=True)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        self.client.force_login(self.other_user)
        detail = self.client.get(f"/notifications/{published.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["recipient"].trang_thai_tiep_nhan, "chua_xac_nhan")

        confirm = self.client.get(f"/notifications/{published.pk}/xac-nhan/")
        self.assertEqual(confirm.status_code, 200)
        self.assertContains(confirm, "Xác nhận không thể tự hủy")
        self.assertEqual(
            NguoiNhanThongBao.objects.get(thong_bao=published, nguoi_dung=self.other_user)
            .trang_thai_tiep_nhan,
            "chua_xac_nhan",
        )

        posted = self.client.post(f"/notifications/{published.pk}/xac-nhan/")
        self.assertEqual(posted.status_code, 302)
        self.assertIn("ack=done", posted["Location"])
        recipient = NguoiNhanThongBao.objects.get(thong_bao=published, nguoi_dung=self.other_user)
        self.assertEqual(recipient.trang_thai_tiep_nhan, "da_xac_nhan")

    def test_tracking_permission_does_not_require_read_audience_membership(self):
        self._grant_publish_permission()
        self._grant_track_permission()
        notice = self._draft(ack=True)
        published, _ = publish_notice(
            notice_id=notice.pk, user=self.user, request_key=uuid.uuid4()
        )
        published.che_do_doc = "theo_tieu_chi"
        published.save(update_fields=["che_do_doc", "ngay_cap_nhat"])
        TieuChiThongBao.objects.create(
            thong_bao=published,
            muc_dich="doc",
            loai_tieu_chi="nguoi_dung",
            nguoi_dung=self.other_user,
        )
        self.client.force_login(self.user)
        listing = self.client.get("/notifications/")
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Theo dõi tiếp nhận")
        self.assertNotContains(listing, "Nội dung thông báo kiểm thử.")

        report = self.client.get(f"/notifications/{published.pk}/theo-doi/")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.context["tracking"]["total"], 2)
        self.assertEqual(report.context["tracking"]["pending_lost"], 1)
        self.assertEqual(report.context["tracking"]["pending_current"], 1)
        detail = self.client.get(f"/notifications/{published.pk}/")
        self.assertEqual(detail.status_code, 403)

