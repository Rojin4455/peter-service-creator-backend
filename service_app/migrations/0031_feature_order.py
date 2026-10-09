from django.db import migrations, models


def backfill_feature_order(apps, schema_editor):
    Feature = apps.get_model('service_app', 'Feature')
    by_service = {}
    for f in Feature.objects.order_by('created_at'):
        by_service.setdefault(f.service_id, []).append(f)
    for features in by_service.values():
        for index, f in enumerate(features):
            f.order = index
        Feature.objects.bulk_update(features, ['order'])


class Migration(migrations.Migration):

    dependencies = [
        ('service_app', '0030_dashboardapikey'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='feature',
            options={'ordering': ['order', 'created_at']},
        ),
        migrations.AddField(
            model_name='feature',
            name='order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_feature_order, migrations.RunPython.noop),
    ]
