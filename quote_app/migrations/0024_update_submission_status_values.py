# Generated migration to update status values
from django.db import migrations


def update_status_values(apps, schema_editor):
    """Update existing status values:
    - 'submitted' -> 'approved' (old submitted becomes approved)
    - 'responses_completed' -> 'submitted' (old responses_completed becomes submitted)
    """
    CustomerSubmission = apps.get_model('quote_app', 'CustomerSubmission')
    
    # First, update old 'submitted' to 'approved' (to avoid conflicts)
    CustomerSubmission.objects.filter(status='submitted').update(status='approved')
    
    # Then, update 'responses_completed' to 'submitted'
    CustomerSubmission.objects.filter(status='responses_completed').update(status='submitted')


def reverse_status_values(apps, schema_editor):
    """Reverse the migration:
    - 'submitted' -> 'responses_completed'
    - 'approved' -> 'submitted'
    """
    CustomerSubmission = apps.get_model('quote_app', 'CustomerSubmission')
    
    # Reverse: 'submitted' -> 'responses_completed'
    CustomerSubmission.objects.filter(status='submitted').update(status='responses_completed')
    
    # Reverse: 'approved' -> 'submitted'
    CustomerSubmission.objects.filter(status='approved').update(status='submitted')


class Migration(migrations.Migration):

    dependencies = [
        ('quote_app', '0023_customersubmission_quote_url'),
    ]

    operations = [
        migrations.RunPython(update_status_values, reverse_status_values),
    ]

