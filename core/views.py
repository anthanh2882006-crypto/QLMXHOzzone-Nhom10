from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from social.forms import PostForm
from social.permissions import can_create_company_post
from social.tokens import issue_post_token

from .services import build_home_context


@login_required(login_url="accounts:login")
def home(request):
    context = build_home_context(request.user)
    context["can_post"] = can_create_company_post(request.user)
    context["post_modal_source"] = "home"
    context["active_tab"] = "for_you"
    if context["can_post"]:
        context["post_form"] = PostForm(initial={"request_token": issue_post_token(request)})
    return render(request, "core/home.html", context)
