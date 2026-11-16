from accounts.views._chung import ho_ten
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone

from projectp.models import (
    BaiHocKinhNghiem,
    DinhKem,
    BaiViet,
    BaiVietDaLuu,
    BaiVietTriThuc,
    PhienBanTriThuc,
    ChuDeTriThuc,
    GanChuDePhienBan,
    KetLuanXuLy,
    MaThietBi,
    NguonThamKhao,
    HoSoNhanVien,
    KyNangNhanVien,
    ThanhVienDuAn,
)

PAGE_SIZE = 10
PERIOD_OPTIONS = (
    ("all", "Tất cả thời gian"),
    ("7", "7 ngày gần đây"),
    ("30", "30 ngày gần đây"),
    ("90", "90 ngày gần đây"),
    ("365", "1 năm gần đây"),
)
KIND_OPTIONS = (
    ("all", "Tất cả nội dung"),
    ("lesson", "Bài học kinh nghiệm"),
    ("article", "Bài viết tri thức"),
    ("conclusion", "Kết luận xử lý"),
)


def _knowledge_sources_for(user):
    """Build permission-filtered querysets before search, count or pagination."""
    from projects.permissions import readable_projects, active_memberships
    from communities.views._chung import active_community_memberships

    project_ids = list(readable_projects(user).values_list("pk", flat=True))
    community_ids = list(active_community_memberships(user).values_list("cong_dong_id", flat=True))

    # Lesson learned: company-wide lessons or lessons belonging to an active project.
    lessons = (
        BaiHocKinhNghiem.objects.filter(
            da_xoa_mem=False,
            trang_thai_quan_tri="hien_thi",
            bai_viet_nguon__da_xoa_mem=False,
            bai_viet_nguon__trang_thai="hien",
        )
        .filter(
            Q(pham_vi_chia_se="noi_bo") | Q(pham_vi_chia_se="du_an", bai_viet_nguon__du_an_id__in=project_ids)
        )
        .select_related(
            "bai_viet_nguon",
            "bai_viet_nguon__du_an",
            "bai_viet_nguon__ma_the_thiet_bi",
            "nguoi_kiem_tra_noi_dung",
        )
    )

    # Knowledge articles: only the current published version can enter search.
    articles = (
        BaiVietTriThuc.objects.filter(
            da_xoa_mem=False,
            trang_thai_quan_tri="hien_thi",
            an_khoi_tra_cuu=False,
            phien_ban_dang_cong_bo__isnull=False,
            phien_ban_dang_cong_bo__trang_thai="da_cong_bo",
            phien_ban_dang_cong_bo__bai_viet_tri_thuc_id=F("pk"),
        )
        .filter(
            Q(phien_ban_dang_cong_bo__pham_vi_chia_se="noi_bo")
            | Q(
                phien_ban_dang_cong_bo__pham_vi_chia_se="cong_dong",
                phien_ban_dang_cong_bo__cong_dong_id__in=community_ids,
            )
            | Q(
                phien_ban_dang_cong_bo__pham_vi_chia_se="du_an",
                phien_ban_dang_cong_bo__du_an_id__in=project_ids,
            )
        )
        .select_related(
            "phien_ban_dang_cong_bo",
            "phien_ban_dang_cong_bo__du_an",
            "phien_ban_dang_cong_bo__cong_dong",
        )
    )

    # Confirmed conclusions are searchable only inside projects the user belongs to.
    conclusions = KetLuanXuLy.objects.filter(
        trang_thai="da_xac_nhan",
        ket_qua__thanh_cong=True,
        bai_viet_nguon__da_xoa_mem=False,
        bai_viet_nguon__trang_thai="hien",
        bai_viet_nguon__che_do_xu_ly=True,
        bai_viet_nguon__trang_thai_xu_ly="da_giai_quyet",
        bai_viet_nguon__du_an_id__in=project_ids,
    ).select_related(
        "bai_viet_nguon",
        "bai_viet_nguon__du_an",
        "bai_viet_nguon__ma_the_thiet_bi",
        "ket_qua",
    )

    projects = (
        ThanhVienDuAn.objects.filter(
            du_an_id__in=project_ids,
            nguoi_dung=user,
            trang_thai="hoat_dong",
            ket_thuc_luc__isnull=True,
        )
        .select_related("du_an")
        .order_by("du_an__ten_du_an")
    )

    devices = (
        MaThietBi.objects.filter(
            du_an_id__in=project_ids,
            dang_su_dung=True,
        )
        .select_related("du_an")
        .order_by("du_an__ten_du_an", "ten_thiet_bi")
    )

    visible_article_version_ids = articles.values_list("phien_ban_dang_cong_bo_id", flat=True)
    visible_topic_ids = GanChuDePhienBan.objects.filter(
        phien_ban_id__in=visible_article_version_ids
    ).values_list("chu_de_id", flat=True)
    topics = ChuDeTriThuc.objects.filter(ma_chu_de__in=visible_topic_ids).order_by("ten_chu_de")

    return {
        "lessons": lessons,
        "articles": articles,
        "conclusions": conclusions,
        "project_ids": project_ids,
        "community_ids": community_ids,
        "projects": projects,
        "devices": devices,
        "topics": topics,
    }


