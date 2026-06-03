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
  type: "income" | "expense";
  source: string;
  description?: string;
  invoice_number?: string;
  anomaly?: boolean;
  anomaly_reason?: string;
  business?: boolean;
  created_at: string;
}

export interface Summary {
  total_income: number;
  total_expenses: number;
  net_profit: number;
  monthly: { month: string; type: string; total: number }[];
  by_category: { category: string; total: number }[];
}

export const api = {
  getSummary: () => req<Summary>("/transactions/summary"),

  getTransactions: (params?: { type?: string; category?: string; month?: string; anomaly?: boolean }) => {
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

  syncEmailAccount: async (id: number, daysBack = 30, reimport = false) => {
    const { job_id } = await req<{ job_id: string }>(
      `/import/email-accounts/${id}/sync?days_back=${daysBack}&reimport=${reimport}`,
      { method: "POST" }
    );
    while (true) {
      await new Promise((r) => setTimeout(r, 2000));
      const job = await req<{ status: string; added?: number; skipped?: number; errors?: unknown[] }>(
        `/import/jobs/${job_id}`
      );
      if (job.status === "done") return job as { added: number; skipped: number; errors: unknown[] };
      if (job.status === "failed") throw new Error((job as { error?: string }).error ?? "Sync failed");
    }
  },

  uploadFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<{ transaction: Partial<Transaction> }>("/import/file", {
      method: "POST",
      body: form,
    });
  },

  uploadCsv: async (file: File, csvType: "bank" | "supplier" = "supplier") => {
    const form = new FormData();
    form.append("file", file);
    const { job_id } = await req<{ job_id: string }>(`/import/csv?csv_type=${csvType}`, {
      method: "POST",
      body: form,
    });
    while (true) {
      await new Promise((r) => setTimeout(r, 2000));
      const job = await req<{ status: string; added?: number; skipped?: number; error?: string }>(
        `/import/jobs/${job_id}`
      );
      if (job.status === "done") return { added: job.added ?? 0, skipped: job.skipped ?? 0 };
      if (job.status === "failed") throw new Error(job.error ?? "CSV import failed");
    }
  },

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

  // ── BAS ─────────────────────────────────────────────────────────────────

  getBas: (fy: number, quarter: string) =>
    req<BasResult>(`/bas?fy=${fy}&quarter=${quarter}`),

  // ── Deductions ───────────────────────────────────────────────────────────

  getDeductionSettings: () =>
    req<{ user_type: string }>("/deductions/settings"),

  updateDeductionSettings: (user_type: string) =>
    req<{ user_type: string }>("/deductions/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_type }),
    }),

  getDeductionRules: (user_type: string) =>
    req<DeductionRule[]>(`/deductions/rules?user_type=${user_type}`),

  createDeductionRule: (data: Omit<DeductionRule, "id">) =>
    req<DeductionRule>("/deductions/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  updateDeductionRule: (id: number, data: { rate?: number; label?: string; note?: string }) =>
    req<DeductionRule>(`/deductions/rules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  deleteDeductionRule: (id: number) =>
    req<{ ok: boolean }>(`/deductions/rules/${id}`, { method: "DELETE" }),

  resetDeductionRules: (user_type: string) =>
    req<DeductionRule[]>(`/deductions/rules/reset?user_type=${user_type}`, { method: "POST" }),

  getDeductionsEstimate: (year: number) =>
    req<DeductionsEstimate>(`/deductions/estimate?year=${year}`),
};

export interface EmailAccount {
  id: number;
  name: string;
  email: string;
  imap_host: string;
  imap_port: number;
  username: string;
  last_synced?: string;
}

export interface BasResult {
  period: string;
  fy: number;
  quarter: string;
  date_range: string;
  G1: number;
  G11: number;
  tax_1A: number;
  tax_1B: number;
  net_gst: number;
  transaction_count: number;
  gst_registration_warning: boolean;
}

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
  user_type: string;
  items: DeductionItem[];
  total_deductible: number;
}
