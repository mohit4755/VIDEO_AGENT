"""
core/summarizer.py

Same LangChain + Mistral summarization approach as the original project,
with one addition: summarize_short() for a quick 3-4 sentence summary,
used alongside the original map-reduce summarize() (now the "detailed"
summary).
"""

import os
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnablePassthrough, RunnableLambda


def get_llm(temperature: float = 0.3):
    return ChatMistralAI(
        model="mistral-small-latest",
        mistral_api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=temperature,
    )


def split_transcript(transcript: str) -> list:
    splitter = RecursiveCharacterTextSplitter(chunk_size=3000, chunk_overlap=200)
    return splitter.split_text(transcript)


def summarize_detailed(transcript: str) -> str:
    """
    Map-reduce summary (unchanged from the original summarize()):
    summarize each chunk, then combine the partial summaries into one
    detailed, well-structured summary.
    """
    llm = get_llm()

    map_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Summarize this portion of a video transcript concisely."),
            ("human", "{text}"),
        ]
    )
    map_chain = map_prompt | llm | StrOutputParser()

    chunks = split_transcript(transcript)
    chunk_summaries = [map_chain.invoke({"text": chunk}) for chunk in chunks]
    combined = "\n\n".join(chunk_summaries)

    combined_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are an expert video summarizer. Combine these partial "
                "summaries into one detailed, well-structured summary of the "
                "video, written in clear paragraphs (not bullet points).",
            ),
            ("human", "{text}"),
        ]
    )
    combined_chain = (
        RunnablePassthrough()
        | RunnableLambda(lambda x: {"text": x})
        | combined_prompt
        | llm
        | StrOutputParser()
    )
    return combined_chain.invoke(combined)


def summarize_short(transcript: str) -> str:
    """A quick 3-4 sentence summary, generated straight from the transcript."""
    llm = get_llm()
    chain = (
        RunnablePassthrough()
        | RunnableLambda(lambda x: {"text": x})
        | ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Summarize this video transcript in 3-4 concise sentences. "
                    "Capture only the core idea, no filler.",
                ),
                ("human", "{text}"),
            ]
        )
        | llm
        | StrOutputParser()
    )
    # Short summary doesn't need the full map-reduce pass; the first ~6000
    # chars plus a closing slice usually gives the model enough signal.
    sample = transcript[:6000]
    if len(transcript) > 12000:
        sample += "\n...\n" + transcript[-2000:]
    return chain.invoke(sample)


def generate_title(transcript: str) -> str:
    llm = get_llm()
    title_chain = (
        RunnablePassthrough()
        | RunnableLambda(lambda x: {"text": x})
        | ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Based on the video transcript, generate a short, "
                    "descriptive title (max 10 words). Only return the "
                    "title, nothing else.",
                ),
                ("human", "{text}"),
            ]
        )
        | llm
        | StrOutputParser()
    )
    return title_chain.invoke(transcript[:2000])
