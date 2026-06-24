"""Persist customer package picks on a submission."""

from django.shortcuts import get_object_or_404

from service_app.models import Package
from quote_app.models import CustomerPackageQuote, CustomerServiceSelection
from quote_app.pricing_utils import recalculate_submission_totals


def _coerce_package_data(package_data):
    if hasattr(package_data, 'items'):
        return dict(package_data)
    return package_data


def resolve_service_selection(submission, package_data):
    """
    Find the CustomerServiceSelection row for a package pick.

    Accepts service_selection_id (preferred), service_id, or package_id alone
    (resolved via package.service_id). This avoids failures when the frontend
    caches a stale service_selection_id after services are re-added.
    """
    data = _coerce_package_data(package_data)
    package_id = data.get('package_id')
    if not package_id:
        raise ValueError('Each selected package must include package_id.')

    package = get_object_or_404(Package, id=package_id)
    selection_id = data.get('service_selection_id')
    service_id = data.get('service_id') or package.service_id

    if selection_id:
        try:
            selection = CustomerServiceSelection.objects.get(
                id=selection_id,
                submission=submission,
            )
            if selection.service_id != package.service_id:
                raise ValueError(
                    f'Package "{package.name}" belongs to service {package.service_id}, '
                    f'but service_selection_id {selection_id} is for service {selection.service_id}.'
                )
            return selection
        except CustomerServiceSelection.DoesNotExist:
            pass

    try:
        return CustomerServiceSelection.objects.get(
            submission=submission,
            service_id=service_id,
        )
    except CustomerServiceSelection.DoesNotExist:
        available = list(
            CustomerServiceSelection.objects.filter(submission=submission).values(
                'id', 'service_id', 'service__name'
            )
        )
        raise ValueError(
            f'No service selection on submission {submission.id} for package "{package.name}". '
            f'Received service_selection_id={selection_id!r}, service_id={service_id!r}. '
            f'Current selections: {available}. '
            f'Use service_selections[].id from GET /api/quote/{submission.id}/, '
            f'or send only package_id (resolved automatically).'
        )


def sync_package_selections(submission, selected_packages, *, recalculate=True):
    """
    Save package choices for each service selection.

    selected_packages: list of dicts with package_id and optionally
    service_selection_id or service_id.
    """
    if not selected_packages:
        return submission

    for package_data in selected_packages:
        service_selection = resolve_service_selection(submission, package_data)
        data = _coerce_package_data(package_data)
        package = get_object_or_404(Package, id=data['package_id'])

        if package.service_id != service_selection.service_id:
            raise ValueError(
                f'Package {package.name} does not belong to service {service_selection.service.name}'
            )

        quote = CustomerPackageQuote.objects.filter(
            service_selection=service_selection,
            package=package,
        ).first()
        if not quote:
            raise ValueError(
                f'No package quote found for "{package.name}" on this submission. '
                f'Complete service questions first (POST .../services/{{service_id}}/responses/).'
            )

        service_selection.selected_package = package
        service_selection.final_base_price = quote.base_price + quote.sqft_price
        service_selection.final_sqft_price = quote.sqft_price
        service_selection.final_total_price = quote.effective_total_price
        service_selection.save()

        service_selection.package_quotes.update(is_selected=False)
        quote.is_selected = True
        quote.save()

    if submission.status in ('draft', 'submitted'):
        submission.status = 'packages_selected'
    submission.save(update_fields=['status', 'updated_at'])

    if recalculate:
        recalculate_submission_totals(submission)

    return submission
