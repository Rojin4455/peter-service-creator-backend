"""Shared submission total calculation including service bundle discounts."""

from decimal import Decimal

from django.db.models import Count

from service_app.models import ServiceBundle


def get_submission_service_ids(submission):
    """Service IDs currently selected on the submission."""
    return set(
        submission.customerserviceselection_set.values_list('service_id', flat=True)
    )


def bundle_matches_submission(bundle, submission_service_ids):
    """Exact-set match: submission services must equal bundle services."""
    if not bundle or not bundle.is_active:
        return False
    bundle_service_ids = bundle.get_service_id_set()
    if len(bundle_service_ids) < 2:
        return False
    return bundle_service_ids == set(submission_service_ids)


def find_matching_bundles(submission):
    """Active bundles whose service set exactly matches the submission."""
    submission_service_ids = get_submission_service_ids(submission)
    if len(submission_service_ids) < 2:
        return ServiceBundle.objects.none()

    candidates = (
        ServiceBundle.objects.filter(is_active=True)
        .prefetch_related('services')
        .annotate(service_count=Count('services'))
        .filter(service_count=len(submission_service_ids))
    )

    return [
        bundle
        for bundle in candidates
        if bundle_matches_submission(bundle, submission_service_ids)
    ]


def submission_pricing_ready(submission):
    """True when every selected service has a priced, selected package."""
    selections = submission.customerserviceselection_set.all()
    if not selections.exists():
        return False
    for selection in selections:
        if not selection.selected_package_id:
            return False
        if not selection.package_quotes.filter(is_selected=True).exists():
            return False
    return True


def compute_services_total(submission):
    """Sum effective package prices for all services with a selected package."""
    total = Decimal('0.00')
    selections = submission.customerserviceselection_set.filter(
        selected_package__isnull=False
    ).prefetch_related('package_quotes')

    for selection in selections:
        selected_quote = selection.package_quotes.filter(is_selected=True).first()
        if selected_quote:
            total += selected_quote.effective_total_price
    return total


def compute_addons_total(submission):
    total = Decimal('0.00')
    for sub_addon in submission.submission_addons.select_related('addon'):
        total += sub_addon.addon.base_price * sub_addon.quantity
    return total


def clear_bundle_if_invalid(submission, *, save=False):
    """Remove applied bundle when it no longer matches submission services."""
    if not submission.is_bundle_applied and not submission.applied_bundle_id:
        return False

    service_ids = get_submission_service_ids(submission)
    bundle = submission.applied_bundle
    if bundle and bundle_matches_submission(bundle, service_ids):
        return False

    submission.applied_bundle = None
    submission.is_bundle_applied = False
    submission.bundle_discount_amount = Decimal('0.00')
    if save:
        submission.save(
            update_fields=[
                'applied_bundle',
                'is_bundle_applied',
                'bundle_discount_amount',
                'updated_at',
            ]
        )
    return True


def build_bundle_preview(submission, bundle, services_total=None):
    """Pricing preview for one matching bundle."""
    if services_total is None:
        services_total = compute_services_total(submission)

    discount_amount = bundle.get_discount_amount(services_total)
    bundled_services_total = services_total - discount_amount
    addons_total = compute_addons_total(submission)
    pre_coupon_total = bundled_services_total + addons_total

    coupon_discount = Decimal('0.00')
    final_total = pre_coupon_total
    if submission.applied_coupon and submission.applied_coupon.is_valid():
        final_total = submission.applied_coupon.apply_discount(pre_coupon_total)
        coupon_discount = pre_coupon_total - final_total

    return {
        'bundle_id': str(bundle.id),
        'name': bundle.name,
        'description': bundle.description,
        'discount_type': bundle.discount_type,
        'discount_percentage': (
            str(bundle.discount_percentage) if bundle.discount_percentage is not None else None
        ),
        'discount_fixed': (
            str(bundle.discount_fixed) if bundle.discount_fixed is not None else None
        ),
        'services': [
            {'id': str(s.id), 'name': s.name}
            for s in bundle.services.all().order_by('name')
        ],
        'original_services_total': str(services_total),
        'bundle_discount_amount': str(discount_amount),
        'bundled_services_total': str(bundled_services_total),
        'addons_total': str(addons_total),
        'pre_coupon_total': str(pre_coupon_total),
        'coupon_discount_amount': str(coupon_discount),
        'final_total': str(final_total),
        'is_applied': (
            submission.is_bundle_applied
            and submission.applied_bundle_id == bundle.id
        ),
    }


def recalculate_submission_totals(submission, *, debug=False):
    """
    Recompute submission pricing:
    services → bundle discount (services only) → add-ons → coupon.
    """
    service_selections = submission.customerserviceselection_set.filter(
        selected_package__isnull=False
    ).prefetch_related('package_quotes')

    total_base_price = Decimal('0.00')
    total_sqft_price = Decimal('0.00')
    total_adjustments = Decimal('0.00')
    total_services_price = Decimal('0.00')

    for selection in service_selections:
        selected_quote = selection.package_quotes.filter(is_selected=True).first()
        if selected_quote:
            total_base_price += selected_quote.base_price
            total_sqft_price += selected_quote.sqft_price
            total_adjustments += selected_quote.question_adjustments
            total_services_price += selected_quote.effective_total_price
            if debug:
                print(
                    f"[DEBUG] Service {selection.service.name}: "
                    f"package_total={selected_quote.effective_total_price}"
                )

    total_addons_price = compute_addons_total(submission)

    bundle_discount = Decimal('0.00')
    discounted_services_total = total_services_price

    if submission.is_bundle_applied and submission.applied_bundle:
        bundle = submission.applied_bundle
        service_ids = get_submission_service_ids(submission)
        if bundle_matches_submission(bundle, service_ids):
            bundle_discount = bundle.get_discount_amount(total_services_price)
            discounted_services_total = total_services_price - bundle_discount
        else:
            submission.applied_bundle = None
            submission.is_bundle_applied = False
            bundle_discount = Decimal('0.00')
            if debug:
                print("[DEBUG] Applied bundle no longer matches; cleared")

    submission.bundle_discount_amount = bundle_discount
    pre_coupon_total = discounted_services_total + total_addons_price

    if submission.applied_coupon and submission.applied_coupon.is_valid():
        final_total = submission.applied_coupon.apply_discount(pre_coupon_total)
        submission.is_coupon_applied = True
        submission.discounted_amount = pre_coupon_total - final_total
        if debug:
            print(
                f"[DEBUG] Coupon {submission.applied_coupon.code} applied: "
                f"pre_coupon={pre_coupon_total}, final={final_total}"
            )
    else:
        final_total = pre_coupon_total
        submission.is_coupon_applied = False
        submission.discounted_amount = Decimal('0.00')
        if debug:
            print("[DEBUG] No valid coupon applied")

    submission.total_base_price = total_base_price + total_sqft_price
    submission.total_adjustments = total_adjustments
    submission.total_addons_price = total_addons_price
    submission.final_total = final_total
    submission.save()

    if debug:
        print(
            f"[DEBUG] Totals: services={total_services_price}, "
            f"bundle_discount={bundle_discount}, addons={total_addons_price}, "
            f"final={final_total}"
        )

    return submission
