# Your private accountant

The accountant handels your data privately. All your data is in your local storage, and the model runs in your machine. It's capable of:
```
AI bookkeeping
+
Australian tax intelligence
+
BAS/GST preparation
+
tax optimization recommendations (with explanation and confidence)
```
It's a safe and intelligent financial operations assistant for Australian small businesses.

## Core Feature

The data pipeline:
source -> parse -> extract -> catergorize -> store locally 
### 1. Data ingestion
The app will import from:
- Email inboxes (Gmail, Outlook, IMAP)
- PDFs and invoices
- Receipt photos
- Bank CSV exports
- Stripe/PayPal CSV exports
- Supplier websites CSV exports
- Manual input from the UI

### 2. Extraction 
Agent reads the data and identifies:
- vendor
- date
- amount
- tax/GST
- category
- recurring payments
- client revenue
- invoice numbers


### 3. Data storage
Clean structured data stores locally. 

### 4. Chat and UI
The UI has a dashboard with cost and revenue, cash flows etc.

The user can ask the agent for numbers, charts, reports etc. 

### 5. Bank reconciliation 
### 6. Anomaly detection
### 7. Tax deductibles

for small business
### 8. BAS/GST reports
### 9. Budgeting
### 10. Cash flow forecasting 

## Core Architecture 
Frontend:
- Next.js or Electron app

Backend:
- Python FastAPI

AI Layer:
- Ollama for extraction
- Llama 3 for csv ingestion

Database:
- SQLite

File storage:
- Local filesystem

Vector DB:
- Chromadb

## Tools

| Purpose             | Local Tool              |
| ------------------- | ----------------------- |
| OCR                 | Tesseract / PaddleOCR   |
| Document parsing    | Unstructured.io         |
| LLM extraction      | Ollama                  |
| Local models        | Llama 3, Mistral, Gemma |
| Embeddings          | nomic-embed-text        |
| Workflow automation | n8n                     |
| Email sync          | IMAP                    |
| DB                  | SQLite                  |
| Vector DB           | Chromadb                |


## Core RAG flow 
- ### chat
1. user asks question
2. embed the question (convert into a vector)
3. search vector DB for similar vectors
4. build the prompt with the vector (build the context)
5. LLM answers with retrieved infomation 

- ### extraction
1. a new transaction

- ### ATO rulings

```
{
  "rule": "gst_threshold",
  "threshold": 75000,
  "condition": "annual_turnover"
}
```

- ### tax interpretations

- ### GST categories

- ### deduction examples

## AI Improvement
1. The extraction accuracy: types and category is sometimes wrong 
    - use rules e.g. 
    ```
    Uber → Transport
    AWS → Hosting
    Officeworks → Office Supplies
    ```
    - ML classification
    - user feedback learning
2. csv exports from different source are very different 
2. Extraction / deduplication: When extracting a new transaction from an email or PDF, use RAG to search for similar existing transactions first  
3. Anomaly detection: Before saving a transaction, search for similar past ones and compare the amount
4. Vendor normalisation: Different emails might write the same vendor differently (AWS, Amazon Web Services, AMAZON WEB SVCS). RAG can find existing vendor names and prompt the model to match them.

## Roadmap
### Phase 1
- transaction ingestion
- categorization
- GST detection
- monthly summaries
### Phase 2
- BAS estimation
- deduction recommendations
- anomaly detection
### Phase 3
- ATO rule RAG
- tax explanations
- forecast modeling
### Phase 4
- accountant collaboration mode
- one-click export to accountant
- audit trail
- reconciliation