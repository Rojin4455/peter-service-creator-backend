# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Admin API URLs
urlpatterns = [
    # Authentication
    path('auth/login/', views.AdminTokenObtainPairView.as_view(), name='admin-login'),
    path('auth/logout/', views.AdminLogoutView.as_view(), name='admin-logout'),

    path('auth/refresh/', views.AdminTokenRefreshView.as_view(), name='token_refresh'),
    
        
    # Locations
    path('locations/', views.LocationListCreateView.as_view(), name='location-list-create'),
    path('locations/<uuid:pk>/', views.LocationDetailView.as_view(), name='location-detail'),
    path('locations/search/google-places/', views.GooglePlacesSearchView.as_view(), name='google-places-search'),
    
    # Services
    path('services/', views.ServiceListCreateView.as_view(), name='service-list-create'),
    path('services/<uuid:pk>/', views.ServiceDetailView.as_view(), name='service-detail'),
    path('services/analytics/', views.ServiceAnalyticsView.as_view(), name='service-analytics'),
    
    # Packages
    path('packages/', views.PackageListCreateView.as_view(), name='package-list-create'),
    path('packages/<uuid:pk>/', views.PackageDetailView.as_view(), name='package-detail'),
    path('packages/<uuid:pk>/features/', views.PackageWithFeaturesView.as_view(), name='package-features'),
    
    # Features
    path('features/', views.FeatureListCreateView.as_view(), name='feature-list-create'),
    path('features/<uuid:pk>/', views.FeatureDetailView.as_view(), name='feature-detail'),
    
    # Package-Feature Relationships
    path('package-features/', views.PackageFeatureListCreateView.as_view(), name='package-feature-list-create'),
    path('package-features/<uuid:pk>/', views.PackageFeatureDetailView.as_view(), name='package-feature-detail'),
    
    # Questions
    path('questions/', views.QuestionListCreateView.as_view(), name='question-list-create'),
    path('questions/<uuid:pk>/', views.QuestionDetailView.as_view(), name='question-detail'),
    
    # Question Options
    path('question-options/', views.QuestionOptionListCreateView.as_view(), name='question-option-list-create'),
    path('question-options/<uuid:pk>/', views.QuestionOptionDetailView.as_view(), name='question-option-detail'),
    
    # Pricing Rules
    path('question-pricing/', views.QuestionPricingListCreateView.as_view(), name='question-pricing-list-create'),
    path('question-pricing/<uuid:pk>/', views.QuestionPricingDetailView.as_view(), name='question-pricing-detail'),
    path('option-pricing/', views.OptionPricingListCreateView.as_view(), name='option-pricing-list-create'),
    path('option-pricing/<uuid:pk>/', views.OptionPricingDetailView.as_view(), name='option-pricing-detail'),
    
    # Bulk Operations
    path('questions/bulk-pricing/', views.BulkQuestionPricingView.as_view(), name='bulk-question-pricing'),
    path('options/bulk-pricing/', views.BulkOptionPricingView.as_view(), name='bulk-option-pricing'),
    
    # Utilities
    path('pricing/calculate/', views.PricingCalculatorView.as_view(), name='pricing-calculator'),
]