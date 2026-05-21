# Your private accountant
The accountant handels your data privately. 

## core feature

The data pipeline:
source -> parse -> extract -> catergorize -> store locally 
### 1. Data ingestion
The app will import from:
- Email inboxes (Gmail, Outlook, IMAP)
- PDFs and invoices
- Receipt photos
- Bank CSV exports
- Ecommerce dashboards
- Web portals
- Stripe/PayPal exports
- Utility bills
- Supplier websites
- Manual input

### 2. AI extraction layer 
Agent reads the data and identifies:
- vendor
- date
- amount
- tax/GST
- category
- recurring payments
- client revenue
- invoice numbers

The model runs locally.

### 3. Data storage
Clean structured data stores locally. 

### 4. Chat and UI
The UI has a dashboard with cost and revenue, cash flows etc.

The user can ask the agent for numbers, charts, reports etc. 


## core architecture 
Frontend:
- Next.js or Electron app

Backend:
- Python FastAPI

AI Layer:
- Ollama local models

Database:
- SQLite

File storage:
- Local filesystem

## Core RAG flow (chat)
1. user asks question
2. embed the question (convert into a vector)
3. search vector DB for similar vectors
4. build the prompt with the vector (build the context)
5. LLM answers with retrieved infomation 


## Hard Parts

1. Data normalization

    Invoices are inconsistent.

2. Deduplication

    Same invoice from: email, PDF and upload
    
3. Confidence scoring

    AI extraction is never 100%.

4. Reconciliation

    Matching bank statements to invoices.

5. Tax logic

    GST/VAT rules become complex quickly.


## Improvement
1. Extraction / deduplication: When extracting a new transaction from an email or PDF, use RAG to search for similar existing transactions first  
2. Anomaly detection: Before saving a transaction, search for similar past ones and compare the amount
3. Vendor normalisation: Different emails might write the same vendor differently (AWS, Amazon Web Services, AMAZON WEB SVCS). RAG can find existing vendor names and prompt the model to match them.