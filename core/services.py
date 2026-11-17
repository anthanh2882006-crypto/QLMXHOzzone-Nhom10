"""Permission-aware homepage queries for OZZONE.

Only existing projectp models and the configured Django user model are used.
This module intentionally does not introduce homepage-specific database tables.
"""
from accounts.views._chung import ho_ten
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from django.urls import reverse
from projects.permissions import active_memberships, can_resolve, readable_projects
from social.permissions import accessible_posts

from projectp.models import (
    CongDong,
    HoSoNhanVien,
    KetQuaThu,
    LanThuPhuongAn,
    NguoiNhanThongBao,
    ThanhVienCongDong,
    ThongBaoChinhThuc,
    TieuChiThongBao,
)

ACTIVE = "hoat_dong"
VISIBLE_POST = "hien"
PUBLISHED = "da_cong_bo"


def _profile_for(user):
    return (
        HoSoNhanVien.objects.select_related("phong_ban", "vi_tri")
        .filter(nguoi_dung=user)
        .first()
    )


def _memberships_for(user):
    project_memberships = list(
        active_memberships(user).select_related("du_an")
        .filter(
            nguoi_dung=user,
            trang_thai=ACTIVE,
            ket_thuc_luc__isnull=True,
            du_an_id__in=readable_projects(user).values("pk"),
        )
        .order_by("du_an__ten_du_an")
    )
    community_memberships = list(
        ThanhVienCongDong.objects.select_related("cong_dong")
        .filter(
            nguoi_dung=user,
            trang_thai=ACTIVE,
            ket_thuc_luc__isnull=True,
            cong_dong__da_xoa_mem=False,
        )
        .filter(Q(cong_dong__loai_cong_dong="chung") | Q(cong_dong_id__in=readable_projects(user).values("cong_dong_id")))
        .order_by("cong_dong__ten_cong_dong")
    )
    project_ids = {membership.du_an_id for membership in project_memberships}
    member_community_ids = {membership.cong_dong_id for membership in community_memberships}

    # Company-internal communities are visible to active employees. A
    # members-only community is visible only to users with active membership.
    internal_community_ids = set(
        CongDong.objects.filter(
            da_xoa_mem=False,
            pham_vi_truy_cap="noi_bo",
            loai_cong_dong="chung",
        ).values_list("ma_cong_dong", flat=True)
    )
    readable_community_ids = member_community_ids | internal_community_ids

    return {
        "project_memberships": project_memberships,
        "community_memberships": community_memberships,
        "project_ids": project_ids,
        "member_community_ids": member_community_ids,
        "readable_community_ids": readable_community_ids,
    }


def _post_scope_filter(scope):
    """Company posts plus posts whose current community/project scopes are readable."""
    project_ids = scope["project_ids"]
    community_ids = scope["readable_community_ids"]

    return (
        Q(cong_dong__isnull=True, du_an__isnull=True)
        | Q(cong_dong_id__in=community_ids, du_an__isnull=True)
        # Project membership grants access to project-scoped posts, including
        # project posts that also reference the project's linked community.
        | Q(du_an_id__in=project_ids)
    )


def _notice_is_readable(notice, user, profile, scope):
    from notifications.permissions import can_read_notice
    return can_read_notice(user, notice)


def _readable_official_notices(user, profile, scope):
    criteria_qs = TieuChiThongBao.objects.filter(muc_dich="doc").select_related(
        "phong_ban", "cong_dong", "du_an", "nguoi_dung"
    )
    recipient_qs = NguoiNhanThongBao.objects.filter(nguoi_dung=user)
    notices = (
        ThongBaoChinhThuc.objects.select_related("bai_viet", "nguoi_phu_trach", "nguoi_xuat_ban")
        .prefetch_related(
            Prefetch("tieu_chi", queryset=criteria_qs, to_attr="_all_read_criteria"),
            Prefetch("nguoi_nhan", queryset=recipient_qs, to_attr="_current_user_recipients"),
        )
        .filter(
            trang_thai=PUBLISHED,
            ngay_xuat_ban__lte=timezone.now(),
            bai_viet__trang_thai=VISIBLE_POST,
            bai_viet__da_xoa_mem=False,
        )
        .order_by("-ngay_xuat_ban", "-bai_viet_id")
    )

    readable = []
    for notice in notices:
        notice.home_read_criteria = notice._all_read_criteria
        if not _notice_is_readable(notice, user, profile, scope):
            continue
        recipients = notice._current_user_recipients
        notice.home_recipient = recipients[0] if recipients else None
        publisher_profile = _profile_for(notice.nguoi_xuat_ban) if notice.nguoi_xuat_ban_id else None
        notice.home_publisher_department = (
            publisher_profile.phong_ban.ten_phong_ban if publisher_profile else "OZZONE"
        )
        readable.append(notice)
        if len(readable) >= 4:
            break
    return readable


