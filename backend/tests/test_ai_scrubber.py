import pytest
from backend.utilities.ai_scrubber import clean_ai_text, stream_clean_ai_text

def test_clean_ai_text_phrases():
    text1 = "As an AI, I recommend this. I hope this helps!"
    assert clean_ai_text(text1).strip() == "I recommend this."
    
    text2 = "As an AI language model, here is your summary."
    assert clean_ai_text(text2).strip() == "here is your summary."
    
    text3 = "I am an AI, and this is my output."
    assert clean_ai_text(text3).strip() == "and this is my output."

def test_clean_ai_text_words():
    text1 = "We should delve into this robust solution to leverage our tapestry."
    assert clean_ai_text(text1) == "We should explore into this strong solution to use our collection."
    
    # Test case matching
    text2 = "Delve Leverage ROBUST TAPESTRY Testament"
    assert clean_ai_text(text2) == "Explore Use STRONG COLLECTION Proof"
    
def test_clean_ai_text_em_dashes():
    # Runs of hyphens collapse to a single plain hyphen — never an em-dash.
    text = "This is a test --- and it works -- perfectly."
    assert clean_ai_text(text) == "This is a test - and it works - perfectly."

def test_clean_ai_text_real_em_dash_character():
    # The far more common real-world case: the LLM emits an actual em-dash
    # character directly, not "--". A single "—" used to pass through
    # untouched (the old regex required a run of 2+).
    text = "Built a strong system—used by thousands of engineers."
    assert clean_ai_text(text) == "Built a strong system-used by thousands of engineers."

def test_clean_ai_text_resume_safety():
    # Real resume text shouldn't be overly damaged. Words like "robust" are replaced but the sentence stands.
    text = "Built a robust backend system using Python."
    assert clean_ai_text(text) == "Built a strong backend system using Python."

@pytest.mark.asyncio
async def test_stream_clean_ai_text():
    # Simulate a generator yielding chunks
    async def mock_stream():
        chunks = [
            "Hello! As ", 
            "an AI, I ",
            "am here to help. ",
            "Let's del",
            "ve into it."
        ]
        for c in chunks:
            yield c

    result = ""
    async for cleaned_chunk in stream_clean_ai_text(mock_stream()):
        result += cleaned_chunk

    expected = "Hello! I am here to help. Let's explore into it."
    assert result == expected
