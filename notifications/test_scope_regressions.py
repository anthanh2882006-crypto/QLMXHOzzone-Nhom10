"""Thông báo theo cộng đồng phải giữ quyền dự án liên kết."""
import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projectp.models import (
    BaiViet, CongDong, DuAn, MemberStatus, ThanhVienCongDong,
    ThanhVienDuAn, ThongBaoChinhThuc, TieuChiThongBao,
)
from .permissions import can_read_notice, resolve_scope_user_ids


class ProjectCommunityNoticeScopeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user("notice-project-member")
        self.outsider = user_model.objects.create_user("notice-outside-project")
        self.community = CongDong.objects.create(
            ten_cong_dong="Cộng đồng dự án", nguoi_tao=self.member,
            loai_cong_dong=CongDong.Type.PROJECT, quy_tac_tham_gia="theo_du_an",
            pham_vi_truy_cap="noi_bo",
        )
        self.project = DuAn.objects.create(
            ma_du_an_nghiep_vu="NOTICE-PRJ", ten_du_an="Dự án thông báo",
            nguoi_tao=self.member, cong_dong=self.community, ngay_bat_dau=date.today(),
        )
        self.membership = ThanhVienDuAn.objects.create(du_an=self.project, nguoi_dung=self.member)
        ThanhVienCongDong.objects.create(cong_dong=self.community, nguoi_dung=self.member)
        post = BaiViet.objects.create(
            nguoi_dang=self.member, loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
            tieu_de="Thông báo riêng dự án", noi_dung="Thông tin thuộc dự án",
        )
        self.notice = ThongBaoChinhThuc.objects.create(
            bai_viet=post, nguoi_phu_trach=self.member, nguoi_xuat_ban=self.member,
            trang_thai="da_cong_bo", ngay_xuat_ban=timezone.now(), kiem_tra_luc=timezone.now(),
            khoa_yeu_cau_xuat_ban=uuid.uuid4(), che_do_doc="theo_tieu_chi",
        )
        self.criterion = TieuChiThongBao.objects.create(
            thong_bao=self.notice, muc_dich="doc", loai_tieu_chi="cong_dong", cong_dong=self.community,
        )

    def test_project_community_never_grants_company_wide_notice_access(self):
        self.assertTrue(can_read_notice(self.member, self.notice))
        self.assertFalse(can_read_notice(self.outsider, self.notice))
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("notifications:detail", args=[self.notice.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, self.notice.bai_viet.noi_dung, status_code=403)

    def test_stale_community_membership_does_not_grant_notice_read_or_distribution(self):
        self.membership.trang_thai = MemberStatus.SUSPENDED
        self.membership.save()
        self.assertFalse(can_read_notice(self.member, self.notice))
        recipients = resolve_scope_user_ids(scope="theo_tieu_chi", criteria=[self.criterion], purpose="phan_phoi")
        self.assertNotIn(self.member.pk, recipients)

    def test_general_internal_community_retains_company_wide_read_scope(self):
        general = CongDong.objects.create(ten_cong_dong="Cộng đồng chung", nguoi_tao=self.member, pham_vi_truy_cap="noi_bo")
        self.criterion.cong_dong = general
        self.criterion.save()
        self.assertTrue(can_read_notice(self.outsider, self.notice))
