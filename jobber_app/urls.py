from django.urls import path
from . import views

urlpatterns = [
    path("clients/search/", views.JobberSearchClientsView.as_view(), name="jobber-search-clients"),
    path("clients/create/", views.JobberCreateClientView.as_view(), name="jobber-create-client"),
    path("properties/create/", views.JobberCreatePropertyView.as_view(), name="jobber-create-property"),
    path("visits/", views.JobberVisitsView.as_view(), name="jobber-visits"),
    path("jobs/create/", views.JobberCreateJobView.as_view(), name="jobber-create-job"),
]