def _as_item(obj, kind):
    if kind == "lesson":
        source = obj.bai_viet_nguon
        # Với bài học chia sẻ nội bộ, không để lộ tên dự án/thiết bị của nguồn riêng.
        if obj.pham_vi_chia_se == "du_an" and source.du_an_id:
            context = source.du_an.ten_du_an
            if source.ma_the_thiet_bi_id:
                context = f"{context} · {source.ma_the_thiet_bi.ten_thiet_bi}"
        else:
            context = "OZZONE"
        return {
            "kind": "lesson",
            "kind_label": "Bài học kinh nghiệm",
            "badge": "Tri thức",
            "object_id": obj.pk,
            "title": obj.tieu_de,
            "summary": obj.van_de,
            "context": context,
            "date": obj.ngay_luu_tri_thuc,
        }

    if kind == "article":
        version = obj.phien_ban_dang_cong_bo
        if version.du_an_id:
            context = version.du_an.ten_du_an
        elif version.cong_dong_id:
            context = version.cong_dong.ten_cong_dong
        else:
            context = "OZZONE"
        return {
            "kind": "article",
            "kind_label": "Bài viết tri thức",
            "badge": "Tri thức",
            "object_id": obj.pk,
            "title": version.tieu_de,
            "summary": version.tom_tat or version.noi_dung,
            "context": context,
            "date": version.xuat_ban_luc,
        }

    source = obj.bai_viet_nguon
    project = source.du_an if source.du_an_id else None
    context = project.ten_du_an if project else "Dự án"
    if source.ma_the_thiet_bi_id:
        context = f"{context} · {source.ma_the_thiet_bi.ten_thiet_bi}"
    return {
        "kind": "conclusion",
        "kind_label": "Kết luận xử lý",
        "badge": "Kết luận xử lý",
        "object_id": obj.pk,
        "title": source.tieu_de or obj.noi_dung_ket_luan,
        "open_url": reverse("projects:issue", kwargs={"pk": source.du_an_id, "post_id": source.pk}),
        "summary": obj.noi_dung_ket_luan,
        "context": context,
        "date": obj.ngay_xac_nhan,
    }


def _ordered_items(sources, limit):
    """Fetch a bounded top-N from each permission-filtered source, then merge."""
    rows = []
    for obj in sources["lessons"].order_by("-ngay_luu_tri_thuc", "-ma_bai_hoc")[:limit]:
        rows.append(_as_item(obj, "lesson"))
    for obj in sources["articles"].order_by("-phien_ban_dang_cong_bo__xuat_ban_luc", "-pk")[:limit]:
        rows.append(_as_item(obj, "article"))
    for obj in sources["conclusions"].order_by("-ngay_xac_nhan", "-ma_ket_luan")[:limit]:
        rows.append(_as_item(obj, "conclusion"))

    rows.sort(
        key=lambda item: item["date"].timestamp() if item["date"] else 0,
        reverse=True,
    )
    return rows


def _topic_choices(sources):
    return list(sources["topics"].values("ma_chu_de", "ten_chu_de"))


