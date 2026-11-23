from fastapi import APIRouter

from app.api.v1 import batches, papers, revisions, rule_sets, stats

router = APIRouter(prefix="/api/v1")
router.include_router(rule_sets.router)
router.include_router(batches.router)
router.include_router(papers.router)
router.include_router(revisions.router)
router.include_router(stats.router)
