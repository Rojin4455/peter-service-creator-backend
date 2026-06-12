from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0027_service_icon_ghl_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='addonservice',
            name='services',
            field=models.ManyToManyField(
                blank=True,
                help_text='If empty, this add-on is available for all services.',
                related_name='addon_services',
                to='service_app.service',
            ),
        ),
    ]