def _apply_search_filters(request, sources):
    params = request.GET
    query = params.get("q", "").strip()
    kind = params.get("kind", "all")
    project_value = params.get("project", "").strip()
    device_value = params.get("device", "").strip()
    topic_value = params.get("topic", "").strip()
    period = params.get("period", "all")
    invalid_project = False
    invalid_topic = False

    if kind not in {value for value, _ in KIND_OPTIONS}:
        kind = "all"
    if period not in {value for value, _ in PERIOD_OPTIONS}:
        period = "all"

    lessons = sources["lessons"]
    articles = sources["articles"]
    conclusions = sources["conclusions"]

    if query:
        lessons = lessons.filter(
            Q(tieu_de__icontains=query)
            | Q(van_de__icontains=query)
            | Q(nguyen_nhan__icontains=query)
            | Q(giai_phap__icontains=query)
            | Q(ket_qua__icontains=query)
        )
        articles = articles.filter(
            Q(phien_ban_dang_cong_bo__tieu_de__icontains=query)
            | Q(phien_ban_dang_cong_bo__tom_tat__icontains=query)
            | Q(phien_ban_dang_cong_bo__noi_dung__icontains=query)
            | Q(phien_ban_dang_cong_bo__pham_vi_ap_dung__icontains=query)
            | Q(phien_ban_dang_cong_bo__du_an__ten_du_an__icontains=query)
            | Q(phien_ban_dang_cong_bo__cong_dong__ten_cong_dong__icontains=query)
            | Q(phien_ban_dang_cong_bo__gan_chu_de__chu_de__ten_chu_de__icontains=query)
        ).distinct()
        conclusions = conclusions.filter(
            Q(noi_dung_ket_luan__icontains=query)
            | Q(bai_viet_nguon__tieu_de__icontains=query)
            | Q(bai_viet_nguon__noi_dung__icontains=query)
        )

    if project_value:
        try:
            project_id = int(project_value)
        except ValueError:
            project_id = None
        if project_id is None or project_id not in sources["project_ids"]:
            invalid_project = True
            lessons, articles, conclusions = lessons.none(), articles.none(), conclusions.none()
        else:
            lessons = lessons.filter(
                pham_vi_chia_se="du_an",
                bai_viet_nguon__du_an_id=project_id,
            )
            articles = articles.filter(
                Q(phien_ban_dang_cong_bo__du_an_id=project_id)
                | Q(phien_ban_dang_cong_bo__cong_dong__du_an_lien_ket__ma_du_an=project_id)
            )
            conclusions = conclusions.filter(bai_viet_nguon__du_an_id=project_id)

    if device_value:
        lessons = lessons.filter(
            pham_vi_chia_se="du_an",
        ).filter(
            Q(bai_viet_nguon__ma_the_thiet_bi__ma_thiet_bi__icontains=device_value)
            | Q(bai_viet_nguon__ma_the_thiet_bi__ten_thiet_bi__icontains=device_value)
        )
        conclusions = conclusions.filter(
            Q(bai_viet_nguon__ma_the_thiet_bi__ma_thiet_bi__icontains=device_value)
            | Q(bai_viet_nguon__ma_the_thiet_bi__ten_thiet_bi__icontains=device_value)
        )
        # Article versions do not carry a device FK in the current data model.
        articles = articles.none()

    if topic_value:
        try:
            topic_id = int(topic_value)
        except ValueError:
            topic_id = None
        allowed_topic_ids = set(sources["topics"].values_list("ma_chu_de", flat=True))
        if topic_id is None or topic_id not in allowed_topic_ids:
            invalid_topic = True
            articles = articles.none()
        else:
            articles = articles.filter(phien_ban_dang_cong_bo__gan_chu_de__chu_de_id=topic_id).distinct()
        lessons, conclusions = lessons.none(), conclusions.none()

    if period != "all":
        cutoff = timezone.now() - timedelta(days=int(period))
        lessons = lessons.filter(ngay_luu_tri_thuc__gte=cutoff)
        articles = articles.filter(phien_ban_dang_cong_bo__xuat_ban_luc__gte=cutoff)
        conclusions = conclusions.filter(ngay_xac_nhan__gte=cutoff)

    if kind == "lesson":
        articles, conclusions = articles.none(), conclusions.none()
    elif kind == "article":
        lessons, conclusions = lessons.none(), conclusions.none()
    elif kind == "conclusion":
        lessons, articles = lessons.none(), articles.none()

    filtered = {
        **sources,
        "lessons": lessons,
        "articles": articles,
        "conclusions": conclusions,
    }
    return filtered, {
        "q": query,
        "kind": kind,
        "project": project_value,
        "device": device_value,
        "topic": topic_value,
        "period": period,
        "invalid_project": invalid_project,
        "invalid_topic": invalid_topic,
    }


def _render_search_results(request, sources):
    filtered, filters = _apply_search_filters(request, sources)
    total_count = filtered["lessons"].count() + filtered["articles"].count() + filtered["conclusions"].count()

    try:
        page_number = max(1, int(request.GET.get("page", "1")))
    except (TypeError, ValueError):
        page_number = 1
    page_number = min(page_number, max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE))

    start = (page_number - 1) * PAGE_SIZE
    fetch_limit = page_number * PAGE_SIZE
    merged = _ordered_items(filtered, fetch_limit)
    page_items = merged[start : start + PAGE_SIZE]
    has_previous = page_number > 1
    has_next = total_count > page_number * PAGE_SIZE

    return render(
        request,
        "knowledge/search_results.html",
        {
            "query": filters["q"],
            "filters": filters,
            "search_results": page_items,
            "result_count": total_count,
            "page_number": page_number,
            "has_previous": has_previous,
            "has_next": has_next,
            "topics": _topic_choices(sources),
            "projects": sources["projects"],
            "devices": sources["devices"],
            "kind_options": KIND_OPTIONS,
            "period_options": PERIOD_OPTIONS,
        },
    )


def knowledge_list(request):
    """GD-080: Kho tri thức OZZONE."""
    if not request.user.is_authenticated:
        return render(
            request,
            "knowledge/list.html",
            {"requires_login": True, "featured_items": [], "topics": []},
        )

    sources = _knowledge_sources_for(request.user)
    featured_items = _ordered_items(sources, 3)[:3]
    from .services import can_edit

    drafts = PhienBanTriThuc.objects.none()
    if can_edit(request.user) or request.user.has_perm("projectp.change_baiviettrithuc"):
        drafts = (
            PhienBanTriThuc.objects.filter(
                trang_thai="ban_nhap", bai_viet_tri_thuc__da_xoa_mem=False, nguoi_bien_tap=request.user
            )
            .select_related("bai_viet_tri_thuc")
            .order_by("-ngay_cap_nhat")
        )
    return render(
        request,
        "knowledge/list.html",
        {
            "requires_login": False,
            "featured_items": featured_items,
            "drafts": drafts,
            "topics": _topic_choices(sources),
        },
    )


