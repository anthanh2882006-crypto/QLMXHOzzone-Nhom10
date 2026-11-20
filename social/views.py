from accounts.views._chung import ho_ten
import uuid
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import BooleanField, Case, Count, Exists, F, OuterRef, Q, When
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from projectp.models import (
    BaiViet,
    BaiVietDaLuu,
    CongDong,
    BinhLuan,
    CamXuc,
    DinhKem,
    DuAn,
    HoSoNhanVien,
    MemberStatus,
    NguoiNhanThongBao,
    ThongBaoChinhThuc,
    ThanhVienCongDong,
)

from .forms import CommentForm, PostForm
from .navigation import interaction_redirect as _interaction_redirect, listing_origin, post_return_url, with_listing_origin
from notifications.permissions import can_read_notice
from projects.permissions import active_memberships, readable_projects
from .permissions import (
    accessible_posts,
    can_create_company_post,
    can_manage_own_post,
)
from .services import create_company_post, soft_delete_post, update_company_post, with_post_attachments
from .tokens import consume_post_token, has_post_token, issue_post_token

REACTION_CHOICES = {value for value, _label in CamXuc._meta.get_field("loai_cam_xuc").choices}


def _post_cards(queryset, user):
    liked = CamXuc.objects.filter(bai_viet_id=OuterRef("pk"), nguoi_dung=user)
    saved = BaiVietDaLuu.objects.filter(bai_viet_id=OuterRef("pk"), nguoi_dung=user)
    from communities.views._chung import active_community_memberships

    member = active_community_memberships(user).filter(cong_dong_id=OuterRef("cong_dong_id"))
    current_scope = (
        Q(du_an__isnull=False) | Q(cong_dong__isnull=True) | Q(Exists(member))
    ) & ~Q(du_an__trang_thai=DuAn.Status.ARCHIVED) & ~Q(
        du_an__isnull=True, cong_dong__du_an_lien_ket__trang_thai=DuAn.Status.ARCHIVED,
    )
    return with_post_attachments(queryset.annotate(
        interaction_permitted=Case(
            When(Q(trang_thai="hien", da_xoa_mem=False) & current_scope, then=True),
            default=False, output_field=BooleanField(),
        ),
        comment_count=Count("binhluan", filter=Q(binhluan__da_xoa_mem=False), distinct=True),
        reaction_count=Count("camxuc", distinct=True),
        liked_by_me=Exists(liked),
        saved_by_me=Exists(saved),
    ).order_by("-ngay_tao", "-ma_bai_viet"))


def _interaction_post(request, pk, *, community_id=None, project_id=None):
    if community_id is not None:
        from communities.views._chung import community_posts, duoc_doc, lay_cong_dong, tu_cach

        community = lay_cong_dong(request.user, community_id)
        if not duoc_doc(community, tu_cach(request.user, community)):
            raise PermissionDenied("Bạn không còn quyền đọc cộng đồng này.")
        post = get_object_or_404(
            community_posts(community).exclude(loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT),
            pk=pk, trang_thai="hien",
        )
        if community.loai_cong_dong == CongDong.Type.PROJECT and not post.du_an_id:
            from communities.views._chung import du_an_lien_ket

            post.du_an = du_an_lien_ket(community)
        return post
    if project_id is not None:
        from projects.permissions import project_access, readable_project_posts

        project, _ = project_access(request.user, project_id)
        post = get_object_or_404(readable_project_posts(request.user, project), pk=pk)
        post.du_an = project
        return post
    post = get_object_or_404(accessible_posts(request.user), pk=pk)
    if not post.du_an_id and post.cong_dong_id and post.cong_dong.loai_cong_dong == CongDong.Type.PROJECT:
        post.du_an = post.cong_dong.du_an_lien_ket
    return post


def _may_interact(user, post):
    if post.da_xoa_mem or post.trang_thai != "hien":
        return False
    if post.du_an_id:
        return not post.du_an.da_luu_tru
    if post.cong_dong_id:
        from communities.views._chung import tu_cach

        return tu_cach(user, post.cong_dong) is not None
    return True


