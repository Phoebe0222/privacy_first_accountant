const BASE = "/api";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

// ── Transactions ────────────────────────────────────────────────────────────

export interface Transaction {
  id: number;
  date: string;
  vendor: string;
  amount: number;
  tax: number;
  category: string;
  type: "income" | "expense" | "transfer" | "transfer-in" | "transfer-out";
  source: string;
  description?: string;
  invoice_number?: string;
  anomaly?: boolean;
  anomaly_reason?: string;
  needs_review?: boolean;
  category_confidence?: number;
  business?: boolean;
  source_ref?: string;
  created_at: string;
}

export interface Summary {
  total_income: number;
  total_expenses: number;
  net_profit: number;
  monthly: { month: string; type: string; total: number }[];
  by_category: { category: string; total: number }[];
  business_income: number;
  business_expenses: number;
  business_net: number;
  by_category_business: { category: string; total: number }[];
  personal_expenses: number;
  personal_income: number;
  by_category_personal: { category: string; total: number }[];
}

export const api = {
  getSummary: () => req<Summary>("/transactions/summary"),

  getTransactions: (params?: { type?: string; category?: string; month?: string; date_from?: string; date_to?: string; source?: string; source_ref?: string; vendor?: string; needs_review?: boolean; anomaly?: boolean; sort_by?: string; sort_dir?: string; limit?: number; offset?: number }) => {
    const defined = Object.fromEntries(
      Object.entries(params ?? {}).filter(([, v]) => v !== undefined)
    );
    const q = new URLSearchParams(defined as Record<string, string>).toString();
    return req<{ total: number; items: Transaction[] }>(`/transactions${q ? "?" + q : ""}`);
  },

  createTransaction: (data: Omit<Transaction, "id" | "created_at">) =>
    req<Transaction>("/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  updateTransaction: (id: number, data: Partial<Transaction>) =>
    req<Transaction>(`/transactions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  deleteTransaction: (id: number) =>
    req<{ ok: boolean }>(`/transactions/${id}`, { method: "DELETE" }),

  dismissAnomaly: (id: number) =>
    req<Transaction>(`/transactions/${id}/dismiss-anomaly`, { method: "POST" }),

  getSourceText: (id: number) =>
    req<{ id: number; source: string; source_ref: string | null; raw_text: string }>(`/transactions/${id}/source`),

  deleteBySourceRef: (sourceRef: string) =>
    req<{ deleted: number }>(`/transactions?source_ref=${encodeURIComponent(sourceRef)}`, { method: "DELETE" }),

  deleteBySource: (source: string) =>
    req<{ deleted: number }>(`/transactions?source=${encodeURIComponent(source)}`, { method: "DELETE" }),

  getImportHistory: () =>
    req<{ source: string; source_ref: string; count: number; date_from: string; date_to: string; imported_at: string }[]>("/transactions/imports"),

  getReviewQueue: () =>
    req<{ count: number; items: Transaction[] }>("/transactions/review-queue"),

  getAnomalies: () =>
    req<{ total: number; items: Transaction[] }>("/transactions?anomaly=true&sort_by=date&sort_dir=desc&limit=100"),

  // ── Import ──────────────────────────────────────────────────────────────

  getEmailAccounts: () => req<EmailAccount[]>("/import/email-accounts"),

  addEmailAccount: (data: Omit<EmailAccount, "id" | "last_synced">) =>
    req<EmailAccount>("/import/email-accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  deleteEmailAccount: (id: number) =>
    req<{ ok: boolean }>(`/import/email-accounts/${id}`, { method: "DELETE" }),

  startSync: (id: number, reimport = false) =>
    req<{ job_id: string }>(`/import/email-accounts/${id}/sync?reimport=${reimport}`, { method: "POST" }),

  pollJob: async (jobId: string): Promise<{ added: number; skipped: number }> => {
    while (true) {
      const job = await req<{ status: string; added?: number; skipped?: number; error?: string }>(
        `/import/jobs/${jobId}`
      );
      if (job.status === "done") return { added: job.added ?? 0, skipped: job.skipped ?? 0 };
      if (job.status === "failed") throw new Error(job.error ?? "Sync failed");
      await new Promise((r) => setTimeout(r, 2000));
    }
  },

  startFileUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<{ job_id: string }>("/import/file", { method: "POST", body: form });
  },

  pollFileJob: async (jobId: string): Promise<{ vendor: string; type: string; amount: number; date: string; category: string }> => {
    while (true) {
      const job = await req<{ status: string; transaction?: { vendor: string; type: string; amount: number; date: string; category: string }; error?: string }>(
        `/import/jobs/${jobId}`
      );
      if (job.status === "done" && job.transaction) return job.transaction;
      if (job.status === "failed") throw new Error(job.error ?? "File processing failed");
      await new Promise((r) => setTimeout(r, 2000));
    }
  },

  startCsvUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<{ job_id: string }>("/import/csv", { method: "POST", body: form });
  },

  startBankCsvUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<{ job_id: string }>("/import/bank-csv", { method: "POST", body: form });
  },

  // ── Vendor rules ────────────────────────────────────────────────────────

  getVendorRules: () => req<{ id: number; vendor_pattern: string; category: string }[]>("/vendor-rules"),

  getBuiltInRules: () => req<{ vendor_pattern: string; category: string }[]>("/vendor-rules/built-in"),

  createVendorRule: (vendor_pattern: string, category: string) =>
    req<{ id: number; vendor_pattern: string; category: string }>("/vendor-rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendor_pattern, category }),
    }),

  deleteVendorRule: (id: number) =>
    req<{ ok: boolean }>(`/vendor-rules/${id}`, { method: "DELETE" }),

  // ── ATO rules ───────────────────────────────────────────────────────────

  getATORules: () => req<{ id: number; title: string; description: string }[]>("/ato-rules"),

  createATORule: (title: string, description: string) =>
    req<{ id: number; title: string; description: string }>("/ato-rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, description }),
    }),

  deleteATORule: (id: number) =>
    req<{ ok: boolean }>(`/ato-rules/${id}`, { method: "DELETE" }),

  // ── Chat ────────────────────────────────────────────────────────────────

  sendChat: (message: string) =>
    req<{ reply: string }>("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }),

  getChatHistory: () =>
    req<{ role: string; content: string; created_at: string }[]>("/chat/history"),

  clearChatHistory: () => req<{ ok: boolean }>("/chat/history", { method: "DELETE" }),

  // ── Deductions ──────────────────────────────────────────────────────────

  getDeductionSettings: () => req<{ user_type: string }>("/deductions/settings"),
  updateDeductionSettings: (user_type: string) =>
    req<{ user_type: string }>("/deductions/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_type }),
    }),
  getDeductionRules: (user_type: string) =>
    req<DeductionRule[]>(`/deductions/rules?user_type=${user_type}`),
  createDeductionRule: (data: Omit<DeductionRule, "id">) =>
    req<DeductionRule>("/deductions/rules", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateDeductionRule: (id: number, data: { rate?: number; label?: string; note?: string }) =>
    req<DeductionRule>(`/deductions/rules/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteDeductionRule: (id: number) =>
    req<{ ok: boolean }>(`/deductions/rules/${id}`, { method: "DELETE" }),
  resetDeductionRules: (user_type: string) =>
    req<DeductionRule[]>(`/deductions/rules/reset?user_type=${user_type}`, { method: "POST" }),
  getDeductionsEstimate: (year: number) =>
    req<DeductionsEstimate>(`/deductions/estimate?year=${year}`),

  // ── BAS ─────────────────────────────────────────────────────────────────

  getBas: (year: number, quarter: string) =>
    req<BasResult>(`/bas?year=${year}&quarter=${quarter}`),

  // ── Reconciliation ───────────────────────────────────────────────────────

  getReconciliationSummary: () =>
    req<{ total_bank: number; total_receipts: number; matched: number; unmatched_bank: number; unmatched_receipts: number }>("/reconciliation/summary"),

  getReconciliationMatches: (status?: string) =>
    req<ReconciliationMatch[]>(`/reconciliation/matches${status ? "?status=" + status : ""}`),

  runAutoReconcile: () =>
    req<{ new_matches: number; unmatched_bank: number; unmatched_receipts: number }>("/reconciliation/run", { method: "POST" }),

  createMatch: (bank_tx_id: number, receipt_tx_id: number) =>
    req<ReconciliationMatch>("/reconciliation/matches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bank_tx_id, receipt_tx_id }),
    }),

  updateMatch: (match_id: number, status: "confirmed" | "rejected") =>
    req<ReconciliationMatch>(`/reconciliation/matches/${match_id}?status=${status}`, { method: "PATCH" }),

  deleteMatch: (match_id: number) =>
    req<{ ok: boolean }>(`/reconciliation/matches/${match_id}`, { method: "DELETE" }),

  getUnmatchedBank: () => req<TxSummary[]>("/reconciliation/unmatched/bank"),
  getUnmatchedReceipts: () => req<TxSummary[]>("/reconciliation/unmatched/receipts"),
};

export interface DeductionRule {
  id: number;
  user_type: string;
  category: string;
  rate: number;
  label: string;
  note?: string;
}

export interface DeductionItem {
  category: string;
  label: string;
  total_spent: number;
  rate: number;
  deductible_amount: number;
  note?: string;
}

export interface DeductionsEstimate {
  year: number;
  period: string;
  date_range: string;
  user_type: string;
  items: DeductionItem[];
  total_deductible: number;
  total_expenses: number;
}

export interface BasResult {
  period: string;
  date_range: string;
  G1: number;
  G11: number;
  tax_1A: number;
  tax_1B: number;
  net_gst: number;
  transaction_count: number;
  gst_registration_warning: boolean;
  annualised_income: number;
}

export interface TxSummary {
  id: number;
  date: string;
  vendor: string;
  amount: number;
  type: string;
  category: string;
  source: string;
  description?: string;
}

export interface ReconciliationMatch {
  id: number;
  bank: TxSummary | null;
  receipt: TxSummary | null;
  confidence: number;
  status: "auto" | "confirmed" | "rejected";
  created_at: string;
}

export interface EmailAccount {
  id: number;
  name: string;
  email: string;
  imap_host: string;
  imap_port: number;
  username: string;
  last_synced?: string;
}
