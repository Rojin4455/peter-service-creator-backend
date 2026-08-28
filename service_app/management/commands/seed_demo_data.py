from datetime import timedelta
from decimal import Decimal
from random import choice, randint, sample

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from quote_app.models import (
    CustomerAvailability,
    CustomerPackageQuote,
    CustomerServiceSelection,
    CustomerSubmission,
    SubmissionAddOn,
)
from service_app.models import (
    AddOnService,
    Coupon,
    Feature,
    GlobalPackageTemplate,
    GlobalSizePackage,
    Location,
    Package,
    PackageFeature,
    PropertyType,
    Question,
    QuestionOption,
    QuestionPricing,
    Service,
    ServiceBundle,
    ServicePackageSizeMapping,
    ServiceSettings,
)

User = get_user_model()


FIRST_NAMES = [
    'Alex', 'Jordan', 'Taylor', 'Morgan', 'Casey',
    'Riley', 'Avery', 'Quinn', 'Jamie', 'Cameron',
]
LAST_NAMES = [
    'Smith', 'Johnson', 'Williams', 'Brown', 'Jones',
    'Garcia', 'Miller', 'Davis', 'Wilson', 'Moore',
]
CITIES = [
    ('Downtown Hub', '100 Main St, Toronto, ON', Decimal('43.6532000000000000'), Decimal('-79.3832000000000000')),
    ('North York', '500 Sheppard Ave, North York, ON', Decimal('43.7615000000000000'), Decimal('-79.4111000000000000')),
    ('Mississauga', '200 Burnhamthorpe Rd, Mississauga, ON', Decimal('43.5890000000000000'), Decimal('-79.6441000000000000')),
    ('Scarborough', '300 Progress Ave, Scarborough, ON', Decimal('43.7764000000000000'), Decimal('-79.2318000000000000')),
    ('Etobicoke', '150 The West Mall, Etobicoke, ON', Decimal('43.6205000000000000'), Decimal('-79.5132000000000000')),
]


