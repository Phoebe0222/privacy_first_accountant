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
TODO: put some screenshots here
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
Bank transactions come from the bank CSV exports, and reciepts can be from emails, PDFs or images upload, or supplier CSV exports. 

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


### 9. Tax scenarios

Tax behaviour is driven by two user settings: `income_type` and `gst_registered`.

| Scenario | income_type | gst_registered | profit/loss | Key behaviour | Taxable Income |
|---|---|---|---|---|---|
| Pure salary | employment | false | — | No BAS · work-related deductions only · tax = salary − employment deductions | `salary_income − salary_deductions` |
| Business + GST + profit | business / both | true | profit | BAS enabled · GST-exclusive amounts for income tax · combine with salary | `(salary_income − salary_deductions) + biz_net` *(GST-exclusive)* |
| Business + GST + loss | business / both | true | loss | BAS enabled · GST-exclusive amounts · NCL rules (Div 35) — loss may be deferred | loss deferred: `salary_income − salary_deductions`<br>loss offsets: `+ biz_net` *(GST-exclusive)* |
| Business no GST + profit | business / both | false | profit | No BAS · full amounts · $75k threshold warning · combine with salary | `(salary_income − salary_deductions) + biz_net` |
| Business no GST + loss | business / both | false | loss | No BAS · full amounts · $75k threshold warning · NCL rules — loss may be deferred | loss deferred: `salary_income − salary_deductions`<br>loss offsets: `+ biz_net` |

`biz_net = biz_income − biz_deductions` (negative when the business is in loss).

NCL = non-commercial loss (Division 35 ITAA 1997).
A business loss can only offset salary income if BOTH:
- the income requirement is met — taxable income, reportable fringe benefits, reportable
  super contributions and net investment losses (excluding this business loss) are
  under $250,000, AND
- one of four ATO tests is passed
  (business income ≥ $20k, 3-of-5 profit years, real property ≥ $500k, other assets ≥ $100k).

Otherwise the loss is deferred (carried forward against future profits from the same activity).
source:
- https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/income-you-must-declare/business-partnership-and-trust-income
- https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/deductions-you-can-claim/how-to-claim-deductions
- https://www.ato.gov.au/businesses-and-organisations/income-deductions-and-concessions/income-and-deductions-for-business/business-losses
- https://www.ato.gov.au/businesses-and-organisations/income-deductions-and-concessions/losses/non-commercial-losses/what-is-a-non-commercial-loss
### 10. Budgeting
### 11. Cash flow forecasting 

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
  ┌──────────────────────┐
  │  LLM + bound tools   │  decide: call a tool, or reply in plain text
  └──────────┬───────────┘
             │
             ├─ tool call ──► run it, append result as ToolMessage, repeat
             │   (search_transactions, update_transaction,
             │    bulk_update_category, get_financial_summary,
             │    query_tax_rules)
             │
             └─ plain-text reply
                  │
                  ▼
       ┌────────────────────┐
       │  Claim guard       │  claims an update was made, or lists
       └──────────┬─────────┘  "ID:n" rows, with no tool call this round?
                  │
                  ├─ yes ──► inject correction message, repeat
                  │
                  └─ no  ──► return reply to user

  Repeats up to 5 rounds total; if exhausted with no plain-text reply,
  returns "I wasn't able to complete that in time. Please try rephrasing.
```


## Core RAG flow 
- ### similar-transaction search (`transactions` collection)
1. embed a query — either a new transaction's text, or a `vendor:{name}` lookup
2. search the `transactions` collection for similar past transactions
3. reused by three different consumers, each with its own goal:
   - extraction agent — similar transactions as anomaly context for the Fields Agent
   - categorization agent — category consensus from past transactions (≥80% agreement resolves the category)
   - vendor normalizer — vendor-name consensus from past transactions (≥80% agreement resolves the vendor name)

- ### tax interpretations (`ato_rules` collection)
1. build a plain-English tax question (per category, from the user's chat message, or for a deduction estimate)
2. make sure ATO rules for that year are indexed (seeded + live-fetched, cached after first use)
3. embed the question and search the `ato_rules` collection
4. return the top matches with their source URLs
5. reused by three different consumers:
   - categorization agent — classify tax_kind (business / employment / na) for a transaction
   - chat agent — `query_tax_rules` tool, returns matches directly to the user
   - tax agent — assess deductibility rate per category


## Agent self-correction
The model itself sometimes hallucinate, e.g making numbers that do not exist, claiming it has done something without actually doing it. A prompt-only fix cannot fully solve it because the model itself only continues the conversation with the most likely answer, without knowing whether its tool is called. This should be handled by harness. The following chat agent example shows how to add a guard for a known failure.

The chat agent runs a tool-calling loop (max 5 rounds): LLM picks a tool → harness executes it against the real DB → result fed back → repeat until the LLM returns plain text.

Known failure mode: a tool-calling model can skip the tool call entirely and just narrate a fake success, e.g. replying "I have updated transactions ... to utility" with no real tool call in the logs. Prompt instructions alone don't reliably prevent this — the model has no way to "know" whether its tool call actually happened, only the harness does.

Guard (harness-level, not prompt-level):
1. Track `made_write_change` — set only when `update_transaction`/`bulk_update_category` is called **and** its result starts with `"Updated"` (i.e. it actually succeeded, not a validation error).
2. `_CLAIM_RE` matches "done"-style phrasing in a final reply (e.g. "I've updated...", "...are now categorized...", "successfully updated...").
3. If a reply matches `_CLAIM_RE` while `made_write_change` is still `False`, the harness doesn't return it — it injects a corrective message ("you claimed a change but didn't call the tool — call it now or tell the user honestly") and lets the model retry, within the existing 5-round budget.

## User input correction
Model hallucinate -> user correct result -> re-index the transaction -> the model uses the memory/RAG in the next task



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
### Phase 4
- forecast modeling
- audit trail
