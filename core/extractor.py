"""
core/extractor.py

Same LangChain chain-builder pattern as the original project.
extract_action_items / extract_key_decisions / extract_questions are kept
as-is (still useful for lecture/tutorial videos with a Q&A structure).
extract_key_points() and extract_keywords() are new, built for the
YouTube summarizer use case.
"""

from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
import os


def get_llm():
    return ChatMistralAI(
        model="mistral-small-latest",
        mistral_api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=0.2,
    )


def build_chain(system_prompt: str):
    llm = get_llm()
    return (
        RunnablePassthrough()
        | RunnableLambda(lambda x: {"text": x})
        | ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{text}"),
            ]
        )
        | llm
        | StrOutputParser()
    )


def extract_key_points(transcript: str) -> list:
    """Return a clean Python list of key points (bullet-ready for the UI)."""
    chain = build_chain(
        "You are an expert video analyst. From the transcript, extract the "
        "5-8 most important key points. Return ONLY a numbered list, one "
        "point per line, no preamble, no extra commentary."
    )
    raw = chain.invoke(transcript)
    return _lines_to_list(raw)


def extract_keywords(transcript: str) -> list:
    """Return a clean Python list of keywords/topics for the UI."""
    chain = build_chain(
        "You are an expert video analyst. From the transcript, extract "
        "8-12 important keywords or key phrases that best represent the "
        "video's topic. Return ONLY a comma-separated list, nothing else."
    )
    raw = chain.invoke(transcript)
    keywords = [kw.strip(" .\n-") for kw in raw.split(",") if kw.strip(" .\n-")]
    return keywords


def extract_action_items(transcript: str) -> str:
    chain = build_chain(
        "You are an expert meeting analyst. From the meeting transcript, "
        "extract all action items. For each provide:\n"
        "- Task description\n"
        "- Owner (who is responsible)\n"
        "- Deadline (if mentioned, else write 'Not specified')\n\n"
        "Format as a numbered list. If none found say 'No action items found.'"
    )
    return chain.invoke(transcript)


def extract_key_decisions(transcript: str) -> str:
    chain = build_chain(
        "You are an expert meeting analyst. From the meeting transcript, "
        "extract all key decisions made. Format as a numbered list. "
        "If none found say 'No key decisions found.'"
    )
    return chain.invoke(transcript)


def extract_questions(transcript: str) -> str:
    chain = build_chain(
        "From the meeting transcript, extract all unresolved questions "
        "or topics needing follow-up. Format as a numbered list. "
        "If none found say 'No open questions found.'"
    )
    return chain.invoke(transcript)


def _lines_to_list(raw: str) -> list:
    """Turn a numbered/bulleted LLM response into a clean list of strings."""
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # strip leading numbering like "1.", "1)", "-", "*"
        cleaned = line.lstrip("0123456789.)-* \t")
        if cleaned:
            items.append(cleaned)
    return items
