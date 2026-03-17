from django.urls import path
from accounts.views import auth_connect, tokens, callback, jobber_connect, jobber_callback


urlpatterns = [
    path("auth/connect/", auth_connect, name="oauth_connect"),
    path("auth/tokens/", tokens, name="oauth_tokens"),
    path("auth/callback/", callback, name="oauth_callback"),
    path("jobber/connect/", jobber_connect, name="jobber_connect"),
    path("jobber/callback/", jobber_callback, name="jobber_callback"),
]