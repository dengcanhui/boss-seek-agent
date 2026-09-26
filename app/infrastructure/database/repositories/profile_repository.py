from sqlalchemy.orm import Session, sessionmaker

from app.domain.candidate.models import CandidateProfile
from app.infrastructure.database.tables import CandidateProfileRow


class CandidateProfileRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory: sessionmaker[Session] = session_factory

    def load(self) -> CandidateProfile:
        with self.session_factory() as session:
            row = session.get(CandidateProfileRow, 1)
            if row is None:
                profile = CandidateProfile()
                row = CandidateProfileRow(id=1, profile_json=profile.model_dump_json())
                session.add(row); session.commit()
                return profile
            return CandidateProfile.model_validate_json(row.profile_json)

    def save(self, profile: CandidateProfile) -> CandidateProfile:
        with self.session_factory() as session:
            row = session.get(CandidateProfileRow, 1)
            if row is None:
                row = CandidateProfileRow(id=1, profile_json=profile.model_dump_json())
                session.add(row)
            else:
                row.profile_json = profile.model_dump_json()
            session.commit()
            return profile
