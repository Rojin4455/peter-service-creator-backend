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
    
    # ============================================================================
    # UTILITY ENDPOINTS
    # ============================================================================
    
    # Check submission status
    path('<uuid:submission_id>/status/', views.SubmissionStatusView.as_view(), name='submission-status'),
    # Get service packages
    path('services/<uuid:service_id>/packages/', views.ServicePackagesView.as_view(), name='service-packages'),
]
