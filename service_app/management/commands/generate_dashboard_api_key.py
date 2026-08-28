from django.core.management.base import BaseCommand

from service_app.models import DashboardApiKey


class Command(BaseCommand):
    help = 'Generate a dashboard API key for GET /api/pricing-calculator/analytics/'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            default='dashboard',
            help='Label for this API key (default: dashboard)',
        )

    def handle(self, *args, **options):
        instance, raw_key = DashboardApiKey.generate(name=options['name'])
        self.stdout.write(self.style.SUCCESS('Dashboard API key created.'))
        self.stdout.write(f'  id:     {instance.id}')
        self.stdout.write(f'  name:   {instance.name}')
        self.stdout.write(f'  prefix: {instance.key_prefix}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Store this key now — it will not be shown again:'))
        self.stdout.write(raw_key)
        self.stdout.write('')
        self.stdout.write('Use it as:')
        self.stdout.write('  X-API-Key: <key>')
        self.stdout.write('  or  Authorization: Api-Key <key>')
