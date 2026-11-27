"""Version 1 of the public REST API (shared by the web panel and the mobile apps)."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.policy_views import PlatformPolicyView
from apps.accounts.views import AdminViewSet, UserViewSet
from apps.ceremonies.views import (
    CeremonyViewSet,
    InvitationViewSet,
    MyCeremonyViewSet,
    StudioMeCeremoniesView,
    StudioMeView,
)
from apps.event_planner import admin_views as planner_admin
from apps.event_planner import views as planner_views
from apps.media.admin_views import AdminDeletionRequestViewSet
from apps.monitoring.health import LiveView, ReadyView
from apps.reviews.models import TargetKind
from apps.reviews.views import AdminReviewViewSet, LikeView, MyReviewView, TargetReviewsView
from apps.studios import public_views as studio_views
from apps.studios.public_views import PublicStudioViewSet, StudioMePortfolioImageView, StudioMePortfolioView
from apps.studios.views import StudioViewSet
from apps.backup.views import AdminBackupViewSet, MyBackupView, MyNotificationViewSet
from apps.subscriptions.views import (
    AdminFinanceViewSet,
    AdminPlanViewSet,
    AdminSettingsViewSet,
    AdminSubscriptionViewSet,
    MySubscriptionViewSet,
    PlanListViewSet,
)
from apps.support.applications import PublicApplicationViewSet, StaffApplicationViewSet
from apps.support.views import MySupportTicketViewSet, StaffSupportTicketViewSet
from apps.venues.admin_views import AdminVenueViewSet
from apps.venues.public_views import MyVenueBookingViewSet, PublicVenueViewSet
from apps.venues.views import VenueOwnerVenueViewSet
from apps.virtual_tryon import views as tryon_views
from apps.virtual_tryon.admin_views import (
    AdminCategoryListView,
    AdminGarmentOrderViewSet,
    AdminGarmentViewSet,
    AdminSavedLookViewSet,
    AiUsageView,
)

router = DefaultRouter()
router.include_root_view = False
router.register("users", UserViewSet, basename="user")
router.register("admins", AdminViewSet, basename="admin")
router.register("studios", StudioViewSet, basename="studio")
router.register("ceremonies", CeremonyViewSet, basename="ceremony")
router.register("me/ceremonies", MyCeremonyViewSet, basename="my-ceremony")
router.register("me/invitations", InvitationViewSet, basename="my-invitation")
router.register("venue-owner/venues", VenueOwnerVenueViewSet, basename="venue-owner-venue")
router.register("admin/venues", AdminVenueViewSet, basename="admin-venue")
router.register("venues", PublicVenueViewSet, basename="venue")
router.register("public/studios", PublicStudioViewSet, basename="public-studio")
router.register("admin/reviews", AdminReviewViewSet, basename="admin-review")
router.register("subscriptions/plans", PlanListViewSet, basename="subscription-plan")
router.register("me/subscriptions", MySubscriptionViewSet, basename="my-subscription")
router.register("admin/subscriptions", AdminSubscriptionViewSet, basename="admin-subscription")
router.register("admin/subscription-plans", AdminPlanViewSet, basename="admin-subscription-plan")
router.register("admin/finance", AdminFinanceViewSet, basename="admin-finance")
router.register("admin/backup", AdminBackupViewSet, basename="admin-backup")
router.register("me/notifications", MyNotificationViewSet, basename="my-notification")
router.register("me/venue-bookings", MyVenueBookingViewSet, basename="my-venue-booking")
router.register("admin/media-deletion-requests", AdminDeletionRequestViewSet, basename="admin-media-deletion-request")
router.register("support/tickets", MySupportTicketViewSet, basename="support-ticket")
router.register("admin/support/tickets", StaffSupportTicketViewSet, basename="admin-support-ticket")
router.register("admin/support/applications", StaffApplicationViewSet, basename="admin-partner-application")
router.register("public/partner-applications", PublicApplicationViewSet, basename="public-partner-application")
router.register("virtual-tryon/categories", tryon_views.CategoryViewSet, basename="tryon-category")
router.register("virtual-tryon/garments", tryon_views.GarmentViewSet, basename="tryon-garment")
router.register("virtual-tryon/sessions", tryon_views.SessionViewSet, basename="tryon-session")
router.register("virtual-tryon/favorites", tryon_views.FavoriteViewSet, basename="tryon-favorite")
router.register("admin/virtual-tryon/garments", AdminGarmentViewSet, basename="admin-tryon-garment")
router.register("admin/virtual-tryon/looks", AdminSavedLookViewSet, basename="admin-tryon-look")
router.register("admin/virtual-tryon/orders", AdminGarmentOrderViewSet, basename="admin-tryon-order")
router.register("virtual-tryon/ai-sessions", tryon_views.AiSessionViewSet, basename="tryon-ai-session")
router.register("virtual-tryon/looks", tryon_views.SavedLookViewSet, basename="tryon-look")
router.register("virtual-tryon/orders", tryon_views.GarmentOrderViewSet, basename="tryon-order")
router.register("ai-planner/plans", planner_views.PlanViewSet, basename="ai-plan")
router.register(
    r"ai-planner/plans/(?P<plan_id>[0-9a-fA-F-]{36})/items", planner_views.PlanItemViewSet, basename="ai-plan-item"
)
router.register("ai-planner/conversations", planner_views.ConversationViewSet, basename="ai-conversation")
router.register("ai-planner/messages", planner_views.MessageViewSet, basename="ai-message")
router.register("ai-planner/services", planner_views.ServiceViewSet, basename="ai-service")
router.register("admin/ai-planner/usage", planner_admin.UsageLogViewSet, basename="admin-ai-usage")
router.register("admin/ai-planner/reports", planner_admin.AdminReportViewSet, basename="admin-ai-report")
router.register(
    "admin/ai-planner/conversations", planner_admin.AdminConversationViewSet, basename="admin-ai-conversation"
)
router.register("admin/ai-planner/prompts", planner_admin.PromptViewSet, basename="admin-ai-prompt")
router.register("admin/ai-planner/audit", planner_admin.AuditLogViewSet, basename="admin-ai-audit")

urlpatterns = [
    path(
        "admin/platform-policy/",
        PlatformPolicyView.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="platform-policy",
    ),
    path("auth/", include("apps.accounts.auth_urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("monitoring/", include("apps.monitoring.urls")),
    path("devcenter/", include("apps.devcenter.urls")),
    path("admin/storage/", include("apps.storage.urls")),
    path("health/live/", LiveView.as_view(), name="health-live"),
    path("virtual-tryon/ai/status/", tryon_views.AiStatusView.as_view(), name="tryon-ai-status"),
    path("virtual-tryon/ai/render/", tryon_views.AiRenderView.as_view(), name="tryon-ai-render"),
    path("virtual-tryon/ai/render-video/", tryon_views.AiRenderVideoView.as_view(), name="tryon-ai-render-video"),
    path(
        "virtual-tryon/ai/render-video/<uuid:job_id>/",
        tryon_views.AiRenderVideoJobView.as_view(),
        name="tryon-ai-render-video-job",
    ),
    path("admin/virtual-tryon/ai-usage/", AiUsageView.as_view(), name="admin-tryon-ai-usage"),
    path("admin/virtual-tryon/categories/", AdminCategoryListView.as_view(), name="admin-tryon-categories"),
    path("health/ready/", ReadyView.as_view(), name="health-ready"),
    # AI event planner (apps.event_planner)
    path("ai-planner/status/", planner_views.PlannerStatusView.as_view(), name="ai-planner-status"),
    path("ai-planner/usage/", planner_views.MyUsageView.as_view(), name="ai-planner-usage"),
    path("ai-planner/export/", planner_views.ExportView.as_view(), name="ai-planner-export"),
    path("ai-planner/delete-data/", planner_views.DeleteDataView.as_view(), name="ai-planner-delete-data"),
    path("admin/ai-planner/dashboard/", planner_admin.DashboardView.as_view(), name="admin-ai-dashboard"),
    path("admin/ai-planner/disable/", planner_admin.DisableView.as_view(), name="admin-ai-disable"),
    path("admin/ai-planner/config/", planner_admin.ConfigView.as_view(), name="admin-ai-config"),
    path(
        "admin/ai-planner/config/validate/", planner_admin.ConfigValidateView.as_view(), name="admin-ai-config-validate"
    ),
    # Before the router: "studios/me/" must not be captured by "studios/{id}/".
    path("studios/me/", StudioMeView.as_view(), name="studio-me"),
    path("studios/me/ceremonies/", StudioMeCeremoniesView.as_view(), name="studio-me-ceremonies"),
    path("studios/me/<uuid:studio_id>/images/", StudioMePortfolioView.as_view(), name="studio-me-images"),
    path("studios/me/<uuid:studio_id>/reels/", studio_views.StudioMeReelsView.as_view(), name="studio-me-reels"),
    path(
        "studios/me/<uuid:studio_id>/images/<uuid:image_id>/",
        StudioMePortfolioImageView.as_view(),
        name="studio-me-image",
    ),
    path(
        "studios/me/<uuid:studio_id>/images/<uuid:image_id>/comments/",
        studio_views.StudioMeCommentsView.as_view(),
        name="studio-me-image-comments",
    ),
    path(
        "studios/me/<uuid:studio_id>/images/<uuid:image_id>/comments/<uuid:comment_id>/",
        studio_views.StudioMeCommentView.as_view(),
        name="studio-me-image-comment",
    ),
    path(
        "studios/me/<uuid:studio_id>/schedule/", studio_views.StudioMeScheduleView.as_view(), name="studio-me-schedule"
    ),
    path(
        "studios/me/<uuid:studio_id>/schedule/days/<str:day>/",
        studio_views.StudioMeScheduleDayView.as_view(),
        name="studio-me-schedule-day",
    ),
    path("studios/me/<uuid:studio_id>/chats/", studio_views.StudioMeChatsView.as_view(), name="studio-me-chats"),
    path(
        "studios/me/<uuid:studio_id>/chats/<uuid:conversation_id>/",
        studio_views.StudioMeChatView.as_view(),
        name="studio-me-chat",
    ),
    # studio portfolio interactions and customer ↔ studio chat
    path(
        "public/studios/<uuid:studio_id>/portfolio/<uuid:item_id>/reaction/",
        studio_views.PortfolioReactionView.as_view(),
        name="studio-portfolio-reaction",
    ),
    path(
        "public/studios/<uuid:studio_id>/portfolio/<uuid:item_id>/comments/",
        studio_views.PortfolioCommentsView.as_view(),
        name="studio-portfolio-comments",
    ),
    path(
        "public/studios/<uuid:studio_id>/portfolio/<uuid:item_id>/comments/<uuid:comment_id>/",
        studio_views.PortfolioMyCommentView.as_view(),
        name="studio-portfolio-comment",
    ),
    path(
        "public/studios/<uuid:studio_id>/portfolio/<uuid:item_id>/file/<str:part>/",
        studio_views.PortfolioFileView.as_view(),
        name="studio-portfolio-file",
    ),
    path("studios/me/<uuid:studio_id>/storage/", studio_views.StudioMeStorageView.as_view(), name="studio-me-storage"),
    path("me/studio-chats/", studio_views.MyStudioChatsView.as_view(), name="my-studio-chats"),
    path("me/studio-chats/<uuid:studio_id>/", studio_views.MyStudioChatView.as_view(), name="my-studio-chat"),
    # reviews / likes of public venues and studios
    *[
        p
        for prefix, kind in (("venues", TargetKind.VENUE), ("public/studios", TargetKind.STUDIO))
        for p in (
            path(f"{prefix}/<uuid:target_id>/reviews/", TargetReviewsView.as_view(kind=kind), name=f"{kind}-reviews"),
            path(f"{prefix}/<uuid:target_id>/reviews/mine/", MyReviewView.as_view(kind=kind), name=f"{kind}-my-review"),
            path(f"{prefix}/<uuid:target_id>/like/", LikeView.as_view(kind=kind), name=f"{kind}-like"),
        )
    ],
    path("ceremonies/<uuid:ceremony_id>/media/", include("apps.media.urls")),
    path("me/ceremonies/<uuid:ceremony_id>/media/", include("apps.media.urls_me")),
    path("me/backup/", MyBackupView.as_view(), name="my-backup"),
    path("admin/backup/ceremonies/<uuid:ceremony_id>/media/", include("apps.backup.urls_media")),
    path(
        "admin/subscription-settings/",
        AdminSettingsViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="admin-subscription-settings",
    ),
    path("", include(router.urls)),
]
