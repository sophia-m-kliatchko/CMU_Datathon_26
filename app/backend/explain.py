"""
Optional AI explainer: turns one recommendation's cited evidence into a short plain-language explanation,
using a Databricks Foundation Model endpoint (config.LLM_ENDPOINT). The model only sees the evidence the
app already has, and is told not to add facts. If it fails or is switched off, a template is used.
"""

from . import config
from .evidence import TIER_LABEL

SYSTEM = (
    "You explain healthcare facility recommendations to patients and caregivers in India. "
    "Use ONLY the facts provided. Do not add medical advice, facilities, services, phone numbers or claims "
    "that are not in the facts. Be honest about uncertainty and mention any warnings. "
    "Write 2-3 short sentences in plain English, no lists, no headings."
)


def template_explanation(rec, service_label):
    ev = rec.get("evidence_text") or []
    first = ev[0] if ev else "no supporting evidence was found"
    s = (f"{rec['facility_name']} is {rec['distance_km']:.1f} km away. For {service_label.lower()}, the evidence "
         f"level is “{TIER_LABEL.get(rec['tier'], rec['tier'])}”: {first}.")
    if rec.get("warnings"):
        s += " Note: " + rec["warnings"][0]
    return s


def explain(rec, service_label):
    if not (config.EXPLAINER_ENABLED and config.LLM_ENDPOINT):
        return {"text": template_explanation(rec, service_label), "generated_by": "template"}
    facts = [
        f"Facility: {rec['facility_name']} ({rec.get('location') or 'location unknown'})",
        f"Requested service: {service_label}",
        f"Straight-line distance: {rec['distance_km']:.1f} km; location certainty: {rec.get('geo_confidence')}",
        f"Evidence level: {TIER_LABEL.get(rec['tier'], rec['tier'])} (tier {rec['tier']})",
        *[f"Evidence: {e}" for e in (rec.get("evidence_text") or [])[:6]],
        *[f"Warning: {w}" for w in (rec.get("warnings") or [])[:4]],
    ]
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

        w = WorkspaceClient()
        resp = w.serving_endpoints.query(
            name=config.LLM_ENDPOINT, max_tokens=220, temperature=0.2,
            messages=[ChatMessage(role=ChatMessageRole.SYSTEM, content=SYSTEM),
                      ChatMessage(role=ChatMessageRole.USER, content="Facts:\n" + "\n".join(facts))])
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            raise ValueError("empty response")
        return {"text": text, "generated_by": config.LLM_ENDPOINT}
    except Exception as e:  # never break the page because of the explainer
        return {"text": template_explanation(rec, service_label), "generated_by": "template",
                "note": f"AI explainer unavailable ({type(e).__name__})"}
