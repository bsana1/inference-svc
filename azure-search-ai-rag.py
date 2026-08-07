# Import necessary libraries
import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

# Set these in a .env file (see .env.example)
azureAiSearchEndpoint = os.environ["AZURE_SEARCH_URL"]
azureAiSearchKey = os.environ["AZURE_SEARCH_KEY"]

azureOpenAiendpoint = os.environ["AZURE_OPEN_AI_URL"]
azureOpenAiKey = os.environ["AZURE_OPEN_AI_KEY"]
deployment_name = "gpt-4o"

# Provide instructions to the model
GROUNDED_PROMPT = """
You are an AI assistant that helps users learn from the information found in the source material.
Answer the query using only the sources provided below.
Use bullets if the answer has multiple points.
If the answer is longer than 3 sentences, provide a summary.
Answer ONLY with the facts listed in the list of sources below. Cite your source when you answer the question.
If there isn't enough information below, say you don't know.
Do not generate answers that don't use the sources below.
Query: {query}
Sources:\n{sources}
"""

# Setup the search client
search_client = SearchClient(
    endpoint=azureAiSearchEndpoint,
    index_name="py-rag-tutorial-idx",
    credential=AzureKeyCredential(azureAiSearchKey)
)

# Provide the search query
questions = [
    "What is the exact title of this document?",
    "What are the top 3-5 features corresponding to the product(s) discussed in the e-book?",
    "What competitive advantage do the product(s) in the e-book have, vs. competitors who develop similar products?",
    "Why should a customer read the e-book?"
]

for query in questions:
    vector_query = VectorizableTextQuery(text=query, k_nearest_neighbors=50, fields="text_vector")

    # Retrieve the selected fields from the search index related to the question
    search_results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        select=["title", "chunk", "locations"],
        top=10,
        filter="title eq 'whitepaper3_original.pdf'"
    )

    # Format sources
    sources_formatted = "".join([
        f'{document["chunk"]}' for document in search_results
    ])

    # Setup the OpenAI client
    client = AzureOpenAI(
        api_version="2023-07-01-preview",
        azure_endpoint=azureOpenAiendpoint,
        api_key=azureOpenAiKey
    )

    # Create completion request
    response = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": GROUNDED_PROMPT.format(query=query, sources=sources_formatted)
            }
        ],
        model=deployment_name
    )

    # Print response
    print(f"**question: {query}")
    print(f"answer: {response.choices[0].message.content}")
    