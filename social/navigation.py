"""Liên kết bài đăng giữ đúng phân hệ và đối tượng đang mở."""
from urllib.parse import urlencode, urlsplit

from django.http import HttpResponseRedirect
from django.urls import resolve, reverse, Resolver404
from django.utils.http import url_has_allowed_host_and_scheme


def post_navigation(request, post, *, community_id=None, project_id=None):
    match = request.resolver_match
    namespace = match.namespace if match else "social"
    if community_id is None and namespace == "communities":
        community_id = match.kwargs.get("community_id") or match.kwargs.get("pk")
    if project_id is None and namespace == "projects":
        project_id = match.kwargs.get("project_id") or match.kwargs.get("pk")
    if community_id is not None:
        namespace = "communities"
        detail = reverse("communities:post", args=[community_id, post.pk])
        scope = {"community_id": community_id, "pk": post.pk}
    elif project_id is not None:
        namespace = "projects"
        detail = reverse("projects:post_detail", args=[project_id, post.pk])
        scope = {"project_id": project_id, "pk": post.pk}
    else:
        namespace = "social"
        detail = reverse("social:post_detail", args=[post.pk])
        scope = {"pk": post.pk}
    comments = detail + "#comments"
    if namespace == "projects" and post.che_do_xu_ly:
        detail = reverse("projects:issue", args=[project_id, post.pk])
        comments = detail + "#analysis"
    return {
        "detail": detail,
        "comments": comments,
        "comment_create": reverse(namespace + ":comment_create", kwargs=scope),
        "reaction_set": reverse(namespace + ":reaction_set", kwargs=scope),
        "save_set": reverse(namespace + ":save_set", kwargs=scope),
        "namespace": namespace,
        "scope_id": community_id if namespace == "communities" else project_id,
    }


def interaction_redirect(request, post, *, community_id=None, project_id=None, comments=False):
    links = post_navigation(request, post, community_id=community_id, project_id=project_id)
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        try:
            match = resolve(urlsplit(target).path)
        except Resolver404:
            match = None
        if match and (links["namespace"] == "social" or match.namespace == links["namespace"]):
            target_scope = (
                match.kwargs.get("community_id")
                or match.kwargs.get("project_id")
                or match.kwargs.get("pk")
            )
            if links["namespace"] == "social" or target_scope == links["scope_id"]:
                return HttpResponseRedirect(target)
    return_to = _allowed_listing(
        request, request.POST.get("return_to", ""), community_id=community_id, project_id=project_id,
    )
    detail = with_listing_origin(links["detail"], return_to)
    if comments:
        detail += "#" + links["comments"].partition("#")[2]
    return HttpResponseRedirect(detail)


def _allowed_listing(request, candidate, *, community_id=None, project_id=None):
    if not candidate or not url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return ""
    try:
        match = resolve(urlsplit(candidate).path)
    except Resolver404:
        return ""
    if match.view_name in {
        "social:feed", "social:saved", "social:my_posts", "core:home",
        "knowledge:search", "knowledge:filter", "knowledge:saved",
    }:
        return candidate
    if match.view_name == "projects:feed" and project_id is not None and match.kwargs["pk"] == project_id:
        return candidate
    if match.view_name == "communities:detail" and community_id is not None and match.kwargs["pk"] == community_id:
        return candidate
    return ""


def listing_origin(request, *, community_id=None, project_id=None):
    """Find the permitted listing that opened this post."""
    for candidate in (request.GET.get("next", ""), request.META.get("HTTP_REFERER", "")):
        return_to = _allowed_listing(request, candidate, community_id=community_id, project_id=project_id)
        if return_to:
            return return_to
    return ""


def with_listing_origin(detail, origin):
    if origin:
        return detail + "?" + urlencode({"next": origin})
    return detail


def post_return_url(request):
    return listing_origin(request) or reverse("social:feed")
