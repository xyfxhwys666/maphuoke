from backend.app.domain.models import DeliveryDecision, DeliveryPolicy, LeadRecord

_COMPANY_VERIFIED = {
    'verified_map',
    'verified_public_web',
    'verified_official_page',
    'verified_cross_source',
}
_CONTACT_VERIFIED = {
    'verified_public_web',
    'verified_official_page',
    'verified_cross_source',
}


def evaluate_delivery_gate(policy: DeliveryPolicy, lead: LeadRecord) -> DeliveryDecision:
    reasons: list[str] = []
    if lead.company_name_verification_status not in _COMPANY_VERIFIED:
        reasons.append('company_name_unverified')

    contact_is_verified = lead.contact_verification_status in _CONTACT_VERIFIED
    if policy.allow_map_only_verification and lead.contact_verification_status == 'verified_map':
        contact_is_verified = True
    if not contact_is_verified:
        reasons.append('contact_unverified')

    present_contacts = [field for field in policy.required_contacts if getattr(lead, field, None)]
    if policy.require_all_contacts:
        missing = [field for field in policy.required_contacts if not getattr(lead, field, None)]
        if missing:
            reasons.append('missing_required_contacts')
    elif not present_contacts:
        reasons.append('missing_mobile_or_email')

    if not lead.source_url and not lead.source_urls:
        reasons.append('missing_source_url')

    return DeliveryDecision(status='ready' if not reasons else 'display_only', reasons=reasons)
