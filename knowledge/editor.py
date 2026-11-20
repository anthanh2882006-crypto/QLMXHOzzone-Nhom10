"""GD-089. Luồng biên tập, sao chép nháp và công bố UC-KNW-05."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from projectp.models import BaiVietTriThuc, DinhKem, PhienBanTriThuc
from projects.permissions import readable_projects
from projects.services_common import payload_hash
from .forms import BaiVietTriThucDraftForm
from .services import (
    article_communities, can_edit, check_revision, check_scope, clone_draft, editor_token, publication_audit,
    publish_version, revision, save_draft,
)


PREVIEW_SALT = "ozzone.knowledge.publication"


def identifier(value):
    if not value:
        return None
    if (
        not str(value).isascii()
        or not str(value).isdecimal()
        or len(str(value)) > 19
        or int(value) > 9223372036854775807
    ):
        raise Http404("Định danh nội dung không hợp lệ.")
    return int(value)


def editor_url(version):
    return f"{reverse('knowledge:create')}?article={version.bai_viet_tri_thuc_id}&version={version.pk}"


def publication_submission_hash(request):
    return payload_hash({
        "fields": {
            name: values for name, values in request.POST.lists()
            if name not in {"csrfmiddlewaretoken", "preview_token"}
        },
        "files": dict(request.FILES.lists()),
    })


@login_required(login_url="accounts:login")
def article_editor(request):
    article_id = identifier(request.POST.get("article_id") or request.GET.get("article"))
    version_id = identifier(request.POST.get("version_id") or request.GET.get("version"))
    if request.method == "POST" and request.POST.get("action") == "clone":
        try:
            draft = clone_draft(
                request.user,
                article_id,
                request.POST.get("request_token", ""),
                request.POST.get("revision_token", ""),
            )
        except BaiVietTriThuc.DoesNotExist:
            raise Http404("Bài viết không còn khả dụng.")
        except (ValidationError, DatabaseError) as exc:
            messages.error(
                request,
                (
                    " ".join(exc.messages)
                    if isinstance(exc, ValidationError)
                    else "Chưa tạo được nháp. Bản công bố được giữ để bạn thử lại."
                ),
            )
            return redirect("knowledge:article_detail", pk=article_id)
        return redirect(editor_url(draft))

    action = request.POST.get("action", "save_draft")
    replay_error = None
    if request.method == "POST" and action == "publish":
        try:
            completed = publication_audit(request.user, request.POST.get("request_token", ""), article_id, version_id)
            if completed and completed.du_lieu_sau.get("request_hash"):
                # Reuse the original submission before rebuilding form choices for a changed draft.
                if publication_submission_hash(request) != completed.du_lieu_sau["request_hash"]:
                    raise ValidationError("Mã yêu cầu đã được dùng để công bố nội dung khác.")
                published = get_object_or_404(
                    PhienBanTriThuc.objects.select_related("bai_viet_tri_thuc"),
                    pk=completed.du_lieu_sau["version_id"], bai_viet_tri_thuc_id=completed.ma_tai_nguyen,
                )
                if not request.user.has_perm("projectp.cong_bo_tri_thuc") or not can_edit(
                    request.user, published.bai_viet_tri_thuc
                ):
                    raise PermissionDenied("Bạn không còn quyền công bố bài viết này.")
                check_scope(request.user, published)
                messages.info(request, "Yêu cầu này đã được công bố.")
                return redirect("knowledge:article_detail", pk=published.bai_viet_tri_thuc_id)
        except ValidationError as exc:
            replay_error = exc

    article = version = None
    initial = {}
    if article_id or version_id:
        if not article_id or not version_id:
            raise Http404("Cần đúng bài và phiên bản.")
        article = get_object_or_404(BaiVietTriThuc, pk=article_id, da_xoa_mem=False)
        version = get_object_or_404(PhienBanTriThuc, pk=version_id, bai_viet_tri_thuc=article)
        if not can_edit(request.user, article):
            raise PermissionDenied("Bạn không còn quyền biên tập bài viết này.")
        check_scope(request.user, version)
        if version.trang_thai != "ban_nhap" and request.method != "POST":
            return redirect("knowledge:article_detail", pk=article.pk)
        for field in ("loai_nguon", "tieu_de", "tom_tat", "noi_dung", "pham_vi_ap_dung", "pham_vi_chia_se"):
            initial[field] = getattr(version, field)
        initial.update(
            cong_dong=version.cong_dong_id,
            du_an=version.du_an_id,
            chu_de=list(version.gan_chu_de.values_list("chu_de_id", flat=True)),
            revision_token=revision(article, version),
        )
        reference = version.nguon_tham_khao.order_by("thu_tu", "pk").first()
        if reference:
            initial.update(
                reference_id=reference.pk,
                loai_tham_chieu=reference.loai_tham_chieu,
                tieu_de_nguon=reference.tieu_de_nguon,
                tac_gia=reference.tac_gia,
                url_nguon=reference.url,
                trich_dan=reference.trich_dan,
                bai_viet_nguon=reference.bai_viet_nguon_id,
                tep_nguon=reference.tep_nguon_id,
            )
    elif not can_edit(request.user):
        raise PermissionDenied("Bạn chưa có quyền tạo bài viết tri thức.")
    initial["request_token"] = editor_token(request.user, article_id, version_id)
    form = BaiVietTriThucDraftForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        initial=initial,
        allowed_projects=readable_projects(request.user),
        allowed_communities=article_communities(request.user),
        user=request.user,
        version=version,
    )
    if replay_error:
        form.add_error(None, replay_error)
    if request.method == "POST" and action in {"preview", "publish"}:
        if not request.user.has_perm("projectp.cong_bo_tri_thuc"):
            raise PermissionDenied("Bạn chưa có quyền công bố tri thức.")
        if not form.is_valid() and action == "preview":
            return JsonResponse({"error": " ".join(next(iter(form.errors.values())))}, status=400)
        if form.is_valid():
            fingerprint = payload_hash({
                "user": request.user.pk, "article": article_id, "version": version_id,
                "editor_request": form.cleaned_data["request_token"],
                "fields": {**form.cleaned_data, "chu_de": sorted(topic.pk for topic in form.cleaned_data["chu_de"])},
            })
            if action == "preview":
                return JsonResponse({"token": signing.dumps(fingerprint, salt=PREVIEW_SALT)})
            try:
                reviewed = signing.loads(request.POST.get("preview_token", ""), salt=PREVIEW_SALT, max_age=900)
            except signing.BadSignature:
                reviewed = None
            if reviewed != fingerprint:
                form.add_error(None, "Hãy xem trước và xác nhận lại nội dung trước khi công bố.")

    if request.method == "POST" and form.is_valid():
        if action not in {"save_draft", "publish"}:
            form.add_error(None, "Thao tác không hợp lệ.")
        elif action == "publish" and not request.user.has_perm("projectp.cong_bo_tri_thuc"):
            raise PermissionDenied("Bạn chưa có quyền công bố tri thức.")
        else:
            expected_current_id = article.phien_ban_dang_cong_bo_id if article else None
            saved_revision = None
            try:
                version, saved_revision = save_draft(request.user, form.cleaned_data, article_id, version_id)
                article = version.bai_viet_tri_thuc
                if action == "publish":
                    publish_version(
                        request.user,
                        version,
                        form.cleaned_data["request_token"],
                        article_id,
                        version_id,
                        expected_current_id,
                        saved_revision,
                        publication_submission_hash(request),
                    )
                    messages.success(request, "Đã công bố phiên bản tri thức.")
                    return redirect("knowledge:article_detail", pk=article.pk)
            except (ValidationError, DatabaseError) as exc:
                error = (
                    " ".join(exc.messages) if isinstance(exc, ValidationError)
                    else "Chưa hoàn tất lưu/công bố. Bản đã lưu được giữ để thử lại."
                )
                if saved_revision and version:
                    try:
                        check_revision(article, version, saved_revision)
                    except ValidationError:
                        pass
                    else:
                        # Changes already saved, so retry from their actual draft and choices.
                        messages.error(request, error)
                        return redirect(editor_url(version))
                # When superseded, keep the old token. The editor must reload to see the changes.
                form.add_error(None, error)
            else:
                messages.success(request, "Đã lưu bản nháp.")
                return redirect(editor_url(version))
    return render(
        request,
        "knowledge/article_editor.html",
        {
            "form": form,
            "article": article,
            "version": version,
            "is_editing_draft": version is not None,
            "can_publish": request.user.has_perm("projectp.cong_bo_tri_thuc"),
            "reload_draft_url": editor_url(version) if version and form.errors else "",
            "attachments": (
                DinhKem.objects.filter(phien_ban_tri_thuc=version).select_related("tep_tin")
                if version
                else []
            ),
        },
    )
