"""Short-lived, session-bound tokens for personal post submissions."""
from uuid import uuid4


SESSION_KEY = "_social_post_tokens"
MAX_TOKENS = 60


def issue_post_token(request):
    token = uuid4().hex
    tokens = request.session.get(SESSION_KEY, [])
    tokens.append(token)
    request.session[SESSION_KEY] = tokens[-MAX_TOKENS:]
    return token


def has_post_token(request, token):
    return bool(token and token in request.session.get(SESSION_KEY, []))


def consume_post_token(request, token):
    tokens = request.session.get(SESSION_KEY, [])
    if token not in tokens:
        return False
    tokens.remove(token)
    request.session[SESSION_KEY] = tokens
    return True
