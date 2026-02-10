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

    # Remove a service from submission
    path(
        '<uuid:submission_id>/services/<uuid:service_id>/remove/',
        views.RemoveServiceFromSubmissionView.as_view(),
        name='remove-service-from-submission',
    ),
    
    # Step 4: Get questions for a service
    path('services/<uuid:service_id>/questions/', views.ServiceQuestionsView.as_view(), name='service-questions'),
    
    # Step 5: Get conditional questions
    path('conditional-questions/', views.ConditionalQuestionsView.as_view(), name='conditional-questions'),
    
    # Step 6: Submit service responses
    path('<uuid:submission_id>/services/<uuid:service_id>/responses/', views.SubmitServiceResponsesView.as_view(), name='submit-responses'),

    path('<uuid:submission_id>/services/<uuid:service_id>/responses/edit/',views.EditServiceResponsesView.as_view(), name='edit-service-responses'),
    
    # Step 7: Get submission details with quotes
    path('<uuid:id>/', views.SubmissionDetailView.as_view(), name='submission-detail'),
    
    # Admin endpoint to update submission notes
    path('<uuid:submission_id>/notes/', views.UpdateSubmissionNotesView.as_view(), name='update-submission-notes'),

    # Update submission sqft and recalculate package prices (same logic as submit-responses)
    path('<uuid:submission_id>/sqft/', views.UpdateSubmissionSqftView.as_view(), name='update-submission-sqft'),

    # Quote images (GHL media): list, upload, delete
    path('<uuid:submission_id>/images/', views.ListQuoteImagesView.as_view(), name='quote-images-list'),
    path('<uuid:submission_id>/images/upload/', views.UploadQuoteImageView.as_view(), name='quote-images-upload'),
    path('<uuid:submission_id>/images/<uuid:image_id>/', views.DeleteQuoteImageView.as_view(), name='quote-images-delete'),
    
    # Admin endpoint to update package price
    path('package-quotes/<uuid:quote_id>/price/', views.UpdatePackagePriceView.as_view(), name='update-package-price'),
    
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
    path("coupons/global/", views.GlobalCouponListView.as_view(), name="global-coupons-list"),
    path("coupons/apply/", views.ApplyCouponView.as_view(), name="coupon-apply"),
    path("coupons-apply/", views.ApplyCouponView.as_view(), name="coupon-apply"),
    path("coupons/<str:code>/", views.CouponDetailView.as_view(), name="coupon-detail"),
]
