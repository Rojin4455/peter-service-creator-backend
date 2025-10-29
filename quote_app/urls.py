# user_urls.py - URL patterns for user-side functionality
from django.urls import path
from . import views

urlpatterns = [
    # ============================================================================
    # QUOTE GENERATOR FLOW
    # ============================================================================
    # Step 1: Get initial data (locations, services, size ranges)
    path('initial-data/', views.InitialDataView.as_view(), name='initial-data'),
    # Step 2: Create customer submission
    path('create-submission/', views.CustomerSubmissionCreateView.as_view(), name='create-submission'),
    
    # Step 3: Add services to submission
    path('<uuid:submission_id>/add-services/', views.AddServicesToSubmissionView.as_view(), name='add-services'),
    
    # Step 4: Get questions for a service
    path('services/<uuid:service_id>/questions/', views.ServiceQuestionsView.as_view(), name='service-questions'),
    
    # Step 5: Get conditional questions
    path('conditional-questions/', views.ConditionalQuestionsView.as_view(), name='conditional-questions'),
    
    # Step 6: Submit service responses
    path('<uuid:submission_id>/services/<uuid:service_id>/responses/', views.SubmitServiceResponsesView.as_view(), name='submit-responses'),
    
    # Step 7: Get submission details with quotes
    path('<uuid:id>/', views.SubmissionDetailView.as_view(), name='submission-detail'),
    
    # Step 8: Submit final quote
    path('<uuid:submission_id>/submit/', views.SubmitFinalQuoteView.as_view(), name='submit-quote'),

    path("submissions/<uuid:submission_id>/availability/", views.CustomerAvailabilityView.as_view(), name="customer-availability"),

    
    # ============================================================================
    # UTILITY ENDPOINTS
    # ============================================================================
    
    # Check submission status
    path('<uuid:submission_id>/status/', views.SubmissionStatusView.as_view(), name='submission-status'),
    # Get service packages
    path('services/<uuid:service_id>/packages/', views.ServicePackagesView.as_view(), name='service-packages'),

    path("addons/", views.AddOnServiceListView.as_view(), name="addon-list"),
    path("submissions/<uuid:submission_id>/addons/", views.AddAddOnsToSubmissionView.as_view(), name="submission-addons"),

    path(
        "submissions/<uuid:submission_id>/decline/",
        views.DeclineSubmissionView.as_view(),
        name="decline-submission",
    ),




    path("coupons/", views.CouponListView.as_view(), name="coupon-list"),
    path("coupons/<str:code>/", views.CouponDetailView.as_view(), name="coupon-detail"),
    path("coupons/apply/", views.ApplyCouponView.as_view(), name="coupon-apply"),
    path("coupons-apply/", views.ApplyCouponView.as_view(), name="coupon-apply"),
]
