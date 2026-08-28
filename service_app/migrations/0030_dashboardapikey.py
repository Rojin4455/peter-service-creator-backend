import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0029_servicebundle'),
    ]

    operations = [
        migrations.CreateModel(
            name='DashboardApiKey',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(help_text='Label for this key (e.g. dashboard-prod)', max_length=100)),
                ('key_prefix', models.CharField(db_index=True, editable=False, max_length=12)),
                ('key_hash', models.CharField(editable=False, max_length=64, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'dashboard_api_keys',
                'ordering': ['-created_at'],
            },
        ),
    ]
