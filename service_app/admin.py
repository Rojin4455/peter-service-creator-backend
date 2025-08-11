from django.contrib import admin
from .models import Package,GlobalSizePackage

admin.site.register(Package)
admin.site.register(GlobalSizePackage)

# Register your models here.
