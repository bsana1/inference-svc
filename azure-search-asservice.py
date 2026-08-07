from flask import Flask, request, jsonify
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery
import openai
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, ContentSettings
from azure.core.exceptions import ResourceExistsError
import re
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

# Set these in a .env file (see .env.example)
indexer_name = os.environ["AZURE_SEARCH_INDEXER_NAME"]
storage_connection_string = os.environ["AZURE_BLOB_CONNECTION_STRING"]
container_name = os.environ["AZURE_BLOB_CONTAINER_NAME"]

indexName = os.environ["AZURE_SEARCH_INDEX_NAME"]
azureAiSearchEndpoint = os.environ["AZURE_AI_SEARCH_ENDPOINT"]
azureAiSearchKey = os.environ["AZURE_AI_SEARCH_KEY"]

azureOpenAiEndpoint = os.environ["AZURE_OPEN_AI_ENDPOINT"]
azureOpenAiKey = os.environ["AZURE_OPEN_AI_KEY"]
openAiApiKey = os.environ["OPEN_AI_API_KEY"]
deployment_name = "gpt-4o"

# Provide instructions to the model
GROUNDED_PROMPT = """
You are an AI assistant that helps users learn from the information found in the source material.
Answer the query using only the sources provided below.
Use bullets if the answer has multiple points.
If the answer is longer than 3 sentences, provide a summary.
Answer ONLY with the facts listed in the list of sources below.
If there isn't enough information below, say you don't know.
Do not generate answers that don't use the sources below.
Response using the markdown syntax.
Query: {query}
Sources:\n{sources}
"""

# Provide instructions to the model
GUIDELINEGROUNDED_PROMPT = """
You are an AI assistant that helps writers create content.
The provided sources are guidelines for writing.
Answer the questions based on what you can infer from the sources.
Query: {query}
Sources:\n{sources}
"""


app = Flask(__name__)


# Setup the search client
search_client = SearchClient(
    endpoint=azureAiSearchEndpoint,
    index_name=indexName,
    credential=AzureKeyCredential(azureAiSearchKey)
)

