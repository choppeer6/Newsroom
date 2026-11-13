from __future__ import annotations

import asyncio
import logging

from pydantic import Field, field_validator

from app.agents.base import BaseAgent
from app.agents.contracts import FactCheckerInput, FactCheckerOutput
from app.agents.runtime import complete_validated, dump_json, failure_for
from app.agents.sources import dedupe_strings, merge_sources
from app.core.llm import LLMClient, OpenAICompatibleClient
from app.prompts.loader import load_prompt
from app.schemas.base import StrictModel
from app.schemas.domain import (
    FactCheckFinding,
    ResearchSource,
    SourceEvidence,
    VerificationClaim,
)
from app.schemas.enums import (
    AgentName,
    ChiefDecision,
    ClaimVerificationResult,
    FactCheckOverallResult,
)
from app.tools.search import (
    SearchError,
    SearchHit,
    SearchNotConfiguredError,
    SearchTool,
    TavilySearchTool,
)

logger = logging.getLogger(__name__)

MAX_CLAIMS = 8
EVIDENCE_PER_CLAIM = 3
MAX_EVIDENCE = 24
SEARCH_CONCURRENCY = 3


class ClaimListPayload(StrictModel):
    claims: list[str]

    @field_validator("claims", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
        return value

    @field_validator("claims")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        cleaned = dedupe_strings([claim[:300] for claim in value])
        if not cleaned:
            raise ValueError("claims must not be empty")
        return cleaned[:MAX_CLAIMS]


class ClaimVerdictPayload(StrictModel):
    claim: str = Field(min_length=1)
    result: ClaimVerificationResult
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("claim", "reason", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def _none_to_list(cls, value: object) -> object:
        return value or []


class VerdictListPayload(StrictModel):
    claims: list[ClaimVerdictPayload] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)

    @field_validator("issues", mode="before")
    @classmethod
    def _trim_issues(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
        return value


class FactCheckerAgent(BaseAgent[FactCheckerInput, FactCheckerOutput]):
    name = AgentName.FACT_CHECKER

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        search: SearchTool | None = None,
    ) -> None:
        self._llm = llm or OpenAICompatibleClient()
        self._search = search or TavilySearchTool()

    async def run(self, payload: FactCheckerInput) -> FactCheckerOutput:
        logger.info(
            "fact_checker start task_id=%s article_id=%s version=%d",
            payload.task_id,
            payload.article_id,
            payload.article_version,
        )
        try:
            claims = await self._extract_claims(payload)
            hits, search_issues = await self._search_evidence(claims)
            evidence = merge_sources(
                payload.sources,
                hits,
                prefix="EVID",
                limit=MAX_EVIDENCE,
            )
            finding = await self._verify_claims(
                payload, claims, evidence, search_issues
            )
            output = FactCheckerOutput(
                verification_report=finding,
                article_id=payload.article_id,
                article_version=payload.article_version,
            )
            logger.info(
                "fact_checker completed task_id=%s overall=%s claims=%d",
                payload.task_id,
                finding.overall_result,
                len(finding.claims),
            )
            return output
        except Exception as exc:
            output = failure_for(FactCheckerOutput, exc)
            logger.warning(
                "fact_checker failed task_id=%s code=%s",
                payload.task_id,
                output.error.code if output.error else "unknown",
            )
            return output

    async def _extract_claims(self, payload: FactCheckerInput) -> list[str]:
        spec = load_prompt("fact_checker", "extract_claims")
        result = await complete_validated(
            self._llm,
            spec,
            context={
                "title": payload.article.title,
                "content": payload.article.content,
            },
            validate=lambda data: ClaimListPayload.model_validate(data),
        )
        return result.claims

    async def _search_evidence(
        self, claims: list[str]
    ) -> tuple[list[SearchHit], list[str]]:
        semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def search_one(claim: str):
            async with semaphore:
                return await self._search.search(
                    claim, max_results=EVIDENCE_PER_CLAIM
                )

        results = await asyncio.gather(
            *(search_one(claim) for claim in claims),
            return_exceptions=True,
        )

        hits: list[SearchHit] = []
        issues: list[str] = []
        failures = 0
        for claim, result in zip(claims, results):
            if isinstance(result, SearchNotConfiguredError):
                raise result
            if isinstance(result, SearchError):
                failures += 1
                issues.append(f"断言「{claim}」检索失败：{result.message}")
                continue
            if isinstance(result, BaseException):
                raise result
            hits.extend(result)

        if failures == len(claims):
            raise SearchError("所有断言的检索均失败", retryable=True)
        return hits, issues

    async def _verify_claims(
        self,
        payload: FactCheckerInput,
        claims: list[str],
        evidence: list[ResearchSource],
        search_issues: list[str],
    ) -> FactCheckFinding:
        spec = load_prompt("fact_checker", "verify_claims")
        evidence_brief = [
            {
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "summary": source.summary,
            }
            for source in evidence
        ]
        result = await complete_validated(
            self._llm,
            spec,
            context={
                "claims_json": dump_json(claims),
                "evidence_json": dump_json(evidence_brief),
                "title": payload.article.title,
                "content": payload.article.content,
            },
            validate=lambda data: VerdictListPayload.model_validate(data),
        )

        issues = list(search_issues)
        evidence_by_id = {source.source_id: source for source in evidence}
        verdicts_by_claim: dict[str, ClaimVerdictPayload] = {}
        claim_set = set(claims)
        for verdict in result.claims:
            claim = verdict.claim.strip()
            if claim in claim_set:
                verdicts_by_claim.setdefault(claim, verdict)
            elif claim:
                issues.append(f"模型返回了未抽取的断言，已忽略：{claim[:80]}")

        verified_claims: list[VerificationClaim] = []
        for claim in claims:
            verdict = verdicts_by_claim.get(claim)
            if verdict is None:
                issues.append(
                    f"模型未返回断言「{claim}」的核查结果，已标记为 UNVERIFIED"
                )
                verified_claims.append(
                    VerificationClaim(
                        claim=claim,
                        result=ClaimVerificationResult.UNVERIFIED,
                        reason="模型未返回该断言的核查结果",
                    )
                )
                continue
            verified_claims.append(
                self._bind_verdict(verdict, evidence_by_id, issues)
            )

        issues.extend(result.issues)
        return FactCheckFinding(
            overall_result=self._overall_result(verified_claims),
            claims=verified_claims,
            issues=dedupe_strings(issues),
            recommendation=self._recommendation(verified_claims),
        )

    def _bind_verdict(
        self,
        verdict: ClaimVerdictPayload,
        evidence_by_id: dict[str, ResearchSource],
        issues: list[str],
    ) -> VerificationClaim:
        bound: list[SourceEvidence] = []
        unknown: list[str] = []
        for source_id in dedupe_strings(verdict.evidence_ids):
            source = evidence_by_id.get(source_id)
            if source is None:
                unknown.append(source_id)
                continue
            excerpt = (source.summary or source.title).strip()[:400]
            bound.append(
                SourceEvidence(
                    source_id=source.source_id,
                    url=source.url,
                    supporting_excerpt=excerpt or source.title,
                )
            )

        if unknown:
            issues.append(
                f"断言「{verdict.claim}」引用了未知来源编号，已忽略："
                f"{', '.join(unknown)}"
            )

        result = verdict.result
        reason = verdict.reason
        if result != ClaimVerificationResult.UNVERIFIED and not bound:
            issues.append(
                f"断言「{verdict.claim}」缺少有效证据，已按 UNVERIFIED 处理"
            )
            result = ClaimVerificationResult.UNVERIFIED
            reason = "未提供可绑定的来源证据"

        return VerificationClaim(
            claim=verdict.claim,
            result=result,
            evidence=bound,
            reason=reason,
        )

    @staticmethod
    def _overall_result(
        claims: list[VerificationClaim],
    ) -> FactCheckOverallResult:
        results = {claim.result for claim in claims}
        if ClaimVerificationResult.CONTRADICTED in results:
            return FactCheckOverallResult.FAILED
        if results == {ClaimVerificationResult.VERIFIED}:
            return FactCheckOverallResult.PASSED
        return FactCheckOverallResult.PARTIAL

    @staticmethod
    def _recommendation(claims: list[VerificationClaim]) -> ChiefDecision:
        if all(
            claim.result == ClaimVerificationResult.VERIFIED for claim in claims
        ):
            return ChiefDecision.APPROVE
        return ChiefDecision.REQUEST_RESEARCH