def knowledge_search(request):
    """GD-081: Kết quả tra cứu; permission filters run before count and paging."""
    if not request.user.is_authenticated:
        return render(
            request,
            "knowledge/search_results.html",
            {"requires_login": True, "search_results": [], "result_count": 0},
        )
    sources = _knowledge_sources_for(request.user)
    return _render_search_results(request, sources)


def knowledge_filter(request):
    """GD-082: Bộ lọc tra cứu theo các nguồn người dùng hiện được phép biết."""
    if not request.user.is_authenticated:
        return render(
            request,
            "knowledge/filter.html",
            {"requires_login": True},
        )

    sources = _knowledge_sources_for(request.user)
    current = {
        "q": request.GET.get("q", "").strip(),
        "kind": request.GET.get("kind", "all"),
        "project": request.GET.get("project", ""),
        "device": request.GET.get("device", ""),
        "topic": request.GET.get("topic", ""),
        "period": request.GET.get("period", "all"),
    }
    return render(
        request,
        "knowledge/filter.html",
        {
            "requires_login": False,
            "current": current,
            "projects": sources["projects"],
            "devices": sources["devices"],
            "topics": _topic_choices(sources),
            "kind_options": KIND_OPTIONS,
            "period_options": PERIOD_OPTIONS,
        },
    )


# ---------------------------------------------------------------------------
# UC-KNW-03 — Xem nội dung tri thức (GD-083, GD-084, GD-017, GD-016)
# ---------------------------------------------------------------------------


def _login_redirect(request):
    return redirect_to_login(request.get_full_path(), login_url=reverse("accounts:login"))


def _unavailable_response(request):
    """Do not disclose whether a hidden, deleted or unauthorized object exists."""
    return render(request, "knowledge/unavailable.html", status=404)


def _can_read_source_post(user, post, sources):
    """Source access is evaluated separately from access to the knowledge item."""
    if not post or post.da_xoa_mem or post.trang_thai != "hien":
        return False

    from social.permissions import accessible_posts

    if post.loai_bai_viet == BaiViet.Kind.ANNOUNCEMENT:
        from notifications.permissions import can_read_notice

        notice = getattr(post, "thong_bao_chinh_thuc", None)
        return bool(notice and can_read_notice(user, notice))
    return accessible_posts(user).filter(pk=post.pk).exists()


def _user_display(user_id_obj):
    if not user_id_obj:
        return {"name": "Chưa có thông tin", "department": ""}
    name = ho_ten(user_id_obj)
    profile = (
        HoSoNhanVien.objects.filter(nguoi_dung=user_id_obj).select_related("phong_ban", "vi_tri").first()
    )
    department = profile.phong_ban.ten_phong_ban if profile else ""
    position = profile.vi_tri.ten_vi_tri if profile else ""
    detail = " · ".join(value for value in (position, department) if value)
    return {"name": name, "department": detail}