class Command(BaseCommand):
    help = 'Seed demo data across catalog + quote models (10 users, submissions, etc.)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--users',
            type=int,
            default=10,
            help='Number of demo admin users to create (default: 10)',
        )
        parser.add_argument(
            '--submissions',
            type=int,
            default=20,
            help='Number of customer submissions to create (default: 20)',
        )
        parser.add_argument(
            '--reset-demo',
            action='store_true',
            help='Delete previously seeded demo_* users and demo submissions before seeding',
        )

    def handle(self, *args, **options):
        user_count = options['users']
        submission_count = options['submissions']

        if options['reset_demo']:
            self._reset_demo()

        super_admin = self._ensure_super_admin()
        users = self._create_users(user_count, created_by=super_admin)
        property_types = self._create_property_types()
        locations = self._create_locations(super_admin)
        size_packages = self._create_size_packages(property_types)
        services, packages_by_service = self._create_services_and_packages(super_admin, size_packages)
        addons = self._create_addons(services)
        coupons = self._create_coupons()
        bundles = self._create_bundles(services)
        submissions = self._create_submissions(
            count=submission_count,
            locations=locations,
            size_packages=size_packages,
            services=services,
            packages_by_service=packages_by_service,
            addons=addons,
            coupons=coupons,
            bundles=bundles,
        )

        self.stdout.write(self.style.SUCCESS('Demo data seeded.'))
        self.stdout.write(f'  users:        {len(users)} (+ super admin: {super_admin.username})')
        self.stdout.write(f'  locations:    {len(locations)}')
        self.stdout.write(f'  services:     {len(services)}')
        self.stdout.write(f'  addons:       {len(addons)}')
        self.stdout.write(f'  coupons:      {len(coupons)}')
        self.stdout.write(f'  bundles:      {len(bundles)}')
        self.stdout.write(f'  submissions:  {len(submissions)}')
        self.stdout.write('')
        self.stdout.write('Demo user login: demo1 / DemoPass123!  ...  demo10 / DemoPass123!')
        self.stdout.write('Super admin:     admin / admin123')

    def _reset_demo(self):
        CustomerSubmission.all_objects.filter(customer_email__endswith='@demo.cleanonthego.com').delete()
        User.objects.filter(username__startswith='demo').delete()
        self.stdout.write(self.style.WARNING('Cleared previous demo users/submissions.'))

    def _ensure_super_admin(self):
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@example.com',
                'is_admin': True,
                'is_super_admin': True,
                'is_staff': True,
                'is_superuser': True,
                'can_access_dashboard': True,
                'can_access_reports': True,
                'can_access_service_management': True,
                'can_access_location': True,
                'can_access_house_size_management': True,
                'can_access_addon_service': True,
                'can_access_coupon': True,
                'can_access_on_the_go_calculator': True,
            },
        )
        if created:
            admin.set_password('admin123')
            admin.save()
            self.stdout.write(f'Created super admin: {admin.username}')
        return admin

    def _create_users(self, count, created_by):
        users = []
        for i in range(1, count + 1):
            username = f'demo{i}'
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@demo.cleanonthego.com',
                    'first_name': FIRST_NAMES[(i - 1) % len(FIRST_NAMES)],
                    'last_name': LAST_NAMES[(i - 1) % len(LAST_NAMES)],
                    'is_admin': True,
                    'is_staff': True,
                    'is_super_admin': False,
                    'created_by': created_by,
                    'can_access_dashboard': True,
                    'can_access_reports': i % 2 == 0,
                    'can_access_service_management': i % 3 == 0,
                    'can_access_location': True,
                    'can_access_house_size_management': i % 2 == 1,
                    'can_access_addon_service': True,
                    'can_access_coupon': i % 2 == 0,
                    'can_access_on_the_go_calculator': True,
                },
            )
            if created:
                user.set_password('DemoPass123!')
                user.save()
            users.append(user)
        self.stdout.write(f'Users ready: {len(users)}')
        return users

    def _create_property_types(self):
        types = []
        for order, name in enumerate(['Residential', 'Commercial'], start=1):
            pt, _ = PropertyType.objects.get_or_create(
                name=name,
                defaults={'description': f'{name} properties', 'order': order, 'is_active': True},
            )
            types.append(pt)
        return types

    def _create_locations(self, admin):
        locations = []
        for idx, (name, address, lat, lng) in enumerate(CITIES):
            loc, _ = Location.objects.get_or_create(
                name=name,
                defaults={
                    'address': address,
                    'latitude': lat,
                    'longitude': lng,
                    'trip_surcharge': Decimal(str(15 + idx * 5)),
                    'google_place_id': f'demo_place_{idx + 1}',
                    'is_active': True,
                    'created_by': admin,
                },
            )
            locations.append(loc)
        return locations

    def _create_size_packages(self, property_types):
        ranges = [
            (0, 1500),
            (1501, 2500),
            (2501, 4000),
            (4001, 10000),
        ]
        size_packages = []
        for pt in property_types:
            for order, (min_sqft, max_sqft) in enumerate(ranges, start=1):
                sp, created = GlobalSizePackage.objects.get_or_create(
                    property_type=pt,
                    min_sqft=min_sqft,
                    max_sqft=max_sqft,
                    defaults={'order': order},
                )
                if created:
                    for label_order, label in enumerate(['Package 1', 'Package 2', 'Package 3'], start=1):
                        GlobalPackageTemplate.objects.get_or_create(
                            global_size=sp,
                            label=label,
                            defaults={
                                'price': Decimal(str(50 + label_order * 25 + order * 10)),
                                'order': label_order,
                            },
                        )
                size_packages.append(sp)
        return size_packages

    def _create_services_and_packages(self, admin, size_packages):
        service_defs = [
            {
                'name': 'Window Cleaning',
                'description': 'Interior and exterior window cleaning',
                'order': 1,
                'packages': [
                    ('Basic', '80.00'),
                    ('Standard', '120.00'),
                    ('Premium', '180.00'),
                ],
                'features': ['Interior', 'Exterior', 'Screens', 'Tracks'],
                'question': 'Do windows have hard water stains?',
            },
            {
                'name': 'Carpet Cleaning',
                'description': 'Deep carpet shampoo and steam clean',
                'order': 2,
                'packages': [
                    ('Essential', '95.00'),
                    ('Deep Clean', '145.00'),
                    ('Pet Plus', '195.00'),
                ],
                'features': ['Steam Clean', 'Stain Guard', 'Pet Odor Treatment'],
                'question': 'Are there pet odors present?',
            },
            {
                'name': 'Pressure Washing',
                'description': 'Driveways, siding, and patio wash',
                'order': 3,
                'packages': [
                    ('Driveway', '110.00'),
                    ('House Wash', '220.00'),
                    ('Full Exterior', '320.00'),
                ],
                'features': ['Driveway', 'Siding', 'Patio', 'Walkways'],
                'question': 'Is mold or mildew present on surfaces?',
            },
        ]

        services = []
        packages_by_service = {}

        for svc_def in service_defs:
            service, created = Service.objects.get_or_create(
                name=svc_def['name'],
                defaults={
                    'description': svc_def['description'],
                    'is_active': True,
                    'is_commercial': True,
                    'is_residential': True,
                    'order': svc_def['order'],
                    'created_by': admin,
                },
            )
            ServiceSettings.objects.get_or_create(
                service=service,
                defaults={
                    'general_disclaimer': f'Demo disclaimer for {service.name}',
                    'apply_trip_charge_to_bid': True,
                },
            )

            packages = []
            for order, (pkg_name, price) in enumerate(svc_def['packages'], start=1):
                pkg, _ = Package.objects.get_or_create(
                    service=service,
                    name=pkg_name,
                    defaults={
                        'base_price': Decimal(price),
                        'order': order,
                        'is_active': True,
                    },
                )
                packages.append(pkg)
                for sp in size_packages[:4]:
                    ServicePackageSizeMapping.objects.get_or_create(
                        service_package=pkg,
                        global_size=sp,
                        defaults={
                            'pricing_type': 'upcharge',
                            'price': Decimal(str(10 + order * 5)),
                        },
                    )

            features = []
            for feat_name in svc_def['features']:
                feat, _ = Feature.objects.get_or_create(
                    service=service,
                    name=feat_name,
                    defaults={'description': f'{feat_name} included', 'is_active': True},
                )
                features.append(feat)

            for idx, pkg in enumerate(packages):
                for feat in features[: idx + 2]:
                    PackageFeature.objects.get_or_create(
                        package=pkg,
                        feature=feat,
                        defaults={'is_included': True},
                    )

            question, _ = Question.objects.get_or_create(
                service=service,
                question_text=svc_def['question'],
                defaults={
                    'question_type': 'yes_no',
                    'order': 1,
                    'is_active': True,
                },
            )
            QuestionPricing.objects.get_or_create(
                question=question,
                package=packages[0],
                defaults={
                    'yes_pricing_type': 'fixed_price',
                    'value_type': 'amount',
                    'yes_value': Decimal('25.00'),
                },
            )

            option_q, _ = Question.objects.get_or_create(
                service=service,
                question_text=f'How many areas need {service.name.lower()}?',
                defaults={
                    'question_type': 'quantity',
                    'order': 2,
                    'is_active': True,
                },
            )
            QuestionOption.objects.get_or_create(
                question=option_q,
                option_text='1-2 areas',
                defaults={'order': 1, 'is_active': True},
            )
            QuestionOption.objects.get_or_create(
                question=option_q,
                option_text='3+ areas',
                defaults={'order': 2, 'is_active': True},
            )

            packages_by_service[service.id] = packages
            services.append(service)

        return services, packages_by_service

    def _create_addons(self, services):
        defs = [
            ('Fridge Cleaning', '35.00'),
            ('Oven Cleaning', '40.00'),
            ('Baseboard Detail', '25.00'),
            ('Gutter Clean', '55.00'),
        ]
        addons = []
        for name, price in defs:
            addon, _ = AddOnService.objects.get_or_create(
                name=name,
                defaults={
                    'description': f'Demo add-on: {name}',
                    'base_price': Decimal(price),
                },
            )
            if services and not addon.services.exists():
                addon.services.set(sample(list(services), k=min(2, len(services))))
            addons.append(addon)
        return addons

    def _create_coupons(self):
        defs = [
            ('DEMO10', Decimal('10.00'), None),
            ('SAVE25', None, Decimal('25.00')),
            ('WELCOME15', Decimal('15.00'), None),
        ]
        coupons = []
        for code, pct, fixed in defs:
            coupon, _ = Coupon.objects.get_or_create(
                code=code,
                defaults={
                    'percentage_discount': pct,
                    'fixed_discount': fixed,
                    'expiration_date': timezone.now() + timedelta(days=90),
                    'used_count': randint(0, 5),
                    'is_active': True,
                    'is_global': True,
                },
            )
            coupons.append(coupon)
        return coupons

    def _create_bundles(self, services):
        if len(services) < 2:
            return []
        bundle, _ = ServiceBundle.objects.get_or_create(
            name='Window + Carpet Bundle',
            defaults={
                'description': 'Save when booking both services',
                'discount_type': 'percent',
                'discount_percentage': Decimal('10.00'),
                'is_active': True,
            },
        )
        bundle.services.set(services[:2])
        return [bundle]

    def _create_submissions(
        self,
        count,
        locations,
        size_packages,
        services,
        packages_by_service,
        addons,
        coupons,
        bundles,
    ):
        statuses = ['draft', 'submitted', 'packages_selected', 'approved', 'declined', 'expired']
        submissions = []

        for i in range(1, count + 1):
            email = f'customer{i}@demo.cleanonthego.com'
            existing = CustomerSubmission.all_objects.filter(customer_email=email).first()
            if existing:
                submissions.append(existing)
                continue

            status = statuses[(i - 1) % len(statuses)]
            location = locations[(i - 1) % len(locations)]
            size_pkg = size_packages[(i - 1) % len(size_packages)]
            property_type = 'residential' if i % 2 else 'commercial'
            selected_services = sample(list(services), k=min(2, len(services)))

            base = Decimal(str(100 + i * 15))
            adjustments = Decimal(str(10 * (i % 3)))
            surcharges = location.trip_surcharge
            addons_total = Decimal('0.00')
            discount = Decimal('0.00')
            bundle_discount = Decimal('0.00')

            coupon = coupons[(i - 1) % len(coupons)] if i % 3 == 0 else None
            bundle = bundles[0] if bundles and i % 4 == 0 and len(selected_services) >= 2 else None

            if coupon:
                discount = coupon.get_discount_amount(base + adjustments)
            if bundle:
                bundle_discount = bundle.get_discount_amount(base)

            final_total = max(
                base + adjustments + surcharges + addons_total - discount - bundle_discount,
                Decimal('0.00'),
            )

            submission = CustomerSubmission.objects.create(
                first_name=FIRST_NAMES[(i - 1) % len(FIRST_NAMES)],
                last_name=LAST_NAMES[(i - 1) % len(LAST_NAMES)],
                company_name=f'Demo Co {i}' if property_type == 'commercial' else None,
                customer_email=email,
                customer_phone=f'416555{1000 + i:04d}',
                postal_code=f'M{i % 9}A {i % 9}B{i % 9}',
                street_address=f'{100 + i} Demo Street',
                location=location,
                heard_about_us=choice(['Google', 'Referral', 'Facebook', 'Flyer']),
                property_type=property_type,
                property_name=f'Building {i}' if property_type == 'commercial' else None,
                num_floors=choice(['1 story', '2 story', '3 story']),
                is_previous_customer=i % 5 == 0,
                size_range=size_pkg,
                actual_sqft=randint(size_pkg.min_sqft or 800, size_pkg.max_sqft or 3000),
                status=status,
                is_bid_in_person=i % 7 == 0,
                total_base_price=base,
                total_adjustments=adjustments,
                total_surcharges=surcharges,
                quote_surcharge_applicable=True,
                final_total=final_total,
                applied_coupon=coupon,
                is_coupon_applied=bool(coupon),
                discounted_amount=discount,
                applied_bundle=bundle,
                is_bundle_applied=bool(bundle),
                bundle_discount_amount=bundle_discount,
                is_on_the_go=i % 6 == 0,
                expires_at=timezone.now() + timedelta(days=14),
                bid_notes_public='Demo public note' if i % 2 == 0 else '',
                bid_notes_private='Demo private note' if i % 3 == 0 else '',
            )

            for svc in selected_services:
                packages = packages_by_service.get(svc.id) or []
                selected_pkg = packages[(i - 1) % len(packages)] if packages else None
                sel = CustomerServiceSelection.objects.create(
                    submission=submission,
                    service=svc,
                    selected_package=selected_pkg if status in ('packages_selected', 'approved') else None,
                    question_adjustments=adjustments / Decimal(str(len(selected_services))),
                    surcharge_applicable=True,
                    surcharge_amount=surcharges / Decimal(str(len(selected_services))),
                    final_base_price=selected_pkg.base_price if selected_pkg else Decimal('0.00'),
                    final_sqft_price=Decimal(str(5 * (i % 4))),
                    final_total_price=(
                        (selected_pkg.base_price if selected_pkg else Decimal('0.00'))
                        + Decimal(str(5 * (i % 4)))
                    ),
                )
                for pkg in packages:
                    CustomerPackageQuote.objects.create(
                        service_selection=sel,
                        package=pkg,
                        base_price=pkg.base_price,
                        sqft_price=Decimal(str(5 * (i % 4))),
                        question_adjustments=Decimal('10.00'),
                        surcharge_amount=Decimal('5.00'),
                        total_price=pkg.base_price + Decimal('15.00'),
                        included_features=[],
                        excluded_features=[],
                        is_selected=(selected_pkg and pkg.id == selected_pkg.id),
                    )

            chosen_addons = sample(list(addons), k=min(2, len(addons)))
            addons_sum = Decimal('0.00')
            for addon in chosen_addons:
                qty = randint(1, 2)
                sa = SubmissionAddOn.objects.create(
                    submission=submission,
                    addon=addon,
                    quantity=qty,
                )
                addons_sum += sa.subtotal

            submission.total_addons_price = addons_sum
            submission.final_total = final_total + addons_sum
            submission.save(update_fields=['total_addons_price', 'final_total', 'updated_at', 'quote_url'])

            for day_offset in range(2):
                CustomerAvailability.objects.get_or_create(
                    submission=submission,
                    date=(timezone.now() + timedelta(days=3 + day_offset)).date(),
                    time=choice(['Morning', 'Afternoon', 'Evening']),
                )

            submissions.append(submission)

        return submissions
