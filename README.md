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
It's a safe and intelligent financial operations assistant for Australian small businesses, sole traders, or any individuals who want to do their own accounting. 

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
Clean structured data stores locally, both your transactions and the vectors. 

### 4. Chat and UI
The UI has a dashboard with cost and revenue, cash flows etc.

The user can ask the agent for numbers, charts, reports etc. and ask the agent to change some transactions. 

### 5. Bank reconciliation 
The user can reconciliate the bank transactions with receipts from different sources, e.g. email, pdf receipts, images. 

### 6. Anomaly detection
Comparing to similar past transactions, if the transaction is more than twice or less than half of the average, it will be flagged.

### 7. Tax deductibles
For any tax payer, estimate the tax deductions, based on rules and llm. 

### 8. BAS/GST reports
For small business, estimate BAS/GST based on the sales. This is deterministic.

```
Inputs
  business transactions only  (business = true, source = bank_csv or manual)

G1  — Total Sales
  = Σ amount  where  type = income  AND  category = sales

G11 — Total Purchases
  = Σ amount  where  type = expense

1A  — GST Collected  (on sales)
  = Σ tax    where  type = income  AND  category = sales

1B  — Input Tax Credits  (on purchases)
  = Σ tax    where  type = expense

Net GST payable = 1A − 1B

GST registration warning
  annualised G1 = G1 × 4  (quarterly)  or  G1 × 1  (annual)
  warn if annualised G1 ≥ $75,000
```


### 9. Budgeting
### 10. Cash flow forecasting 

## Core Architecture 
Frontend:
- Next.js or Electron app

Backend:
- Python FastAPI

AI Layer:
- Ollama runtime
- Rag
- Multi-agents framework
- Llama 3 for csv ingestion

Database:
- SQLite

File storage:
- Local filesystem

Vector DB:
- Chromadb

## Multi-agents framework 
- ### Extraction agent 
```
  ┌─────────────────────┐
  │  Clean Text         │  Decode HTML entities, strip invisible Unicode spacers
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Load Rules         │  Fetch vendor rules from DB (skipped if pre-populated)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  RAG Search         │  Find similar past transactions for anomaly context
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Skip Agent         │  Is this a real completed transaction?
  └──────────┬──────────┘
             │ not skipped
             ▼
  ┌─────────────────────┐
  │  Type Agent         │  Income or expense? (regex shortcut for refunds)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Fields Agent       │  Vendor, date, amount, tax, description, invoice #, anomaly
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Vendor Normalizer  │  Strip legal suffixes, LLM for complex names
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Categorize         │  Rules → history consensus → LLM
  └─────────────────────┘
```
- ### CSV column mapping agent 
```
  ┌─────────────────────┐   ┌─────────────────────┐
  │  Core Columns Agent │   │  Pattern Detector   │
  │  (LLM)              │   │  (regex, no LLM)    │
  └──────────┬──────────┘   └──────────┬──────────┘
             │                         │
             ▼                         │
  ┌─────────────────────┐              │
  │  Classification     │              │
  │  Agent (LLM)        │              │
  └──────────┬──────────┘              │
             └──────────┬─────────────┘
                        ▼
                 Python Resolver
                 (merge + validate)
```
- ### Vendor Normalizer
```
  ┌──────────────────┐
  │  Rules Step      │  Unwrap processor/bank prefix, strip noise, short-name check
  └──────────┬───────┘
             │ unresolved (> 3 words)
             ▼
  ┌──────────────────┐
  │  RAG Step        │  Find consensus name from past transactions (≥80% agreement)
  └──────────┬───────┘
             │ unresolved
             ▼
  ┌──────────────────┐
  │  LLM Step        │  Extract brand name for complex / first-seen cases
  └──────────────────┘
```
- ### Categorise agent 
```
                ┌──────────────────┐
  state ──────► │  apply_rules     │ (pure Python, no LLM)
                └────────┬─────────┘
                         │ unresolved
                         ▼
                ┌──────────────────┐
                │  search_history  │ (RAG consensus)
                └────────┬─────────┘
                         │ unresolved
                         ▼
                ┌──────────────────┐
                │  llm_categorize  │ (ChatOllama + structured output)
                └──────────────────┘
```
- ### Chat agent
```
```
## Core RAG flow 
- ### chat (maybe)
1. user asks question
2. embed the question (convert into a vector)
3. search vector DB for similar vectors
4. build the prompt with the vector (build the context)
5. LLM answers with retrieved infomation 

- ### extraction
1. a new transaction (either model generated or user created)
2. embed the transaction
3. search for similar transactions
4. add the similar transactions in the prompt
5. better categorization and detect anomoly 

- ### tax interpretations

- ### GST categories

- ### deduction examples


## Roadmap
### Phase 1
- transaction ingestion
- **categorization** -- **this is important**
- anomaly detection
- monthly summaries
- User define rules from UI -- deterministic
- bank reconciliation -- auto and manual
### Phase 2
- BAS estimation
- deduction recommendations
- GST detection
### Phase 3
- ATO rule RAG
- tax explanations
- forecast modeling
### Phase 4
- accountant collaboration mode
- one-click export to accountant
- audit trail
