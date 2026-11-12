"""Các tình huống sai được đối chiếu UC-COM-02/03/04/06/07 trong báo cáo."""
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone

from projectp.models import (
    BaiViet, CommunityRole, CongDong, DuAn, MemberStatus, NhatKyNghiepVu,
    PhuongAnXuLy, ThanhVienCongDong, ThanhVienDuAn, YeuCauThamGia,
)
from .tests import Base


class CommunityRegressionTests(Base):
    def project(self):
        community = CongDong.objects.create(ten_cong_dong="Dự án kín", nguoi_tao=self.owner,
            loai_cong_dong="du_an", quy_tac_tham_gia="theo_du_an", pham_vi_truy_cap="thanh_vien")
        project = DuAn.objects.create(cong_dong=community, nguoi_tao=self.owner,
            ma_du_an_nghiep_vu="PRJ", ten_du_an="Dự án", ngay_bat_dau=timezone.localdate())
        for user, role in [(self.owner, "quan_ly"), (self.alice, "thanh_vien")]:
            ThanhVienDuAn.objects.create(du_an=project, nguoi_dung=user, vai_tro=role)
            ThanhVienCongDong.objects.create(cong_dong=community, nguoi_dung=user,
                vai_tro=CommunityRole.OWNER if user == self.owner else CommunityRole.MEMBER)
        return project

    def test_invalid_join_reason_is_kept(self):
        response = self.post_as(self.alice, "join", [self.kin.pk], {"loi_nhan": "x" * 501})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["join_form"].errors)
        self.assertEqual(response.context["join_form"]["loi_nhan"].value(), "x" * 501)
        self.assertFalse(YeuCauThamGia.objects.filter(nguoi_dung=self.alice).exists())

    def test_join_rolls_back_when_audit_fails(self):
        with patch("communities.views.uc_com_02_tham_gia.ghi_nhat_ky", side_effect=DatabaseError("fault")):
            response = self.post_as(self.alice, "join", [self.mo.pk])
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.la_thanh_vien(self.alice, self.mo))
        self.post_as(self.alice, "join", [self.mo.pk])
        self.assertTrue(self.la_thanh_vien(self.alice, self.mo))

    def test_decision_rolls_back_membership_and_request(self):
        request = YeuCauThamGia.objects.create(cong_dong=self.kin, nguoi_dung=self.alice)
        with patch("communities.views.uc_com_02_tham_gia.ghi_nhat_ky", side_effect=DatabaseError("fault")):
            response = self.post_as(self.owner, "decide", [request.pk], {"decision": "approve"})
        self.assertEqual(response.status_code, 503)
        request.refresh_from_db()
        self.assertEqual(request.trang_thai, "cho_duyet")
        self.assertFalse(self.la_thanh_vien(self.alice, self.kin))

    def test_inactive_applicant_is_not_approved(self):
        request = YeuCauThamGia.objects.create(cong_dong=self.kin, nguoi_dung=self.alice)
        self.alice.is_active = False
        self.alice.save()
        self.post_as(self.owner, "decide", [request.pk], {"decision": "approve"})
        request.refresh_from_db()
        self.assertEqual(request.trang_thai, "cho_duyet")
        self.assertFalse(self.la_thanh_vien(self.alice, self.kin))

    def test_project_request_cannot_bypass_project_membership(self):
        project = self.project()
        request = YeuCauThamGia.objects.create(cong_dong=project.cong_dong, nguoi_dung=self.bob)
        self.post_as(self.owner, "decide", [request.pk], {"decision": "approve"})
        request.refresh_from_db()
        self.assertEqual(request.trang_thai, "cho_duyet")
        self.assertFalse(self.la_thanh_vien(self.bob, project.cong_dong))

    def test_community_membership_alone_cannot_read_project(self):
        project = self.project()
        ThanhVienDuAn.objects.filter(du_an=project, nguoi_dung=self.alice).update(
            trang_thai=MemberStatus.ENDED, ket_thuc_luc=timezone.now())
        self.client.force_login(self.alice)
        response = self.client.get(reverse("communities:detail", args=[project.cong_dong_id]))
        self.assertEqual(response.status_code, 404)

    def test_leave_is_atomic(self):
        self.post_as(self.alice, "join", [self.mo.pk])
        with patch("communities.views.uc_com_03_roi.ghi_nhat_ky", side_effect=DatabaseError("fault")):
            response = self.post_as(self.alice, "leave", [self.mo.pk])
        self.assertEqual(response.status_code, 503)
        self.assertTrue(self.la_thanh_vien(self.alice, self.mo))

    def test_owner_transfer_is_atomic(self):
        recipient = ThanhVienCongDong.objects.get(cong_dong=self.kin, nguoi_dung=self.mod)
        with patch("communities.views.uc_com_07_quan_tri.ghi_nhat_ky", side_effect=DatabaseError("fault")):
            response = self.post_as(self.owner, "transfer", [self.kin.pk], {"member_id": recipient.pk, "confirm": "1"})
        self.assertEqual(response.status_code, 503)
        recipient.refresh_from_db()
        self.assertEqual(recipient.vai_tro, CommunityRole.MODERATOR)
        self.assertEqual(ThanhVienCongDong.objects.get(cong_dong=self.kin, nguoi_dung=self.owner).vai_tro, CommunityRole.OWNER)

    def test_project_owner_transfer_keeps_project_roles(self):
        project = self.project()
        recipient = ThanhVienCongDong.objects.get(cong_dong=project.cong_dong, nguoi_dung=self.alice)
        response = self.post_as(self.owner, "transfer", [project.cong_dong_id], {"member_id": recipient.pk, "confirm": "1"})
        self.assertEqual(response.status_code, 302)
        recipient.refresh_from_db()
        self.assertEqual(recipient.vai_tro, CommunityRole.OWNER)
        self.assertEqual(ThanhVienDuAn.objects.get(du_an=project, nguoi_dung=self.owner).vai_tro, "quan_ly")
        self.assertEqual(ThanhVienDuAn.objects.get(du_an=project, nguoi_dung=self.alice).vai_tro, "thanh_vien")

    def test_bad_transfer_ids_do_not_raise_server_error(self):
        for value in ["abc", "9999999999999999999", "²", "-1"]:
            with self.subTest(value=value):
                response = self.post_as(self.owner, "transfer", [self.kin.pk], {"member_id": value, "confirm": "1"})
                self.assertEqual(response.status_code, 302)

    def test_protected_source_cannot_be_hidden(self):
        post = BaiViet.objects.create(cong_dong=self.kin, nguoi_dang=self.owner, noi_dung="Nguồn")
        PhuongAnXuLy.objects.create(bai_viet=post, nguoi_de_xuat=self.owner, noi_dung_phuong_an="Phương án", co_so_de_xuat="Căn cứ")
        self.post_as(self.owner, "moderate", [self.kin.pk, post.pk], {"action": "hide"})
        post.refresh_from_db()
        self.assertEqual(post.trang_thai, "hien")

    def test_moderation_rolls_back_and_retry_is_idempotent(self):
        post = BaiViet.objects.create(cong_dong=self.kin, nguoi_dang=self.owner, noi_dung="Bài")
        with patch("communities.views.uc_com_07_quan_tri.ghi_nhat_ky", side_effect=DatabaseError("fault")):
            response = self.post_as(self.owner, "moderate", [self.kin.pk, post.pk], {"action": "hide"})
        self.assertEqual(response.status_code, 503)
        post.refresh_from_db()
        self.assertEqual(post.trang_thai, "hien")
        self.post_as(self.owner, "moderate", [self.kin.pk, post.pk], {"action": "hide"})
        count = NhatKyNghiepVu.objects.count()
        self.post_as(self.owner, "moderate", [self.kin.pk, post.pk], {"action": "hide"})
        self.assertEqual(NhatKyNghiepVu.objects.count(), count)

    def test_archived_project_blocks_community_writes(self):
        project = self.project()
        post = BaiViet.objects.create(cong_dong=project.cong_dong, du_an=project, nguoi_dang=self.owner, noi_dung="Bài")
        DuAn.objects.filter(pk=project.pk).update(trang_thai=DuAn.Status.ARCHIVED,
            luu_tru_luc=timezone.now(), nguoi_luu_tru=self.owner)
        self.post_as(self.owner, "moderate", [project.cong_dong_id, post.pk], {"action": "hide"})
        post.refresh_from_db()
        self.assertEqual(post.trang_thai, "hien")
        self.post_as(self.owner, "post_create", [project.cong_dong_id], {"noi_dung": "Không được lưu"})
        self.assertFalse(BaiViet.objects.filter(noi_dung="Không được lưu").exists())

    def test_file_content_must_match_extension(self):
        response = self.post_as(self.owner, "post_create", [self.kin.pk], {
            "noi_dung": "Giữ nội dung", "tep": SimpleUploadedFile("anh.png", b"not a png", content_type="image/png")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(BaiViet.objects.filter(noi_dung="Giữ nội dung").exists())

    def test_partial_file_write_is_cleaned(self):
        original_save = default_storage.save
        stored = []
        def fail_after_write(name, content, **kwargs):
            stored.append(original_save(name, content, **kwargs))
            raise OSError("fault")
        with patch.object(default_storage, "save", side_effect=fail_after_write):
            response = self.post_as(self.owner, "post_create", [self.kin.pk], {
                "noi_dung": "Giữ nội dung", "tep": SimpleUploadedFile("ghi-chu.txt", b"valid text")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(stored)
        self.assertFalse(default_storage.exists(stored[0]))
        self.assertFalse(BaiViet.objects.filter(noi_dung="Giữ nội dung").exists())

    def test_comment_navigation_is_available(self):
        post = BaiViet.objects.create(cong_dong=self.kin, nguoi_dang=self.owner, noi_dung="Bài")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("communities:post", args=[self.kin.pk, post.pk]))
        self.assertContains(response, reverse("social:post_detail", args=[post.pk]))