def lesson_detail(request, pk):
    """GD-083: Read a visible lesson learned without changing its business data."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    sources = _knowledge_sources_for(request.user)
    lesson = (
        sources["lessons"]
        .filter(pk=pk)
        .select_related(
            "bai_viet_nguon",
            "bai_viet_nguon__du_an",
            "bai_viet_nguon__ma_the_thiet_bi",
            "ket_luan__ket_qua__lan_thu__phuong_an",
            "ket_luan__ket_qua",
            "phan_cong__nguoi_phu_trach",
            "nguoi_kiem_tra_noi_dung",
        )
        .first()
    )
    if lesson is None:
        return _unavailable_response(request)

    source_post = lesson.bai_viet_nguon
    source_can_open = _can_read_source_post(request.user, source_post, sources)
    source_project = source_post.du_an if source_can_open and source_post.du_an_id else None
    source_device = (
        source_post.ma_the_thiet_bi if source_can_open and source_post.ma_the_thiet_bi_id else None
    )

    conclusion = lesson.ket_luan
    result = conclusion.ket_qua if conclusion and conclusion.ket_qua_id else None
    trial = result.lan_thu if result else None
    plan = trial.phuong_an if trial else None
    normalizer = _user_display(lesson.nguoi_kiem_tra_noi_dung)

    is_saved = BaiVietDaLuu.objects.filter(
        nguoi_dung=request.user,
        bai_hoc=lesson,
    ).exists()

    context = {
        "lesson": lesson,
        "source_can_open": source_can_open,
        "source_project": source_project,
        "source_device": source_device,
        "conclusion": conclusion,
        "result": result,
        "trial": trial,
        "plan": plan if source_can_open else None,
        "source_url": (
            reverse("projects:issue", kwargs={"pk": source_post.du_an_id, "post_id": source_post.pk})
            if source_can_open and source_post.du_an_id
            else ""
        ),
        "normalizer": normalizer,
        "is_saved": is_saved,
    }
    return render(request, "knowledge/lesson_detail.html", context)


def _article_reference_rows(user, sources, version):
    rows = []
    for reference in (
        NguonThamKhao.objects.filter(phien_ban=version)
        .select_related(
            "bai_viet_nguon",
            "tep_nguon",
        )
        .order_by("thu_tu", "ma_nguon_tham_khao")
    ):
        row = {
            "title": reference.tieu_de_nguon or "Nguồn tham khảo",
            "author": reference.tac_gia,
            "citation": reference.trich_dan,
            "note": reference.ghi_chu,
            "url": None,
            "status": "available",
            "status_label": "Thông tin tham khảo",
        }

        if reference.loai_tham_chieu == "url" and reference.url:
            row["url"] = reference.url
            row["status_label"] = "Nguồn bên ngoài"
            row["external"] = True
            row["open_label"] = "Mở nguồn bên ngoài"
        elif reference.loai_tham_chieu == "bai_viet":
            if _can_read_source_post(user, reference.bai_viet_nguon, sources):
                row["status_label"] = "Nguồn nội bộ · có quyền đọc"
                row["target_available"] = True
                row["url"] = reverse("social:post_detail", args=[reference.bai_viet_nguon_id])
                row["open_label"] = "Mở bài nguồn"
            else:
                # Do not leak the title, author, citation or URL of a restricted source.
                row.update(
                    {
                        "title": "Nguồn nội bộ bị giới hạn quyền",
                        "author": "",
                        "citation": "",
                        "note": "",
                        "status": "restricted",
                        "status_label": "Nguồn đích không khả dụng",
                        "target_available": False,
                    }
                )
        elif reference.loai_tham_chieu == "tep":
            file_obj = reference.tep_nguon
            from .files import can_read_reference_file
            if file_obj and can_read_reference_file(user, reference):
                row["title"] = file_obj.ten_tep
                row["status_label"] = "Tệp tham khảo"
                row["url"] = reverse("knowledge:reference_download", args=[reference.pk])
                row["open_label"] = "Tải tệp nguồn"
            else:
                row.update(
                    {
                        "title": "Tệp tham khảo bị giới hạn quyền",
                        "author": "",
                        "citation": "",
                        "note": "",
                        "status": "restricted",
                        "status_label": "Không thể mở tệp tham khảo",
                    }
                )
        rows.append(row)
    return rows


def article_detail(request, pk):
    """GD-084: Read only the current published version visible to this user."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    sources = _knowledge_sources_for(request.user)
    article = (
        sources["articles"]
        .filter(pk=pk)
        .select_related(
            "phien_ban_dang_cong_bo",
            "phien_ban_dang_cong_bo__du_an",
            "phien_ban_dang_cong_bo__cong_dong",
            "phien_ban_dang_cong_bo__nguoi_bien_tap",
            "phien_ban_dang_cong_bo__nguoi_xuat_ban",
        )
        .prefetch_related("phien_ban_dang_cong_bo__gan_chu_de__chu_de")
        .first()
    )
    if article is None:
        return _unavailable_response(request)

    version = article.phien_ban_dang_cong_bo
    topics = [link.chu_de.ten_chu_de for link in version.gan_chu_de.all()]
    editor = _user_display(version.nguoi_bien_tap)
    publisher = _user_display(version.nguoi_xuat_ban)
    references = _article_reference_rows(request.user, sources, version)
    is_saved = BaiVietDaLuu.objects.filter(
        nguoi_dung=request.user,
        bai_viet_tri_thuc=article,
    ).exists()

    if version.du_an_id:
        sharing_context = version.du_an.ten_du_an
    elif version.cong_dong_id:
        sharing_context = version.cong_dong.ten_cong_dong
    else:
        sharing_context = "Toàn OZZONE"

    from .services import can_edit, editor_token, revision

    context = {
        "can_edit": can_edit(request.user, article),
        "clone_token": editor_token(request.user, article.pk, None),
        "revision_token": revision(article, version),
        "attachments": DinhKem.objects.filter(
            phien_ban_tri_thuc=version, tep_tin__trang_thai="san_sang", tep_tin__da_xoa_mem=False
        ).select_related("tep_tin"),
        "article": article,
        "version": version,
        "topics": topics,
        "editor": editor,
        "publisher": publisher,
        "references": references,
        "is_saved": is_saved,
        "sharing_context": sharing_context,
    }
    return render(request, "knowledge/article_detail.html", context)


@require_POST
def toggle_lesson_saved(request, pk):
    if not request.user.is_authenticated:
        return _login_redirect(request)
    sources = _knowledge_sources_for(request.user)
    lesson = sources["lessons"].filter(pk=pk).first()
    if lesson is None:
        return _unavailable_response(request)

    from django.db import transaction
    from django.contrib.auth import get_user_model

    with transaction.atomic():
        get_user_model().objects.filter(pk=request.user.pk).update(is_active=F("is_active"))
        lesson = _knowledge_sources_for(request.user)["lessons"].filter(pk=pk).first()
        if lesson is None:
            return _unavailable_response(request)
        saved = BaiVietDaLuu.objects.filter(nguoi_dung=request.user, bai_hoc=lesson)
        desired = request.POST.get("state", "off" if saved.exists() else "on")
        if desired == "off":
            saved.delete()
            messages.success(request, "Đã bỏ lưu bài học kinh nghiệm.")
        elif desired == "on":
            BaiVietDaLuu.objects.get_or_create(nguoi_dung=request.user, bai_hoc=lesson)
            messages.success(request, "Đã lưu bài học kinh nghiệm.")
    return redirect("knowledge:lesson_detail", pk=pk)


