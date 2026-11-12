"""Hồi quy UC-COM-04 và UC-PRJ-04 khi đọc và tương tác theo ngữ cảnh."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projectp.models import (
    BaiViet, BaiVietDaLuu, BinhLuan, CamXuc, CommunityRole, CongDong, DuAn,
    MemberStatus, ProjectRole, ThanhVienCongDong, ThanhVienDuAn,
)


class PostContextNavigationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("context-member")
        self.other = get_user_model().objects.create_user("context-outsider")
        self.community = CongDong.objects.create(
            ten_cong_dong="Đo lường công nghiệp", nguoi_tao=self.user,
            pham_vi_truy_cap="thanh_vien",
        )
        self.membership = ThanhVienCongDong.objects.create(
            cong_dong=self.community, nguoi_dung=self.user, vai_tro=CommunityRole.OWNER,
        )
        project_community = CongDong.objects.create(
            ten_cong_dong="Cộng đồng dự án PLC", nguoi_tao=self.user,
            loai_cong_dong=CongDong.Type.PROJECT, quy_tac_tham_gia="theo_du_an",
            pham_vi_truy_cap="thanh_vien",
        )
        self.project = DuAn.objects.create(
            ma_du_an_nghiep_vu="DA-PLC", ten_du_an="Giám sát tủ điều khiển",
            cong_dong=project_community, nguoi_tao=self.user, ngay_bat_dau=date.today(),
        )
        self.project_membership = ThanhVienDuAn.objects.create(
            du_an=self.project, nguoi_dung=self.user, vai_tro=ProjectRole.MANAGER,
        )
        ThanhVienCongDong.objects.create(
            cong_dong=project_community, nguoi_dung=self.user, vai_tro=CommunityRole.OWNER,
        )
        self.post = BaiViet.objects.create(
            nguoi_dang=self.user, cong_dong=self.community,
            tieu_de="Đối chiếu kết quả đo", noi_dung="Nội dung cộng đồng",
        )
        self.project_post = BaiViet.objects.create(
            nguoi_dang=self.user, cong_dong=project_community, du_an=self.project,
            tieu_de="Thông tin bàn giao", noi_dung="Nội dung dự án",
        )
        self.issue = BaiViet.objects.create(
            nguoi_dang=self.user, cong_dong=project_community, du_an=self.project,
            tieu_de="Thiếu dữ liệu trước dao động", noi_dung="Cần đối chiếu tín hiệu",
            loai_bai_viet=BaiViet.Kind.FIELD_UPDATE, che_do_xu_ly=True,
            trang_thai_xu_ly=BaiViet.TechnicalStatus.OPEN, chua_giai_quyet_luc=timezone.now(),
        )
        self.legacy = BaiViet.objects.create(
            nguoi_dang=self.user, cong_dong=project_community,
            tieu_de="Bài cộng đồng dự án cũ", noi_dung="Dữ liệu chưa gắn mã dự án",
        )
        self.client.force_login(self.user)

    def detail(self, namespace, post):
        scope = self.community.pk if post == self.post else self.project.cong_dong_id
        if namespace == "projects":
            return reverse("projects:post_detail", args=[self.project.pk, post.pk])
        return reverse("communities:post", args=[scope, post.pk])

    def action(self, namespace, name, post):
        scope = self.project.pk if namespace == "projects" else post.cong_dong_id
        return reverse(namespace + ":" + name, args=[scope, post.pk])

    def token(self, namespace, post):
        response = self.client.get(self.detail(namespace, post))
        self.assertEqual(response.status_code, 200)
        return response.context["comment_form"]["request_token"].value()

    def test_community_title_opens_local_post_and_back_keeps_community(self):
        response = self.client.get(reverse("communities:detail", args=[self.community.pk]))
        self.assertContains(response, f'href="{self.detail("communities", self.post)}"')
        response = self.client.get(self.detail("communities", self.post))
        self.assertContains(response, "Gửi bình luận")
        self.assertContains(response, reverse("communities:detail", args=[self.community.pk]))
        self.assertNotContains(response, reverse("social:post_detail", args=[self.post.pk]))
        self.assertNotContains(response, reverse("social:comment_create", args=[self.post.pk]))

    def test_comments_replies_and_invalid_inputs_keep_each_module(self):
        for namespace, post in [("communities", self.post), ("projects", self.project_post)]:
            with self.subTest(namespace=namespace):
                token = self.token(namespace, post)
                url = self.action(namespace, "comment_create", post)
                data = {"request_token": token, "noi_dung": "Đã đối chiếu", "next": reverse("social:feed")}
                response = self.client.post(url, data)
                self.assertRedirects(response, self.detail(namespace, post) + "#comments", fetch_redirect_response=False)
                self.client.post(url, data)
                self.assertEqual(BinhLuan.objects.filter(bai_viet=post).count(), 1)
                parent = BinhLuan.objects.get(bai_viet=post)
                response = self.client.post(url, {
                    "request_token": self.token(namespace, post), "noi_dung": "Đã bổ sung",
                    "binh_luan_cha": parent.pk,
                })
                self.assertRedirects(response, self.detail(namespace, post) + "#comments", fetch_redirect_response=False)
                reply = BinhLuan.objects.get(binh_luan_cha=parent)
                self.assertEqual(reply.bai_viet_id, post.pk)
                response = self.client.post(url, {"request_token": self.token(namespace, post), "noi_dung": ""})
                self.assertRedirects(response, self.detail(namespace, post) + "#comments", fetch_redirect_response=False)

    def test_reaction_and_saved_actions_return_to_their_own_feed(self):
        for namespace, post, feed in [
            ("communities", self.post, reverse("communities:detail", args=[self.community.pk])),
            ("projects", self.project_post, reverse("projects:feed", args=[self.project.pk])),
        ]:
            with self.subTest(namespace=namespace):
                for action in ["reaction_set", "save_set"]:
                    response = self.client.post(self.action(namespace, action, post), {"state": "on", "next": feed})
                    self.assertRedirects(response, feed, fetch_redirect_response=False)
                    response = self.client.post(self.action(namespace, action, post), {
                        "state": "on", "next": "https://example.org/",
                    })
                    self.assertRedirects(response, self.detail(namespace, post), fetch_redirect_response=False)
                self.assertEqual(CamXuc.objects.filter(bai_viet=post).count(), 1)
                self.assertEqual(BaiVietDaLuu.objects.filter(bai_viet=post).count(), 1)

    def test_old_global_detail_links_open_the_correct_source(self):
        for post, namespace in [(self.post, "communities"), (self.project_post, "projects")]:
            response = self.client.get(reverse("social:post_detail", args=[post.pk]))
            self.assertRedirects(response, self.detail(namespace, post), fetch_redirect_response=False)

    def test_project_community_keeps_technical_post_reading_local(self):
        response = self.client.get(self.detail("communities", self.issue))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cần đối chiếu tín hiệu")
        self.assertNotContains(response, "Gửi bình luận")
        self.assertContains(response, "Mở xử lý trong dự án")
        response = self.client.post(self.action("communities", "comment_create", self.issue), {"noi_dung": "Vượt luồng"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BinhLuan.objects.filter(bai_viet=self.issue).exists())

    def test_legacy_project_community_posts_support_scoped_interactions(self):
        self.token("communities", self.legacy)
        response = self.client.post(self.action("communities", "reaction_set", self.legacy), {"state": "on"})
        self.assertRedirects(response, self.detail("communities", self.legacy), fetch_redirect_response=False)
        self.assertTrue(CamXuc.objects.filter(bai_viet=self.legacy).exists())

    def test_archived_project_and_its_community_are_read_only(self):
        token = self.token("projects", self.project_post)
        self.project.trang_thai = DuAn.Status.ARCHIVED
        self.project.luu_tru_luc = timezone.now()
        self.project.nguoi_luu_tru = self.user
        self.project.save()
        for namespace in ["projects", "communities"]:
            response = self.client.get(self.detail(namespace, self.project_post))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Gửi bình luận")
            for action in ["reaction_set", "comment_create"]:
                response = self.client.post(self.action(namespace, action, self.project_post), {
                    "state": "on", "noi_dung": "Không hợp lệ", "request_token": token,
                })
                self.assertEqual(response.status_code, 403)
        response = self.client.post(self.action("communities", "reaction_set", self.legacy), {"state": "on"})
        self.assertEqual(response.status_code, 403)

    def test_lost_membership_and_wrong_scope_cannot_modify_content(self):
        token = self.token("communities", self.post)
        self.membership.trang_thai = MemberStatus.SUSPENDED
        self.membership.save()
        response = self.client.post(self.action("communities", "comment_create", self.post), {
            "noi_dung": "Không được ghi", "request_token": token,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BinhLuan.objects.filter(bai_viet=self.post).exists())
        response = self.client.post(reverse("communities:reaction_set", args=[self.project.cong_dong_id, self.post.pk]), {"state": "on"})
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("projects:save_set", args=[self.project.pk, self.post.pk]), {"state": "on"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CamXuc.objects.filter(bai_viet=self.post).exists())

    def test_post_only_actions_reject_get_and_csrf_is_required(self):
        from django.test import Client

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        for namespace, post in [("communities", self.post), ("projects", self.project_post)]:
            for action in ["comment_create", "reaction_set", "save_set"]:
                url = self.action(namespace, action, post)
                self.assertEqual(self.client.get(url).status_code, 405)
                self.assertEqual(csrf_client.post(url, {"state": "on"}).status_code, 403)

    def test_same_post_uses_the_same_local_timestamp_in_both_spaces(self):
        community_response = self.client.get(self.detail("communities", self.project_post))
        project_response = self.client.get(self.detail("projects", self.project_post))
        stamp = timezone.localtime(self.project_post.ngay_tao).strftime("%d/%m/%Y %H:%M")
        self.assertContains(community_response, stamp)
        self.assertContains(project_response, stamp)

    def test_existing_global_interaction_can_return_to_its_original_page(self):
        response = self.client.post(reverse("social:reaction_set", args=[self.post.pk]), {
            "state": "on", "next": reverse("core:home"),
        })
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