def _check_interaction(user, post):
    if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists() or not _may_interact(user, post):
        raise PermissionDenied("Bạn không có quyền bình luận hoặc bày tỏ cảm xúc trong phạm vi này.")


def _lock_interaction_source(post):
    if post.du_an_id:
        DuAn.objects.filter(pk=post.du_an_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    if post.cong_dong_id:
        CongDong.objects.filter(pk=post.cong_dong_id).update(ngay_cap_nhat=F("ngay_cap_nhat"))
    BaiViet.objects.filter(pk=post.pk).update(ngay_cap_nhat=F("ngay_cap_nhat"))


def _session_token(request):
    nonce = request.session.get("_social_comment_nonce")
    if not nonce:
        nonce = uuid.uuid4().hex
        request.session["_social_comment_nonce"] = nonce
    return signing.dumps(
        {"u": request.user.pk, "s": nonce, "key": uuid.uuid4().hex}, salt="social.comments.v2"
    )


def _comment_key(request, token):
    try:
        data = signing.loads(token, salt="social.comments.v2", max_age=4 * 60 * 60)
        if data["u"] == request.user.pk and data["s"] == request.session.get("_social_comment_nonce"):
            return uuid.UUID(data["key"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        pass
    # Các biểu mẫu đang mở trước khi cập nhật vẫn dùng được trong phiên cũ.
    if token in request.session.get("_social_comment_tokens", []):
        try:
            return uuid.UUID(token)
        except (TypeError, ValueError):
            pass
    return None


def _has_session_token(request, token):
    from projectp.models import NhatKyNghiepVu

    key = _comment_key(request, token)
    return bool(
        key
        and not NhatKyNghiepVu.objects.filter(
            nguoi_dung=request.user,
            hanh_dong__in=["tao_binh_luan_bai_viet", "cap_nhat_bai_viet_ca_nhan"],
            ma_yeu_cau=key,
        ).exists()
    )


def _consume_session_token(request, token):
    tokens = request.session.get("_social_comment_tokens", [])
    if token not in tokens:
        return False
    tokens.remove(token)
    request.session["_social_comment_tokens"] = tokens
    return True


def _accessible_notices(user):
    candidates = ThongBaoChinhThuc.objects.filter(
        trang_thai="da_cong_bo",
        bai_viet__da_xoa_mem=False,
        bai_viet__trang_thai="hien",
        bai_viet__loai_bai_viet=BaiViet.Kind.ANNOUNCEMENT,
    ).select_related("bai_viet", "bai_viet__nguoi_dang", "nguoi_xuat_ban")
    return [notice for notice in candidates if can_read_notice(user, notice)]


def _log_comment(request, comment, request_key=None):
    from projectp.models import NhatKyNghiepVu

    NhatKyNghiepVu.objects.create(
        nguoi_dung=request.user,
        hanh_dong="tao_binh_luan_bai_viet",
        loai_tai_nguyen="BINH_LUAN",
        ma_tai_nguyen=str(comment.pk),
        du_lieu_sau={"ma_bai_viet": comment.bai_viet_id, "ma_binh_luan_cha": comment.binh_luan_cha_id},
        dia_chi_ip=request.META.get("REMOTE_ADDR"),
        ma_yeu_cau=request_key or uuid.uuid4(),
    )


def _feed_sidebar_context(user):
    """Current-user profile, memberships and notices for the three-column feed."""
    profile = HoSoNhanVien.objects.select_related("phong_ban", "vi_tri").filter(nguoi_dung=user).first()

    project_memberships = list(
        active_memberships(user)
        .select_related("du_an")
        .filter(
            nguoi_dung=user,
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
            du_an_id__in=readable_projects(user).values("pk"),
        )
        .order_by("du_an__ten_du_an")[:3]
    )
    community_ids = list(
        ThanhVienCongDong.objects.filter(
            nguoi_dung=user,
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
            cong_dong__da_xoa_mem=False,
        ).values_list("cong_dong_id", flat=True)
    )
    community_memberships = list(
        ThanhVienCongDong.objects.select_related("cong_dong")
        .filter(
            nguoi_dung=user,
            trang_thai=MemberStatus.ACTIVE,
            ket_thuc_luc__isnull=True,
            cong_dong__da_xoa_mem=False,
        )
        .order_by("cong_dong__ten_cong_dong")[:3]
    )

    # Only company-wide communities and communities of which the user is an
    # active member are suggested. Members-only communities remain private.
    visible_communities = (
        CongDong.objects.filter(da_xoa_mem=False)
        .filter(Q(loai_cong_dong="chung", pham_vi_truy_cap="noi_bo") | Q(pk__in=community_ids))
        .annotate(
            social_member_count=Count(
                "thanh_vien",
                filter=Q(
                    thanh_vien__trang_thai=MemberStatus.ACTIVE,
                    thanh_vien__ket_thuc_luc__isnull=True,
                ),
                distinct=True,
            )
        )
        .order_by("-social_member_count", "ten_cong_dong")[:3]
    )

    official_notices = _accessible_notices(user)
    official_notices.sort(
        key=lambda item: item.ngay_xuat_ban or item.ngay_tao,
        reverse=True,
    )
    official_notices = official_notices[:3]
    for notice in official_notices:
        recipient = NguoiNhanThongBao.objects.filter(
            thong_bao_id=notice.pk,
            nguoi_dung=user,
        ).first()
        notice.social_ack_pending = bool(
            notice.yeu_cau_xac_nhan
            and recipient
            and recipient.bat_buoc_xac_nhan
            and recipient.trang_thai_tiep_nhan == "chua_xac_nhan"
            and recipient.ngay_xac_nhan is None
        )

    full_name = ho_ten(user)
    return {
        "profile": profile,
        "display_name": full_name,
        "project_memberships": project_memberships,
        "community_memberships": community_memberships,
        "suggested_communities": visible_communities,
        "sidebar_notices": official_notices,
        "has_profile": profile is not None,
    }


def _feed_page_context(request, tab, post_form=None, modal_open=False):
    can_post = can_create_company_post(request.user)
    notices = _accessible_notices(request.user) if tab == "official" else []
    if tab == "official":
        notices.sort(
            key=lambda item: item.ngay_xuat_ban or item.ngay_tao,
            reverse=True,
        )
        posts = []
    else:
        visible_posts = accessible_posts(request.user)
        if tab == "for_you":
            from communities.views._chung import active_community_memberships

            communities = active_community_memberships(request.user).values("cong_dong_id")
            visible_posts = visible_posts.filter(
                Q(du_an__isnull=False) | Q(cong_dong__isnull=True) | Q(cong_dong_id__in=communities)
            )
        posts = _post_cards(visible_posts, request.user)

    context = {
        "active_tab": tab,
        "posts": posts,
        "notices": notices,
        "can_post": can_post,
        "post_modal_source": "feed",
        "post_modal_open": modal_open,
        **_feed_sidebar_context(request.user),
    }
    if can_post:
        context["post_form"] = post_form or PostForm(initial={"request_token": issue_post_token(request)})
    return context


@login_required(login_url="accounts:login")
def feed(request):
    tab = request.GET.get("tab", "for_you")
    if tab not in {"for_you", "latest", "official"}:
        tab = "for_you"
    try:
        return render(request, "social/feed.html", _feed_page_context(request, tab))
    except DatabaseError:
        return render(request, "social/feed.html", {
            "active_tab": tab, "feed_load_failed": True, "retry_url": request.get_full_path(),
        }, status=503)


@login_required(login_url="accounts:login")
def post_detail(request, pk):
    post = accessible_posts(request.user).filter(pk=pk).first()
    if post is None:
        return render(request, "social/unavailable.html", status=404)
    origin = listing_origin(request, community_id=post.cong_dong_id, project_id=post.du_an_id)
    if post.du_an_id and post.che_do_xu_ly:
        return redirect(with_listing_origin(reverse("projects:issue", args=[post.du_an_id, post.pk]), origin))
    if post.du_an_id:
        return redirect(with_listing_origin(reverse("projects:post_detail", args=[post.du_an_id, post.pk]), origin))
    if post.cong_dong_id:
        return redirect(with_listing_origin(reverse("communities:post", args=[post.cong_dong_id, post.pk]), origin))
    return render(request, "social/post_detail.html", post_discussion_context(request, post))


def post_discussion_context(request, post):
    comments = list(
        BinhLuan.objects.filter(
            bai_viet=post,
            da_xoa_mem=False,
        )
        .select_related("nguoi_dung", "binh_luan_cha")
        .order_by("ngay_tao", "ma_binh_luan")
    )

    children = defaultdict(list)
    roots = []
    for comment in comments:
        comment.reply_token = _session_token(request)
        comment.replies = children.get(comment.pk, [])
        if comment.binh_luan_cha_id:
            children[comment.binh_luan_cha_id].append(comment)
        else:
            roots.append(comment)
    # Re-attach after the complete tree has been assembled (supports nested replies).
    for comment in comments:
        comment.replies = children.get(comment.pk, [])

    attachments = DinhKem.objects.filter(
        bai_viet=post,
        tep_tin__trang_thai="san_sang",
        tep_tin__da_xoa_mem=False,
    ).select_related("tep_tin", "nguoi_dinh_kem")
    liked = CamXuc.objects.filter(bai_viet=post, nguoi_dung=request.user).first()
    saved = BaiVietDaLuu.objects.filter(bai_viet=post, nguoi_dung=request.user).exists()

    context = {
        "post": post,
        "post_return_url": post_return_url(request),
        "post_listing_origin": listing_origin(request, community_id=post.cong_dong_id, project_id=post.du_an_id),
        "comments": roots,
        "children": children,
        "attachments": attachments,
        "liked_reaction": liked,
        "is_saved": saved,
        "comment_form": CommentForm(initial={"request_token": _session_token(request)}),
        "reaction_choices": CamXuc._meta.get_field("loai_cam_xuc").choices,
    }
    context["can_interact"] = _may_interact(request.user, post)
    post.interaction_permitted = context["can_interact"]
    context["can_comment"] = context["can_interact"] and not post.che_do_xu_ly
    return context


def _render_post_modal_error(request, form):
    source = request.POST.get("source_context", "")
    if source == "home":
        from core.services import build_home_context

        context = build_home_context(request.user)
        context.update(
            {
                "can_post": True,
                "post_form": form,
                "post_modal_source": "home",
                "post_modal_open": True,
                "active_tab": "for_you",
            }
        )
        return render(request, "core/home.html", context)

    if source == "feed":
        tab = request.POST.get("return_tab", "for_you")
        if tab not in {"for_you", "latest", "official"}:
            tab = "for_you"
        return render(
            request, "social/feed.html", _feed_page_context(request, tab, post_form=form, modal_open=True)
        )

    return render(
        request,
        "social/post_form.html",
        {
            "form": form,
            "page_title": "Tạo bài viết",
        },
    )


@login_required(login_url="accounts:login")
def create_post(request):
    if not can_create_company_post(request.user):
        raise PermissionDenied("Tài khoản chưa có quyền đăng bài hoặc chưa có hồ sơ nhân viên OZZONE.")

    if request.method == "GET":
        form = PostForm(initial={"request_token": issue_post_token(request)})
        return render(
            request,
            "social/post_form.html",
            {
                "form": form,
                "page_title": "Tạo bài viết",
            },
        )

    form = PostForm(request.POST, request.FILES)
    if form.is_valid():
        token = form.cleaned_data["request_token"]
        if not has_post_token(request, token):
            form.add_error(
                None,
                "Biểu mẫu đã hết hiệu lực hoặc yêu cầu cũ đã được xử lý. Bạn có thể gửi lại với mã yêu cầu mới.",
            )
            replacement_token = issue_post_token(request)
            form.data = form.data.copy()
            form.data["request_token"] = replacement_token
            return _render_post_modal_error(request, form)

        try:
            post = create_company_post(
                user=request.user,
                title=form.cleaned_data["tieu_de"],
                content=form.cleaned_data["noi_dung"],
                files=form.cleaned_data["tep_dinh_kem"],
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc.messages if isinstance(exc, ValidationError) else str(exc))
        except Exception:
            form.add_error(None, "Không thể lưu bài viết. Dữ liệu cũ vẫn được giữ; vui lòng thử lại.")
        else:
            consume_post_token(request, token)
            messages.success(request, "Bài viết đã được đăng lên bảng tin công ty.")
            return redirect(f"{reverse('social:feed')}?tab=latest#post-{post.pk}")

    return _render_post_modal_error(request, form)


@login_required(login_url="accounts:login")
@require_POST
def create_comment(request, pk, community_id=None, project_id=None):
    post = _interaction_post(request, pk, community_id=community_id, project_id=project_id)
    _check_interaction(request.user, post)
    if post.che_do_xu_ly:
        raise PermissionDenied("Trao đổi kỹ thuật và vòng đời dự án được kiểm tra trong không gian dự án.")
    token = request.POST.get("request_token", "")
    if not _has_session_token(request, token):
        messages.info(request, "Yêu cầu này đã được xử lý hoặc biểu mẫu đã hết hiệu lực.")
        return _interaction_redirect(request, post, community_id=community_id, project_id=project_id, comments=True)

    content = (request.POST.get("noi_dung") or "").strip()
    parent_id = request.POST.get("binh_luan_cha")
    if not content or len(content) > 5000:
        messages.error(request, "Bình luận không được để trống và tối đa 5.000 ký tự.")
        return _interaction_redirect(request, post, community_id=community_id, project_id=project_id, comments=True)

    parent = None
    if parent_id:
        parent = get_object_or_404(BinhLuan, pk=parent_id, bai_viet=post, da_xoa_mem=False)

    comment = BinhLuan(
        bai_viet=post,
        nguoi_dung=request.user,
        binh_luan_cha=parent,
        noi_dung=content,
    )
    try:
        comment.full_clean()
        with transaction.atomic():
            _lock_interaction_source(post)
            post = _interaction_post(request, pk, community_id=community_id, project_id=project_id)
            _check_interaction(request.user, post)
            if not _has_session_token(request, token):
                messages.info(request, "Yêu cầu này đã được xử lý hoặc biểu mẫu đã hết hiệu lực.")
                return _interaction_redirect(request, post, community_id=community_id, project_id=project_id, comments=True)
            if post.du_an_id:
                if post.du_an.da_luu_tru or post.che_do_xu_ly:
                    raise PermissionDenied("Dự án không còn cho phép thêm bình luận tại đây.")
            if parent_id:
                comment.binh_luan_cha = get_object_or_404(
                    BinhLuan, pk=parent_id, bai_viet=post, da_xoa_mem=False
                )
            comment.save()
            _log_comment(request, comment, _comment_key(request, token))
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        _consume_session_token(request, token)
        messages.success(request, "Bình luận đã được gửi.")
    return _interaction_redirect(request, post, community_id=community_id, project_id=project_id, comments=True)


@login_required(login_url="accounts:login")
@require_POST
def set_reaction(request, pk, community_id=None, project_id=None):
    post = _interaction_post(request, pk, community_id=community_id, project_id=project_id)
    desired = request.POST.get("state") == "on"
    kind = request.POST.get("loai_cam_xuc", "thich")
    if kind not in REACTION_CHOICES:
        raise PermissionDenied("Loại cảm xúc không hợp lệ.")

    # Desired-state endpoint: gửi lại cùng request không tạo bản ghi trùng/đảo trạng thái.
    with transaction.atomic():
        _lock_interaction_source(post)
        post = _interaction_post(request, pk, community_id=community_id, project_id=project_id)
        _check_interaction(request.user, post)
        if desired:
            CamXuc.objects.update_or_create(
                bai_viet=post,
                nguoi_dung=request.user,
                defaults={"loai_cam_xuc": kind},
            )
        else:
            CamXuc.objects.filter(bai_viet=post, nguoi_dung=request.user).delete()
    return _interaction_redirect(request, post, community_id=community_id, project_id=project_id)


@login_required(login_url="accounts:login")
@require_POST
def set_saved(request, pk, community_id=None, project_id=None):
    post = _interaction_post(request, pk, community_id=community_id, project_id=project_id)
    desired = request.POST.get("state") == "on"
    with transaction.atomic():
        _lock_interaction_source(post)
        post = _interaction_post(request, pk, community_id=community_id, project_id=project_id)
        if desired:
            BaiVietDaLuu.objects.get_or_create(bai_viet=post, nguoi_dung=request.user)
        else:
            BaiVietDaLuu.objects.filter(bai_viet=post, nguoi_dung=request.user).delete()
    return _interaction_redirect(request, post, community_id=community_id, project_id=project_id)


@login_required(login_url="accounts:login")
def saved_posts(request):
    return redirect("knowledge:saved")


@login_required(login_url="accounts:login")
def my_posts(request):
    q = request.GET.get("q", "").strip()[:100]
    scope = request.GET.get("scope", "")
    scopes = {
        "company": Q(du_an__isnull=True, cong_dong__isnull=True),
        "community": Q(du_an__isnull=True, cong_dong__isnull=False),
        "project": Q(du_an__isnull=False),
    }
    if scope not in scopes:
        scope = ""
    visible_posts = accessible_posts(request.user)
    posts = BaiViet.objects.filter(
        nguoi_dang=request.user,
        da_xoa_mem=False,
        loai_bai_viet__in=[BaiViet.Kind.STANDARD, BaiViet.Kind.FIELD_UPDATE],
    ).select_related("cong_dong", "du_an").order_by("-ngay_tao", "-ma_bai_viet")
    if q or scope:
        posts = posts.filter(pk__in=visible_posts.values("pk"))
    if q:
        posts = posts.filter(Q(tieu_de__icontains=q) | Q(noi_dung__icontains=q))
    if scope:
        posts = posts.filter(scopes[scope])
    posts = list(posts.annotate(visible_to_owner=Exists(visible_posts.filter(pk=OuterRef("pk")))))
    for post in posts:
        if post.visible_to_owner:
            post.can_manage, post.manage_reason = can_manage_own_post(request.user, post)
    return render(request, "social/my_posts.html", {"posts": posts, "q": q, "scope": scope})


def _post_management_blocked(request, post, reason, visible):
    source_url = reverse("social:post_detail", args=[post.pk]) if visible else ""
    return render(request, "social/action_blocked.html", {
        "reason": reason if visible else "Bạn không còn quyền đọc nội dung bài viết này.",
        "source_url": source_url,
        "return_url": listing_origin(request) or reverse("social:my_posts"),
    }, status=403)


@login_required(login_url="accounts:login")
def edit_post(request, pk):
    post = get_object_or_404(
        BaiViet.objects.filter(
            nguoi_dang=request.user,
            da_xoa_mem=False,
            loai_bai_viet__in=[BaiViet.Kind.STANDARD, BaiViet.Kind.FIELD_UPDATE],
        ),
        pk=pk,
    )
    visible = accessible_posts(request.user).filter(pk=post.pk).exists()
    if not visible:
        return _post_management_blocked(request, post, "", visible)
    allowed, reason = can_manage_own_post(request.user, post)
    if not allowed:
        return _post_management_blocked(request, post, reason, visible)

    current_attachments = DinhKem.objects.filter(bai_viet=post).select_related("tep_tin")
    initial = (
        {
            "tieu_de": post.tieu_de,
            "noi_dung": post.noi_dung,
            "request_token": _session_token(request),
        }
        if request.method == "GET"
        else None
    )
    form = PostForm(request.POST or None, request.FILES or None, initial=initial)
    form.fields["remove_attachment_ids"].choices = [
        (str(item.pk), item.tep_tin.ten_tep) for item in current_attachments
    ]

    if request.method == "POST" and form.is_valid():
        token = form.cleaned_data.get("request_token", "")
        if not _has_session_token(request, token):
            messages.info(request, "Yêu cầu chỉnh sửa này đã được xử lý hoặc biểu mẫu đã hết hiệu lực.")
            return redirect("social:my_posts")
        try:
            update_company_post(
                post=post,
                user=request.user,
                title=form.cleaned_data["tieu_de"],
                content=form.cleaned_data["noi_dung"],
                files=form.cleaned_data["tep_dinh_kem"],
                remove_attachment_ids=form.cleaned_data["remove_attachment_ids"],
                request=request,
            )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc.messages if isinstance(exc, ValidationError) else str(exc))
        except Exception:
            form.add_error(
                None, "Không thể lưu thay đổi. Tệp và nội dung cũ được giữ lại; vui lòng kiểm tra và thử lại."
            )
        else:
            _consume_session_token(request, token)
            messages.success(request, "Bài viết đã được cập nhật.")
            return redirect("social:post_detail", pk=post.pk)

    return render(
        request,
        "social/post_form.html",
        {
            "form": form,
            "page_title": "Chỉnh sửa bài viết",
            "post": post,
            "current_attachments": current_attachments,
            "editing": True,
        },
    )


@login_required(login_url="accounts:login")
@require_POST
def delete_post(request, pk):
    post = get_object_or_404(
        BaiViet.objects.filter(
            nguoi_dang=request.user,
            da_xoa_mem=False,
            loai_bai_viet__in=[BaiViet.Kind.STANDARD, BaiViet.Kind.FIELD_UPDATE],
        ),
        pk=pk,
    )
    visible = accessible_posts(request.user).filter(pk=post.pk).exists()
    if not visible:
        return _post_management_blocked(request, post, "", visible)
    allowed, reason = can_manage_own_post(request.user, post)
    if not allowed:
        return _post_management_blocked(request, post, reason, visible)
    try:
        soft_delete_post(post=post, user=request.user, request=request)
    except PermissionDenied as exc:
        visible = accessible_posts(request.user).filter(pk=post.pk).exists()
        return _post_management_blocked(request, post, str(exc), visible)
    except DatabaseError:
        messages.error(request, "Chưa thể xóa bài viết. Vui lòng tải lại và thử lại.")
        return redirect("social:my_posts")
    messages.success(request, "Bài viết đã được xóa mềm. Lịch sử và liên kết tệp được giữ lại.")
    return redirect("social:my_posts")


@login_required(login_url="accounts:login")
def attachment_download(request, attachment_id, community_id=None):
    attachment = DinhKem.objects.select_related("tep_tin", "bai_viet").filter(
        pk=attachment_id, bai_viet__isnull=False,
    ).first()
    if attachment is None:
        post_id = request.GET.get("post", "")
        post = None
        if post_id.isascii() and post_id.isdecimal() and len(post_id) <= 18:
            try:
                post = _interaction_post(request, int(post_id), community_id=community_id)
            except (Http404, PermissionDenied):
                pass
        return render(request, "social/file_unavailable.html", {
            "post_id": post.pk if post else None,
        }, status=404)
    # Recheck source rights every time; having a saved URL/file reference is not permission.
    try:
        _interaction_post(request, attachment.bai_viet_id, community_id=community_id)
    except (Http404, PermissionDenied):
        return render(request, "social/unavailable.html", status=404)
    try:
        if attachment.tep_tin.da_xoa_mem or attachment.tep_tin.trang_thai != "san_sang":
            raise FileNotFoundError
        file_handle = attachment.tep_tin.tep.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        return render(request, "social/file_unavailable.html", {
            "post_id": attachment.bai_viet_id,
            "retry_url": request.get_full_path(),
        }, status=404)
    file = attachment.tep_tin
    previewable = file.loai_tep in {
        "image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf",
    }
    return FileResponse(
        file_handle, as_attachment=not (request.GET.get("preview") == "1" and previewable),
        filename=file.ten_tep, content_type=file.loai_tep or "application/octet-stream",
    )


@login_required(login_url="accounts:login")
def notice_detail(request, pk):
    return redirect("notifications:detail", pk=pk)