@require_POST
def toggle_article_saved(request, pk):
    if not request.user.is_authenticated:
        return _login_redirect(request)
    sources = _knowledge_sources_for(request.user)
    article = sources["articles"].filter(pk=pk).first()
    if article is None:
        return _unavailable_response(request)

    from django.db import transaction
    from django.contrib.auth import get_user_model

    with transaction.atomic():
        get_user_model().objects.filter(pk=request.user.pk).update(is_active=F("is_active"))
        article = _knowledge_sources_for(request.user)["articles"].filter(pk=pk).first()
        if article is None:
            return _unavailable_response(request)
        saved = BaiVietDaLuu.objects.filter(nguoi_dung=request.user, bai_viet_tri_thuc=article)
        desired = request.POST.get("state", "off" if saved.exists() else "on")
        if desired == "off":
            saved.delete()
            messages.success(request, "Đã bỏ lưu bài viết tri thức.")
        elif desired == "on":
            BaiVietDaLuu.objects.get_or_create(nguoi_dung=request.user, bai_viet_tri_thuc=article)
            messages.success(request, "Đã lưu bài viết tri thức.")
    return redirect("knowledge:article_detail", pk=pk)


@require_POST
def remove_saved_item(request, saved_id):
    if not request.user.is_authenticated:
        return _login_redirect(request)
    saved = get_object_or_404(
        BaiVietDaLuu.objects.filter(nguoi_dung=request.user).filter(
            Q(bai_viet__isnull=False) | Q(bai_hoc__isnull=False) | Q(bai_viet_tri_thuc__isnull=False)
        ),
        pk=saved_id,
    )
    saved.delete()
    messages.success(request, "Đã bỏ nội dung khỏi danh sách đã lưu.")
    return redirect("knowledge:saved")


