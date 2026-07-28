# DocMind - PDF Chatbot

DocMind is a lightweight Flask app that lets you upload a PDF and chat with it using local AI models. The app follows a simple RAG workflow: it processes the document, stores its content in a vector database, and uses that context to answer your questions.

## Features

- Upload a PDF from your computer
- Load a PDF using an absolute file path
- Load a PDF from a Google Drive link
- Ask questions and get answers based on the document content
- Use local models through Ollama

## Tech Stack

- Python
- Flask
- LangChain
- Ollama
- FAISS
- PyPDF

## Requirements

Before getting started, make sure you have:

- Python 3.10 or newer
- pip
- Ollama installed and running

## Quick Start

### 1. Open the project folder

```bash
cd "C:\path\to\Simple_PDF"
```

### 2. Create and activate a virtual environment

On Windows PowerShell:

```powershell
python -m venv chatbot_test_env
.\chatbot_test_env\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Pull the required Ollama models

```bash
ollama pull llama3.1
ollama pull bge-m3
```

### 5. Run the application

```bash
python app.py
```

Then open your browser at:

```text
http://127.0.0.1:5000
```

## Optional Configuration

If you want to customize the model names, create a .env file with:

```env
LLM_MODEL=llama3.1:latest
EMBEDDING_MODEL=bge-m3
```

## Project Structure

- app.py - main Flask application and API routes
- config.py - project configuration and environment variables
- templates/ - frontend HTML files
- static/ - CSS and JavaScript assets
- utils/ - document loading, chunking, embeddings, and chatbot logic
- uploads/ - uploaded PDF files
- vector_store/ - FAISS vector database files

## Architecture

A simple visual overview of the system is shown below:

```text
User
  │
  ▼
Flask Web App
  │
  ├─ Upload / Path / Drive Link
  │
  ▼
Document Processing
  ├─ Extract text
  ├─ Split into chunks
  └─ Create embeddings

Embeddings ──► FAISS Vector Store

User Question ──► Embedding Search ──► Relevant Chunks ──► Ollama LLM ──► Answer
```

### 1. PDF Ingestion Flow

1. The user uploads a PDF, provides a local file path, or shares a Google Drive link.
2. The Flask app receives the request and sends the document to the loader module.
3. The document is extracted, split into smaller chunks, and converted into embeddings.
4. These embeddings are stored in a FAISS vector store for later retrieval.

### 2. User Query to Answer Flow

1. The user asks a question through the web interface.
2. The app converts the question into an embedding and searches the FAISS store for the most relevant chunks.
3. The retrieved chunks are passed to the LLM through Ollama.
4. The model generates a response grounded in the selected document context.

## Troubleshooting

If the app does not work properly, check that:

- Ollama is installed and running
- The required models were pulled successfully
- Your Python environment has all dependencies installed
