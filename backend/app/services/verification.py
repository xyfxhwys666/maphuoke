from backend.app.domain.models import EvidenceResult, LeadRecord, MapPoiCandidate
from backend.app.providers.protocols import MapEvidenceVerifier


class VerificationService:
    def __init__(self, verifier: MapEvidenceVerifier) -> None:
        self.verifier = verifier

    def verify(self, candidate: MapPoiCandidate, lead: LeadRecord) -> EvidenceResult:
        return self.verifier.verify(
            candidate,
            expected_company_name=lead.company_name,
            expected_contact=lead.mobile or lead.email,
        )
