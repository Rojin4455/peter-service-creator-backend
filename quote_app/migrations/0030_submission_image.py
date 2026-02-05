# Generated manually for SubmissionImage (quote images, GHL media)

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('quote_app', '0029_customerpackagequote_admin_override_price_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubmissionImage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('url', models.URLField(help_text='Public URL of the image (from GHL media storage)', max_length=1000)),
                ('file_id', models.CharField(help_text='GHL media file ID, used for delete API', max_length=100)),
                ('trace_id', models.CharField(blank=True, max_length=100, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='quote_app.customersubmission')),
            ],
            options={
                'db_table': 'submission_images',
                'ordering': ['-created_at'],
            },
        ),
    ]
