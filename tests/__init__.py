"""translate-jaの自動test package。"""

from translate.models.review import ReviewAssessment, ReviewResponse


def successful_review(*target_ids: str) -> ReviewResponse:
    """指定した比較対象をすべて正常とするLLM応答fixtureを作る。"""
    return ReviewResponse(
        assessments=[
            ReviewAssessment(
                target_id=key,
                reason="適切な訳文",
                verdict="correct",
                edits=[],
                category=None,
                severity=None,
            )
            for key in target_ids
        ]
    )