def saved_content(request):
    """GD-016: list saved posts, notices and knowledge items in current scopes."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    sources = _knowledge_sources_for(request.user)
    selected_kind = request.GET.get("kind", "all")
    if selected_kind not in {"all", "post", "notice", "knowledge"}:
        selected_kind = "all"

    entries = (
        BaiVietDaLuu.objects.filter(nguoi_dung=request.user)
        .filter(Q(bai_viet__isnull=False) | Q(bai_hoc__isnull=False) | Q(bai_viet_tri_thuc__isnull=False))
        .select_related(
            "bai_viet__du_an",
            "bai_viet__cong_dong",
            "bai_hoc__bai_viet_nguon__du_an",
            "bai_viet_tri_thuc__phien_ban_dang_cong_bo",
        )
        .order_by("-ngay_luu", "-ma_bai_viet_da_luu")
    )

    items = []
    for entry in entries:
        if entry.bai_viet_id:
            post = BaiViet.objects.filter(pk=entry.bai_viet_id).first()
            if post and _can_read_source_post(request.user, post, sources):
                kind = "notice" if post.loai_bai_viet == BaiViet.Kind.ANNOUNCEMENT else "post"
                if selected_kind in {"all", kind}:
                    if post.du_an_id:
                        context_name = post.du_an.ten_du_an
                    elif post.cong_dong_id:
                        context_name = post.cong_dong.ten_cong_dong
                    else:
                        context_name = "OZZONE"
                    items.append(
                        {
                            "saved_id": entry.pk,
                            "kind": kind,
                            "kind_label": "Thông báo chính thức" if kind == "notice" else "Bài đăng",
                            "title": post.tieu_de or (post.noi_dung or "")[:100],
                            "context": context_name,
                            "saved_at": entry.ngay_luu,
                            "available": True,
                            "open_url": (
                                reverse("notifications:detail", args=[post.thong_bao_chinh_thuc.pk])
                                if kind == "notice"
                                else reverse("social:post_detail", args=[post.pk])
                            ),
                        }
                    )
                continue
            if selected_kind == "all":
                items.append(
                    {
                        "saved_id": entry.pk,
                        "kind": "unavailable",
                        "kind_label": "Nội dung đã lưu",
                        "title": "Nội dung không khả dụng",
                        "context": "Nội dung đã thay đổi trạng thái hoặc quyền truy cập",
                        "saved_at": entry.ngay_luu,
                        "available": False,
                    }
                )
            continue

        if entry.bai_hoc_id and selected_kind in {"all", "knowledge"}:
            lesson = sources["lessons"].filter(pk=entry.bai_hoc_id).first()
            if lesson:
                item = _as_item(lesson, "lesson")
                items.append({**item, "saved_id": entry.pk, "saved_at": entry.ngay_luu, "available": True})
            else:
                items.append(
                    {
                        "saved_id": entry.pk,
                        "kind": "unavailable",
                        "kind_label": "Nội dung đã lưu",
                        "title": "Nội dung không khả dụng",
                        "context": "Nội dung đã thay đổi trạng thái hoặc quyền truy cập",
                        "saved_at": entry.ngay_luu,
                        "available": False,
                    }
                )
        elif entry.bai_viet_tri_thuc_id and selected_kind in {"all", "knowledge"}:
            article = sources["articles"].filter(pk=entry.bai_viet_tri_thuc_id).first()
            if article:
                item = _as_item(article, "article")
                items.append({**item, "saved_id": entry.pk, "saved_at": entry.ngay_luu, "available": True})
            else:
                items.append(
                    {
                        "saved_id": entry.pk,
                        "kind": "unavailable",
                        "kind_label": "Nội dung đã lưu",
                        "title": "Nội dung không khả dụng",
                        "context": "Nội dung đã thay đổi trạng thái hoặc quyền truy cập",
                        "saved_at": entry.ngay_luu,
                        "available": False,
                    }
                )

    return render(
        request,
        "knowledge/saved.html",
        {
            "saved_items": items,
            "selected_kind": selected_kind,
            "saved_count": len(items),
        },
    )


# ---------------------------------------------------------------------------
# UC-KNW-02 — Tìm người hỗ trợ (GD-085, GD-086)
# ---------------------------------------------------------------------------


def _support_workspace(user, params=None):
    """Return only employee profiles sharing an active project membership with the current user.

    No relevance score is calculated because the specification has not defined
    a ranking formula or weights. Candidate ordering is stable by employee name.
    """
    params = params or {}
    from projects.permissions import readable_projects

    own_memberships = (
        ThanhVienDuAn.objects.filter(
            du_an__in=readable_projects(user),
            nguoi_dung=user,
            trang_thai="hoat_dong",
            ket_thuc_luc__isnull=True,
        )
        .select_related("du_an")
        .order_by("du_an__ten_du_an")
    )
    own_project_ids = list(own_memberships.values_list("du_an_id", flat=True))

    # A colleague is eligible only through a current, shared project membership.
    shared_memberships = (
        ThanhVienDuAn.objects.filter(
            du_an_id__in=own_project_ids,
            trang_thai="hoat_dong",
            ket_thuc_luc__isnull=True,
            nguoi_dung__is_active=True,
        )
        .exclude(nguoi_dung=user)
        .select_related("du_an", "nguoi_dung")
    )
    eligible_user_ids = list(
        HoSoNhanVien.objects.filter(nguoi_dung__is_active=True)
        .exclude(nguoi_dung=user)
        .values_list("nguoi_dung_id", flat=True)
    )

    base_profiles = (
        HoSoNhanVien.objects.filter(
            nguoi_dung_id__in=eligible_user_ids,
            nguoi_dung__is_active=True,
        )
        .select_related("nguoi_dung", "phong_ban", "vi_tri")
        .prefetch_related("kynangnhanvien_set__ky_nang")
    )

    # Filter choices are derived only from candidates already within the user's scope.
    skill_options = list(
        KyNangNhanVien.objects.filter(ho_so__nguoi_dung_id__in=eligible_user_ids)
        .values("ky_nang_id", "ky_nang__ten_ky_nang")
        .distinct()
        .order_by("ky_nang__ten_ky_nang")
    )
    department_options = list(
        base_profiles.values("phong_ban_id", "phong_ban__ten_phong_ban")
        .distinct()
        .order_by("phong_ban__ten_phong_ban")
    )
    project_options = list(own_memberships.values("du_an_id", "du_an__ten_du_an").distinct())

    selected_skill = str(params.get("skill", "")).strip()
    selected_department = str(params.get("department", "")).strip()
    selected_project = str(params.get("project", "")).strip()
    invalid_filter = False

    # Project values must be in the user's current project scope.
    if selected_project:
        if not selected_project.isdigit() or int(selected_project) not in own_project_ids:
            invalid_filter = True
            eligible_user_ids = []
        else:
            eligible_user_ids = list(
                shared_memberships.filter(du_an_id=int(selected_project))
                .values_list("nguoi_dung_id", flat=True)
                .distinct()
            )

    filtered_profiles = base_profiles.filter(nguoi_dung_id__in=eligible_user_ids)
    for word in params.get("context", "").strip().split():
        filtered_profiles = filtered_profiles.filter(
            Q(nguoi_dung__first_name__icontains=word)
            | Q(nguoi_dung__last_name__icontains=word)
            | Q(kynangnhanvien__ky_nang__ten_ky_nang__icontains=word)
            | Q(vi_tri__ten_vi_tri__icontains=word)
            | Q(gioi_thieu__icontains=word)
        ).distinct()

    visible_skill_ids = {str(row["ky_nang_id"]) for row in skill_options}
    visible_department_ids = {str(row["phong_ban_id"]) for row in department_options}

    if selected_skill:
        if selected_skill not in visible_skill_ids:
            invalid_filter = True
            filtered_profiles = filtered_profiles.none()
        else:
            filtered_profiles = filtered_profiles.filter(
                kynangnhanvien__ky_nang_id=int(selected_skill)
            ).distinct()

    if selected_department:
        if selected_department not in visible_department_ids:
            invalid_filter = True
            filtered_profiles = filtered_profiles.none()
        else:
            filtered_profiles = filtered_profiles.filter(phong_ban_id=int(selected_department))

    filtered_profiles = filtered_profiles.order_by(
        "nguoi_dung__last_name", "nguoi_dung__first_name", "nguoi_dung__username"
    )

    # Candidate project context is limited to projects shared with the current user.
    all_shared_rows = list(
        shared_memberships.values("nguoi_dung_id", "du_an_id", "du_an__ten_du_an").order_by(
            "du_an__ten_du_an"
        )
    )
    project_names_by_user = {}
    project_ids_by_user = {}
    for row in all_shared_rows:
        project_names_by_user.setdefault(row["nguoi_dung_id"], []).append(row["du_an__ten_du_an"])
        project_ids_by_user.setdefault(row["nguoi_dung_id"], []).append(row["du_an_id"])

    # Count only visible posts inside a shared project; no private content is exposed.

    contribution_rows = (
        BaiViet.objects.filter(
            nguoi_dang_id__in=eligible_user_ids,
            du_an_id__in=own_project_ids,
            da_xoa_mem=False,
            trang_thai="hien",
        )
        .values("nguoi_dang_id")
        .annotate(total=Count("ma_bai_viet"))
    )

    contribution_counts = {row["nguoi_dang_id"]: row["total"] for row in contribution_rows}

    candidate_items = []
    for profile in filtered_profiles:
        employee = profile.nguoi_dung
        skill_rows = [
            {
                "id": link.ky_nang_id,
                "name": link.ky_nang.ten_ky_nang,
                "experience": link.mo_ta_kinh_nghiem,
            }
            for link in profile.kynangnhanvien_set.all()
        ]
        projects = project_names_by_user.get(employee.pk, [])
        project_ids = project_ids_by_user.get(employee.pk, [])
        full_name = (
            " ".join(part for part in (employee.last_name.strip(), employee.first_name.strip()) if part)
            or employee.username
        )
        initials = "".join(part[0] for part in full_name.split()[:2]).upper()
        candidate_items.append(
            {
                "user_id": employee.pk,
                "name": full_name,
                "initials": initials or "NV",
                "department": profile.phong_ban.ten_phong_ban,
                "position": profile.vi_tri.ten_vi_tri,
                "skills": skill_rows,
                "projects": projects,
                "project_ids": project_ids,
                "contribution_count": contribution_counts.get(employee.pk, 0),
            }
        )

    context = {
        "context_query": params.get("context", "").strip(),
        "candidate_items": candidate_items,
        "skill_options": skill_options,
        "department_options": department_options,
        "project_options": project_options,
        "selected_skill": selected_skill,
        "selected_department": selected_department,
        "selected_project": selected_project,
        "invalid_filter": invalid_filter,
        "limited_access": False,
        "create_project_options": list(own_memberships.exclude(du_an__trang_thai="luu_tru")),
        "result_count": len(candidate_items),
        "reason_candidate": None,
    }

    reason_user_id = params.get("reason")
    if reason_user_id and str(reason_user_id).isdigit():
        reason_user_id = int(reason_user_id)
        # Re-check against the complete eligible colleague set, not a client-supplied ID alone.
        reason_profile = base_profiles.filter(nguoi_dung_id=reason_user_id).first()
        if reason_profile:
            reason_skills = [
                {
                    "name": link.ky_nang.ten_ky_nang,
                    "experience": link.mo_ta_kinh_nghiem,
                }
                for link in reason_profile.kynangnhanvien_set.all()
            ]
            reason_projects = project_names_by_user.get(reason_user_id, [])
            reason_user = reason_profile.nguoi_dung
            reason_name = (
                " ".join(
                    part for part in (reason_user.last_name.strip(), reason_user.first_name.strip()) if part
                )
                or reason_user.username
            )
            context["reason_candidate"] = {
                "user_id": reason_user_id,
                "name": reason_name,
                "department": reason_profile.phong_ban.ten_phong_ban,
                "position": reason_profile.vi_tri.ten_vi_tri,
                "skills": reason_skills,
                "projects": reason_projects,
                "contribution_count": contribution_counts.get(reason_user_id, 0),
            }

    return context


def support_finder(request):
    """GD-085: Find colleagues using only permitted shared-project profile data."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    context = _support_workspace(request.user, request.GET)
    return render(request, "knowledge/support.html", context)


def support_profile(request, user_id):
    """Mở hồ sơ nhân viên dùng chung GD-009, kiểm tra lại tài khoản hiện hành."""
    if not request.user.is_authenticated:
        return _login_redirect(request)

    from django.contrib.auth import get_user_model

    employee = get_object_or_404(get_user_model(), pk=user_id, is_active=True, ho_so_nhan_vien__isnull=False)
    return redirect("accounts:employee", username=employee.username)


from .editor import article_editor
