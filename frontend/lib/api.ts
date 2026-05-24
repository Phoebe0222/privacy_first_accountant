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

  getTransactions: (params?: { type?: string; category?: string; month?: string }) => {
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

  uploadFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<{ transaction: Partial<Transaction> }>("/import/file", {
      method: "POST",
      body: form,
    });
  },

  uploadCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const { job_id } = await req<{ job_id: string }>("/import/csv", { method: "POST", body: form });
    return api.pollJob(job_id);
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
