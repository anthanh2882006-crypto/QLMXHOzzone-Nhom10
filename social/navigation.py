"""Liên kết bài đăng giữ đúng phân hệ và đối tượng đang mở."""
from urllib.parse import urlsplit

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
    return HttpResponseRedirect(links["comments"] if comments else links["detail"])
