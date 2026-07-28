from django.urls import path

from . import views, views_users

app_name = "accounts"

urlpatterns = [
    # Session lifecycle
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    # Profile
    path("me/", views.MeView.as_view(), name="me"),
    path("me/avatar/", views_users.MeAvatarView.as_view(), name="me-avatar"),
    # Passwords
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password/", views.ResetPasswordView.as_view(), name="reset-password"),
    # Email verification
    path(
        "send-verification-email/",
        views.SendVerificationEmailView.as_view(),
        name="send-verification-email",
    ),
    path("verify-email/", views.VerifyEmailView.as_view(), name="verify-email"),
]
