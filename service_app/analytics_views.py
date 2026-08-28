from decimal import Decimal

from django.db.models import Count, Sum, Avg
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from quote_app.models import CustomerSubmission
from service_app.api_key_auth import DashboardAPIKeyAuthentication, HasDashboardAPIKey
from service_app.models import (
    Service,
    Package,
    Location,
    AddOnService,
    Coupon,
    ServiceBundle,
    GlobalSizePackage,
)


def _dec(value):
    if value is None:
        return '0.00'
    return str(Decimal(value).quantize(Decimal('0.01')))


def _dt(value):
    return value.isoformat() if value else None


class PricingCalculatorAnalyticsView(APIView):
    """
    GET /api/pricing-calculator/analytics/

    Pull dashboard-ready pricing-calculator data for an external app.
    Auth: X-API-Key or Authorization: Api-Key <key>

    Optional query params:
      since=ISO datetime   — only submissions created on/after
      status=draft,approved — comma-separated status filter
      include_deleted=true  — include soft-deleted submissions
    """

    authentication_classes = [DashboardAPIKeyAuthentication]
    permission_classes = [HasDashboardAPIKey]

    def get(self, request):
        since = request.query_params.get('since')
        status_filter = request.query_params.get('status')
        include_deleted = request.query_params.get('include_deleted', '').lower() in (
            '1', 'true', 'yes',
        )

        if include_deleted:
            submissions_qs = CustomerSubmission.all_objects.all()
        else:
            submissions_qs = CustomerSubmission.objects.all()

        if since:
            submissions_qs = submissions_qs.filter(created_at__gte=since)
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(',') if s.strip()]
            if statuses:
                submissions_qs = submissions_qs.filter(status__in=statuses)

        submissions_qs = (
            submissions_qs
            .select_related(
                'location',
                'size_range',
                'size_range__property_type',
                'applied_coupon',
                'applied_bundle',
            )
            .prefetch_related(
                'availabilities',
                'submission_addons__addon',
                'customerserviceselection_set__service',
                'customerserviceselection_set__selected_package',
                'customerserviceselection_set__package_quotes__package',
            )
            .order_by('-created_at')
        )

        summary = self._build_summary(submissions_qs)
        submissions = [self._serialize_submission(s) for s in submissions_qs]

        payload = {
            'generated_at': timezone.now().isoformat(),
            'source': 'pricing-calculator',
            'summary': summary,
            'submissions': submissions,
            'catalog': {
                'services': self._serialize_services(),
                'packages': self._serialize_packages(),
                'locations': self._serialize_locations(),
                'addons': self._serialize_addons(),
                'coupons': self._serialize_coupons(),
                'bundles': self._serialize_bundles(),
                'size_packages': self._serialize_size_packages(),
            },
        }
        return Response(payload)

    def _build_summary(self, submissions_qs):
        aggregates = submissions_qs.aggregate(
            total=Count('id'),
            revenue_sum=Sum('final_total'),
            revenue_avg=Avg('final_total'),
            base_sum=Sum('total_base_price'),
            adjustments_sum=Sum('total_adjustments'),
            surcharges_sum=Sum('total_surcharges'),
            addons_sum=Sum('total_addons_price'),
            discounts_sum=Sum('discounted_amount'),
            bundle_discounts_sum=Sum('bundle_discount_amount'),
        )

        by_status = {
            row['status']: {
                'count': row['count'],
                'revenue': _dec(row['revenue']),
            }
            for row in submissions_qs.values('status').annotate(
                count=Count('id'),
                revenue=Sum('final_total'),
            )
        }

        by_property = {
            row['property_type'] or 'unknown': row['count']
            for row in submissions_qs.values('property_type').annotate(count=Count('id'))
        }

        approved_revenue = submissions_qs.filter(
            status__in=['approved', 'packages_selected', 'submitted']
        ).aggregate(total=Sum('final_total'))['total']

        return {
            'submissions_total': aggregates['total'] or 0,
            'submissions_by_status': by_status,
            'submissions_by_property_type': by_property,
            'revenue_total': _dec(aggregates['revenue_sum']),
            'revenue_pipeline': _dec(approved_revenue),
            'revenue_average': _dec(aggregates['revenue_avg']),
            'base_price_total': _dec(aggregates['base_sum']),
            'adjustments_total': _dec(aggregates['adjustments_sum']),
            'surcharges_total': _dec(aggregates['surcharges_sum']),
            'addons_revenue_total': _dec(aggregates['addons_sum']),
            'coupon_discounts_total': _dec(aggregates['discounts_sum']),
            'bundle_discounts_total': _dec(aggregates['bundle_discounts_sum']),
            'services_active': Service.objects.filter(is_active=True).count(),
            'locations_active': Location.objects.filter(is_active=True).count(),
            'coupons_active': Coupon.objects.filter(is_active=True).count(),
            'addons_count': AddOnService.objects.count(),
            'bundles_active': ServiceBundle.objects.filter(is_active=True).count(),
            'bid_in_person_count': submissions_qs.filter(is_bid_in_person=True).count(),
            'on_the_go_count': submissions_qs.filter(is_on_the_go=True).count(),
            'coupon_applied_count': submissions_qs.filter(is_coupon_applied=True).count(),
            'bundle_applied_count': submissions_qs.filter(is_bundle_applied=True).count(),
        }

    def _serialize_submission(self, s: CustomerSubmission):
        service_selections = []
        for sel in s.customerserviceselection_set.all():
            package_quotes = [
                {
                    'id': str(pq.id),
                    'package_id': str(pq.package_id),
                    'package_name': pq.package.name if pq.package_id else None,
                    'base_price': _dec(pq.base_price),
                    'sqft_price': _dec(pq.sqft_price),
                    'question_adjustments': _dec(pq.question_adjustments),
                    'measurement_total': _dec(pq.measurement_total),
                    'surcharge_amount': _dec(pq.surcharge_amount),
                    'total_price': _dec(pq.total_price),
                    'admin_override_price': _dec(pq.admin_override_price) if pq.admin_override_price is not None else None,
                    'effective_total_price': _dec(pq.effective_total_price),
                    'is_selected': pq.is_selected,
                }
                for pq in sel.package_quotes.all()
            ]
            service_selections.append({
                'id': str(sel.id),
                'service_id': str(sel.service_id),
                'service_name': sel.service.name if sel.service_id else None,
                'selected_package_id': str(sel.selected_package_id) if sel.selected_package_id else None,
                'selected_package_name': sel.selected_package.name if sel.selected_package_id else None,
                'question_adjustments': _dec(sel.question_adjustments),
                'surcharge_applicable': sel.surcharge_applicable,
                'surcharge_amount': _dec(sel.surcharge_amount),
                'final_base_price': _dec(sel.final_base_price),
                'final_sqft_price': _dec(sel.final_sqft_price),
                'final_total_price': _dec(sel.final_total_price),
                'package_quotes': package_quotes,
                'created_at': _dt(sel.created_at),
            })

        addons = [
            {
                'addon_id': str(sa.addon_id),
                'addon_name': sa.addon.name if sa.addon_id else None,
                'quantity': sa.quantity,
                'subtotal': _dec(sa.subtotal),
                'unit_price': _dec(sa.addon.base_price) if sa.addon_id else None,
            }
            for sa in s.submission_addons.all()
        ]

        availabilities = [
            {
                'id': str(a.id),
                'date': a.date.isoformat() if a.date else None,
                'time': a.time,
            }
            for a in s.availabilities.all()
        ]

        return {
            'id': str(s.id),
            'status': s.status,
            'is_deleted': s.is_deleted,
            'customer': {
                'first_name': s.first_name,
                'last_name': s.last_name,
                'company_name': s.company_name,
                'email': s.customer_email,
                'phone': s.customer_phone,
                'postal_code': s.postal_code,
                'street_address': s.street_address,
                'ghl_contact_id': s.ghl_contact_id,
                'allow_sms': s.allow_sms,
                'allow_email': s.allow_email,
                'is_previous_customer': s.is_previous_customer,
                'heard_about_us': s.heard_about_us,
            },
            'property': {
                'type': s.property_type,
                'name': s.property_name,
                'num_floors': s.num_floors,
                'actual_sqft': s.actual_sqft,
                'size_range_id': str(s.size_range_id) if s.size_range_id else None,
                'size_range': (
                    f"{s.size_range.min_sqft}-{s.size_range.max_sqft}"
                    if s.size_range_id else None
                ),
            },
            'location': {
                'id': str(s.location_id) if s.location_id else None,
                'name': s.location.name if s.location_id else None,
                'address': s.location.address if s.location_id else None,
                'trip_surcharge': _dec(s.location.trip_surcharge) if s.location_id else None,
            },
            'pricing': {
                'total_base_price': _dec(s.total_base_price),
                'total_adjustments': _dec(s.total_adjustments),
                'total_surcharges': _dec(s.total_surcharges),
                'total_addons_price': _dec(s.total_addons_price),
                'discounted_amount': _dec(s.discounted_amount),
                'bundle_discount_amount': _dec(s.bundle_discount_amount),
                'final_total': _dec(s.final_total),
                'original_final_total': _dec(s.original_final_total) if s.original_final_total is not None else None,
                'quote_surcharge_applicable': s.quote_surcharge_applicable,
            },
            'coupon': {
                'applied': s.is_coupon_applied,
                'id': str(s.applied_coupon_id) if s.applied_coupon_id else None,
                'code': s.applied_coupon.code if s.applied_coupon_id else None,
            },
            'bundle': {
                'applied': s.is_bundle_applied,
                'id': str(s.applied_bundle_id) if s.applied_bundle_id else None,
                'name': s.applied_bundle.name if s.applied_bundle_id else None,
            },
            'flags': {
                'is_bid_in_person': s.is_bid_in_person,
                'is_on_the_go': s.is_on_the_go,
            },
            'service_selections': service_selections,
            'addons': addons,
            'availabilities': availabilities,
            'quote_url': s.quote_url,
            'declined_at': _dt(s.declined_at),
            'expires_at': _dt(s.expires_at),
            'created_at': _dt(s.created_at),
            'updated_at': _dt(s.updated_at),
            'last_edited_at': _dt(s.last_edited_at),
            'edited_by': s.edited_by,
            'edit_count': s.edit_count,
        }

    def _serialize_services(self):
        return [
            {
                'id': str(svc.id),
                'name': svc.name,
                'description': svc.description,
                'is_active': svc.is_active,
                'is_commercial': svc.is_commercial,
                'is_residential': svc.is_residential,
                'order': svc.order,
                'icon_url': svc.icon_url,
                'created_at': _dt(svc.created_at),
                'updated_at': _dt(svc.updated_at),
            }
            for svc in Service.objects.all().order_by('order', 'name')
        ]

    def _serialize_packages(self):
        return [
            {
                'id': str(pkg.id),
                'service_id': str(pkg.service_id),
                'service_name': pkg.service.name,
                'name': pkg.name,
                'base_price': _dec(pkg.base_price),
                'order': pkg.order,
                'is_active': pkg.is_active,
            }
            for pkg in Package.objects.select_related('service').order_by('service__order', 'order')
        ]

    def _serialize_locations(self):
        return [
            {
                'id': str(loc.id),
                'name': loc.name,
                'address': loc.address,
                'latitude': str(loc.latitude),
                'longitude': str(loc.longitude),
                'trip_surcharge': _dec(loc.trip_surcharge),
                'is_active': loc.is_active,
            }
            for loc in Location.objects.all().order_by('name')
        ]

    def _serialize_addons(self):
        addons = AddOnService.objects.prefetch_related('services').all().order_by('name')
        return [
            {
                'id': str(a.id),
                'name': a.name,
                'description': a.description,
                'base_price': _dec(a.base_price),
                'is_global': a.is_global,
                'service_ids': [str(sid) for sid in a.services.values_list('id', flat=True)],
            }
            for a in addons
        ]

    def _serialize_coupons(self):
        return [
            {
                'id': str(c.id),
                'code': c.code,
                'percentage_discount': _dec(c.percentage_discount) if c.percentage_discount is not None else None,
                'fixed_discount': _dec(c.fixed_discount) if c.fixed_discount is not None else None,
                'expiration_date': _dt(c.expiration_date),
                'used_count': c.used_count,
                'is_active': c.is_active,
                'is_global': c.is_global,
            }
            for c in Coupon.objects.all().order_by('-created_at')
        ]

    def _serialize_bundles(self):
        bundles = ServiceBundle.objects.prefetch_related('services').all().order_by('name')
        return [
            {
                'id': str(b.id),
                'name': b.name,
                'description': b.description,
                'discount_type': b.discount_type,
                'discount_percentage': _dec(b.discount_percentage) if b.discount_percentage is not None else None,
                'discount_fixed': _dec(b.discount_fixed) if b.discount_fixed is not None else None,
                'is_active': b.is_active,
                'service_ids': [str(sid) for sid in b.services.values_list('id', flat=True)],
            }
            for b in bundles
        ]

    def _serialize_size_packages(self):
        return [
            {
                'id': str(sp.id),
                'property_type': sp.property_type.name if sp.property_type_id else None,
                'min_sqft': sp.min_sqft,
                'max_sqft': sp.max_sqft,
                'order': sp.order,
            }
            for sp in GlobalSizePackage.objects.select_related('property_type').order_by('order')
        ]