def _task_items(user, profile, scope):
    items = []

    # A trial assigned to this employee and still waiting for an actual result.
    trials = (
        LanThuPhuongAn.objects.select_related(
            "phuong_an", "phuong_an__bai_viet", "phuong_an__bai_viet__du_an"
        )
        .filter(
            nguoi_thuc_hien=user,
            trang_thai__in=["cho_ket_qua", "dang_thuc_hien"],
            ket_thuc_luc__isnull=True,
            phuong_an__bai_viet__da_xoa_mem=False,
            phuong_an__bai_viet__trang_thai=VISIBLE_POST,
            phuong_an__bai_viet__du_an_id__in=scope["project_ids"],
            phuong_an__bai_viet__du_an__trang_thai="dang_thuc_hien",
        )
        .filter(ket_qua__isnull=True)
        .order_by("ngay_thu")[:4]
    )
    for trial in trials:
        issue = trial.phuong_an.bai_viet
        items.append({
            "type": "result",
            "title": "Ghi nhận kết quả thực tế",
            "subtitle": f"Phương án #{trial.phuong_an_id} · {issue.du_an.ten_du_an if issue.du_an_id else 'Dự án'}",
            "detail": issue.tieu_de or issue.noi_dung[:110],
            "created_at": trial.ngay_thu,
            "object_id": issue.pk,
            "url": reverse("projects:result_create", kwargs={"pk": issue.du_an_id, "target": trial.pk}),
            "status": "Chờ kết quả",
        })

    from knowledge.uc04_views import _queue_for_user

    reviews = _queue_for_user(user).filter(
        trang_thai__in=["cho_danh_gia", "cho_danh_gia_lai"],
    ).exclude(bai_viet_nguon__du_an__trang_thai="luu_tru").order_by("ngay_tao")[:3]
    for review in reviews:
        items.append({
            "type": "knowledge",
            "title": "Đánh giá bài học kinh nghiệm",
            "subtitle": review.bai_viet_nguon.du_an.ten_du_an,
            "detail": review.bai_viet_nguon.tieu_de or review.bai_viet_nguon.noi_dung[:110],
            "created_at": review.ngay_tao,
            "object_id": review.bai_viet_nguon_id,
            "url": reverse("knowledge:normalize_lesson", kwargs={"pk": review.pk}),
            "status": "Chờ đánh giá",
        })

    # UC-PRJ-09 dành cho thành viên dự án có quyền đọc nguồn và căn cứ hợp lệ.
    if scope["project_ids"]:
        successful_results = (
            KetQuaThu.objects.select_related(
                "lan_thu", "lan_thu__phuong_an", "lan_thu__phuong_an__bai_viet",
                "lan_thu__phuong_an__bai_viet__du_an",
            )
            .filter(
                thanh_cong=True,
                lan_thu__phuong_an__bai_viet__du_an_id__in=scope["project_ids"],
                lan_thu__phuong_an__bai_viet__du_an__trang_thai="dang_thuc_hien",
                lan_thu__phuong_an__bai_viet__da_xoa_mem=False,
                lan_thu__phuong_an__bai_viet__trang_thai=VISIBLE_POST,
                lan_thu__phuong_an__bai_viet__che_do_xu_ly=True,
                lan_thu__phuong_an__bai_viet__trang_thai_xu_ly="chua_giai_quyet",
                lan_thu__phuong_an__bai_viet__ket_luan_xu_ly__isnull=True,
            )
            .order_by("-hoan_tat_luc")[:3]
        )
        for result in successful_results:
            issue = result.lan_thu.phuong_an.bai_viet
            if not can_resolve(user, issue.du_an):
                continue
            items.append({
                "type": "conclusion",
                "title": "Đề nghị kết luận xử lý",
                "subtitle": "Nguồn đã có kết quả thành công",
                "detail": issue.tieu_de or issue.noi_dung[:110],
                "created_at": result.hoan_tat_luc,
                "object_id": issue.pk,
                "url": reverse("projects:resolution_create", kwargs={"pk": issue.du_an_id, "post_id": issue.pk}),
                "status": "Có thể đề nghị",
            })

    # ACK is actionable only for members of the immutable recipient set who
    # still satisfy the current read rule. Reading alone never creates an ACK.
    ack_rows = (
        NguoiNhanThongBao.objects.select_related("thong_bao", "thong_bao__bai_viet")
        .filter(
            nguoi_dung=user,
            bat_buoc_xac_nhan=True,
            trang_thai_tiep_nhan="chua_xac_nhan",
            ngay_xac_nhan__isnull=True,
            thong_bao__trang_thai=PUBLISHED,
            thong_bao__bai_viet__trang_thai=VISIBLE_POST,
            thong_bao__bai_viet__da_xoa_mem=False,
        )
        .order_by("ngay_phan_phoi")
    )
    for recipient in ack_rows:
        notice = recipient.thong_bao
        notice.home_read_criteria = list(
            TieuChiThongBao.objects.filter(thong_bao=notice, muc_dich="doc").select_related(
                "phong_ban", "cong_dong", "du_an", "nguoi_dung"
            )
        )
        if not _notice_is_readable(notice, user, profile, scope):
            continue
        items.append({
            "type": "ack",
            "title": "Xác nhận tiếp nhận thông báo",
            "subtitle": notice.bai_viet.tieu_de,
            "detail": notice.bai_viet.noi_dung[:110],
            "created_at": recipient.ngay_phan_phoi,
            "object_id": notice.pk,
            "status": "Cần xác nhận",
        })

    priority = {"result": 0, "conclusion": 1, "ack": 2, "knowledge": 3}
    items.sort(key=lambda item: (priority.get(item["type"], 9), item["created_at"] or timezone.now()))
    return items[:2]


