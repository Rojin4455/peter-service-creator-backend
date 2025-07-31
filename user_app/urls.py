# urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Step 1: Submit Contact Info
    path('contacts/', views.ContactCreateView.as_view(), name='contact-create'),
    path('contacts/<uuid:id>/', views.ContactCreateUpdateView.as_view(), name='contact-update'),

    
    # Step 2: List All Services
    path('services/', views.ServiceListView.as_view(), name='service-list'),
    
    # Step 3: Get Service Details with Packages
    path('services/<uuid:id>/', views.ServiceDetailView.as_view(), name='service-detail'),
    
    # Step 4: Get Package Details (Optional)
    path('packages/<uuid:id>/', views.PackageDetailView.as_view(), name='package-detail'),
    
    # Step 5: Get Questions for a Service
    path('services/<uuid:service_id>/questions/', views.ServiceQuestionsView.as_view(), name='service-questions'),
    
    # Step 6: Create Quote (Checkout Summary)
    path('quotes/', views.QuoteCreateView.as_view(), name='quote-create'),
    
    # Additional endpoints
    path('quotes/<uuid:id>/', views.QuoteDetailView.as_view(), name='quote-detail'),
    path('quotes/<uuid:quote_id>/status/', views.update_quote_status, name='quote-status-update'),
    path('calculate-price/', views.calculate_price, name='calculate-price'),
    path('contacts/<uuid:contact_id>/quotes/', views.ContactQuotesView.as_view(), name='contact-quotes'),
]