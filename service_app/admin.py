from django.contrib import admin
from .models import Package,GlobalSizePackage,SubQuestionPricing,QuestionPricing,OptionPricing

admin.site.register(Package)
admin.site.register(GlobalSizePackage)
admin.site.register(SubQuestionPricing)
admin.site.register(QuestionPricing)
admin.site.register(OptionPricing)

# Register your models here.