def upload_large_file_to_blob(file_path, chunk_size_mb=4):
    # Connection to the BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    file_name = os.path.basename(file_path)
    blob_client = container_client.get_blob_client(file_name)

    # Initialize variables
    chunk_size = chunk_size_mb * 1024 * 1024
    num_chunks = (os.path.getsize(file_path) // chunk_size) + 1

    print(f"Uploading {file_name} to Blob Storage in {num_chunks} chunks...")

    # Upload file in chunks
    with open(file_path, "rb") as file:
        for i in range(num_chunks):
            chunk_data = file.read(chunk_size)
            chunk_id = f"{i:06d}"
            print(f"Uploading chunk {i+1}/{num_chunks} (ID: {chunk_id})...")
            blob_client.stage_block(block_id=chunk_id, data=chunk_data)

    # Commit the blocks to finalize the upload
    print("Committing blocks...")
    block_list = [f"{i:06d}" for i in range(num_chunks)]
    blob_client.commit_block_list(block_list, content_settings=ContentSettings(content_type='application/pdf'))
    print("PDF uploaded successfully.")

def upload_pdf_to_blob(file_path, chunk_size_mb=4):
    blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
    container_client = blob_service_client.get_container_client(container_name)
    file_name = os.path.basename(file_path)
    blob_client = container_client.get_blob_client(file_name)

    # Upload large file in chunks
    print("Uploading PDF to Blob Storage...")
    try:
        with open(file_path, "rb") as data:
            blob_client.upload_blob(data, blob_type="BlockBlob", overwrite=True, max_concurrency=4, length=chunk_size_mb * 1024 * 1024)
    except ResourceExistsError:
        pass
    print("PDF uploaded successfully.")
    
def trigger_indexer():
    url = f"{azureAiSearchEndpoint}/indexers/{indexer_name}/run?api-version=2021-04-30-Preview"
    headers = {"api-key": azureAiSearchKey}

    print("Triggering Indexer...")
    response = requests.post(url, headers=headers)

    if response.status_code == 202:
        print("Indexer run triggered successfully.")
    else:
        print(f"Error triggering indexer: {response.status_code}, {response.text}")

def wait_for_indexing_completion():
    url = f"{azureAiSearchEndpoint}/indexers/{indexer_name}/status?api-version=2021-04-30-Preview"
    headers = {"api-key": azureAiSearchKey}

    print("Waiting for indexing to complete...")
    while True:
        response = requests.get(url, headers=headers)
        status = response.json()
        
        if status["lastResult"]["status"] in ["success", "error"]:
            print(f"Indexer completed with status: {status['lastResult']['status']}")
            break
        else:
            print("Indexer is still running...")
            time.sleep(10)

@app.route('/upload', methods=['POST'])
def upload():
    data = request.json
    fileUrl = data.get('filepath')
    file_path = data.get('filename')
    file_name = os.path.basename(file_path) if file_path else None
    
    # Use Azure OpenAI to answer the question
    vector_query = VectorizableTextQuery(text='*', k_nearest_neighbors=50, fields="text_vector")

    theFilter = f"file_path eq '{fileUrl}'" if fileUrl else f"title eq '{file_name}'"
    
    print(f"#### theFilter: {theFilter}")

    # Retrieve the selected fields from the search index related to the question
    search_results = search_client.search(
        search_text='',
        vector_queries=[vector_query],
        select=["title"],
        top=1,
        filter=theFilter
    )

    # Convert search_results to a list to check its length
    results_list = list(search_results)

    if len(results_list) > 0:
        return jsonify({'message': f'Document {file_name} already indexed'}), 200
    
    #upload_pdf_to_blob(file_path)
    upload_large_file_to_blob(file_path, 4)
    trigger_indexer()
    wait_for_indexing_completion()
        
    return jsonify({'message': f'Document {file_name} indexed successfully'}), 200

@app.route('/ask', methods=['POST'])
def ask():
    data = request.json
    file_path = data.get('filename')
    question = data['question']
    isGuideLine = data.get('type')  == 'guideline'
    searchTerm = data.get('search')
    file_name = os.path.basename(file_path) if file_path else None
    fileUrl = data.get('filepath')

    print(f"#### file path: {file_name}, question: {question}, search: {searchTerm if searchTerm else ''}")

    # Use Azure OpenAI to answer the question
    vector_query = VectorizableTextQuery(text=searchTerm if searchTerm else '*', k_nearest_neighbors=50, fields="text_vector")

    theFilter = f"file_path eq '{fileUrl}'" if fileUrl else f"title eq '{file_name}'"

    print(f"#### theFilter: {theFilter}")


    # Retrieve the selected fields from the search index related to the question
    search_results_iterable = search_client.search(
        search_text= searchTerm if searchTerm else '',
        vector_queries=[vector_query],
        select=["title", "chunk", "chunk_id"],
        top=50,
        filter=theFilter,
        order_by="chunk_id asc"
    )


    # Convert the iterable search results into a list
    search_results = list(search_results_iterable)

    # Function to extract and pad the numerical part of the chunk_id
    def get_padded_chunk_number(chunk_id):
        match = re.search(r'_(\d+)$', chunk_id)
        if match:
            return f'{int(match.group(1)):03}'  # Pad the number with leading zeros to 3 digits
        return chunk_id

    # Sort the search results based on the padded numerical part of the chunk_id
    search_results.sort(key=lambda doc: get_padded_chunk_number(doc.get("chunk_id", "")))
    
    # Collect chunk_ids in a list and print them
    chunk_ids = [document.get("chunk_id", "") for document in search_results]

    print("#### Chunk IDs:")
    for chunk_id in chunk_ids:
        print(chunk_id)

    # Format sources by joining the "chunk" field from search results
    sources_formatted = ", ".join([
        f'{document["chunk"]}' for document in search_results
    ])

     # Setup the OpenAI client
    openai.api_key = openAiApiKey

    groundedPrompts = GROUNDED_PROMPT.format(query=question, sources=sources_formatted)
    if isGuideLine:
        groundedPrompts = GUIDELINEGROUNDED_PROMPT.format(query=question, sources=sources_formatted)

    # Create completion request
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": groundedPrompts
            },
            {
                "role": "user",
                "content": question
            }
        ]
    )
    
    # Print response
    print(f"**question: {question}")
    answer = response.choices[0].message.content; 
    print(f"answer: {answer}")

    return jsonify({'response': answer}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
