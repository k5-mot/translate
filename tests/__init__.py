"""translate-jaの自動test package。"""

from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DoclingDocument,
    ProvenanceItem,
    Size,
)

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


def docling_document(
    pages: int = 1, width: float = 100, height: float = 200
) -> DoclingDocument:
    """同じ大きさの空ページだけを持つDocling文書fixtureを作る。"""
    document = DoclingDocument(name="sample")
    for number in range(1, pages + 1):
        document.add_page(page_no=number, size=Size(width=width, height=height))
    return document


def docling_prov(
    page: int = 1,
    box: tuple[float, float, float, float] = (0, 0, 1, 1),
    origin: CoordOrigin = CoordOrigin.TOPLEFT,
) -> ProvenanceItem:
    """左・上・右・下の座標から、Docling要素の位置fixtureを作る。"""
    left, top, right, bottom = box
    return ProvenanceItem(
        page_no=page,
        bbox=BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=origin),
        charspan=(0, 0),
    )
