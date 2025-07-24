# management/commands/create_admin.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import IntegrityError

User = get_user_model()

class Command(BaseCommand):
    help = 'Create an admin user'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Admin username', required=True)
        parser.add_argument('--email', type=str, help='Admin email', required=True)
        parser.add_argument('--password', type=str, help='Admin password', required=True)
        parser.add_argument('--first-name', type=str, help='First name', default='')
        parser.add_argument('--last-name', type=str, help='Last name', default='')

    def handle(self, *args, **options):
        try:
            user = User.objects.create_user(
                username=options['username'],
                email=options['email'],
                password=options['password'],
                first_name=options.get('first_name', ''),
                last_name=options.get('last_name', ''),
                is_admin=True,
                is_staff=True,
                is_superuser=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created admin user: {user.username}')
            )
        except IntegrityError:
            self.stdout.write(
                self.style.ERROR(f'User with username "{options["username"]}" already exists')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating admin user: {str(e)}')
            )