def _recent_work(project_memberships, issue_posts, lessons):
    rows = []
    for membership in project_memberships:
        project = membership.du_an
        rows.append({
            "title": project.ten_du_an,
            "kind": "Dự án",
            "updated_at": project.ngay_cap_nhat,
            "meta": project.get_trang_thai_display(),
        })
    for issue in issue_posts:
        rows.append({
            "title": issue.tieu_de or issue.noi_dung[:70],
            "kind": "Vấn đề",
            "updated_at": issue.ngay_cap_nhat,
            "meta": issue.du_an.ten_du_an if issue.du_an_id else "Bảng tin công ty",
        })
    for lesson in lessons:
        rows.append({
            "title": lesson.tieu_de,
            "kind": "Tri thức",
            "updated_at": lesson.ngay_luu_tri_thuc,
            "meta": (
                "Nội bộ OZZONE"
                if lesson.pham_vi_chia_se == "noi_bo"
                else lesson.phan_cong.du_an.ten_du_an
            ),
        })
    rows.sort(key=lambda row: row["updated_at"] or timezone.now(), reverse=True)
    return rows[:3]


def build_home_context(user):
    profile = _profile_for(user)
    scope = _memberships_for(user)
    project_memberships = scope["project_memberships"]
    community_memberships = scope["community_memberships"]

    community_rows = (
        CongDong.objects.filter(
            ma_cong_dong__in=[membership.cong_dong_id for membership in community_memberships],
            da_xoa_mem=False,
        )
        .annotate(
            home_member_count=Count(
                "thanh_vien",
                filter=Q(thanh_vien__trang_thai=ACTIVE, thanh_vien__ket_thuc_luc__isnull=True),
                distinct=True,
            )
        )
        .order_by("ten_cong_dong")[:4]
    )

    announcements = _readable_official_notices(user, profile, scope)

    from social.services import with_post_attachments

    new_posts = list(
        with_post_attachments(accessible_posts(user)).select_related("nguoi_dang", "cong_dong", "du_an")
        .exclude(loai_bai_viet="thong_bao")
        .order_by("-ngay_tao", "-ma_bai_viet")[:1]
    )
    author_ids = {post.nguoi_dang_id for post in new_posts}
    author_profiles = {
        employee_profile.nguoi_dung_id: employee_profile
        for employee_profile in HoSoNhanVien.objects.select_related("phong_ban").filter(
            nguoi_dung_id__in=author_ids
        )
    }
    for post in new_posts:
        author_profile = author_profiles.get(post.nguoi_dang_id)
        post.home_author_department = (
            author_profile.phong_ban.ten_phong_ban if author_profile else "Nhân viên OZZONE"
        )

    issue_posts = list(
        accessible_posts(user).select_related("du_an")
        .filter(
            du_an_id__in=scope["project_ids"],
            da_xoa_mem=False,
            trang_thai=VISIBLE_POST,
            che_do_xu_ly=True,
            trang_thai_xu_ly="chua_giai_quyet",
        )
        .order_by("-ngay_cap_nhat", "-ma_bai_viet")[:2]
    )

    from knowledge.views import _knowledge_sources_for

    knowledge = _knowledge_sources_for(user)
    lessons = (
        knowledge["lessons"]
        .select_related("phan_cong__du_an")
        .order_by("-ngay_luu_tri_thuc")[:3]
    )
    knowledge_articles = knowledge["articles"].order_by(
        "-phien_ban_dang_cong_bo__xuat_ban_luc"
    )[:3]

    tasks = _task_items(user, profile, scope)
    continue_items = _recent_work(project_memberships, issue_posts, lessons)
    display_name = ho_ten(user)

    return {
        "active_nav": "core",
        "profile": profile,
        "display_name": display_name,
        "first_name": user.first_name or display_name.split()[0],
        "project_memberships": project_memberships[:2],
        "projects": [membership.du_an for membership in project_memberships[:2]],
        "communities": community_rows,
        "announcements": announcements,
        "new_posts": new_posts,
        "issue_posts": issue_posts,
        "lessons": lessons,
        "knowledge_articles": knowledge_articles,
        "tasks": tasks,
        "continue_items": continue_items,
        "has_project_data": bool(project_memberships),
        "has_community_data": bool(community_memberships),
    }
