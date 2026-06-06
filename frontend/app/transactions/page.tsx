"use client";
import React, { useEffect, useState } from "react";
import { api, Transaction, ReconciliationMatch } from "@/lib/api";
import VendorRulesTab from "@/components/VendorRulesTab";

const CATEGORIES = ["all", "food", "grocery", "drink", "transport", "travel", "utilities", "software", "marketing", "revenue", "salary", "refund", "office", "subscription", "shopping", "leisure", "material", "fee", "gym", "medical", "other"];
const FORM_CATEGORIES = CATEGORIES.filter((c) => c !== "all");
const EMPTY_FORM = { date: "", vendor: "", amount: "", tax: "", category: "other", type: "expense" as "income" | "expense", description: "" };

function fyStartYear(): number {
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
}

function fyOptions() {
  const current = fyStartYear();
  return Array.from({ length: 4 }, (_, i) => current - i).map((y) => ({
    label: `FY ${y}–${String(y + 1).slice(2)}`,
    value: `fy:${y}`,
    from: `${y}-07-01`,
    to: `${y + 1}-06-30`,
  }));
}

const FY_OPTIONS = fyOptions();

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function TransactionsPage() {
  const [pageTab, setPageTab] = useState<"transactions" | "rules">("transactions");
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [type, setType] = useState("");
  const [category, setCategory] = useState("all");
  const [sourceRef, setSourceRef] = useState("");
  const [importFiles, setImportFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortCol, setSortCol] = useState<keyof Transaction>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [dateRange, setDateRange] = useState<"all" | "custom" | string>(`fy:${fyStartYear()}`);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [source, setSource] = useState("bank_csv");
  const [vendor, setVendor] = useState("");
  const [businessOnly, setBusinessOnly] = useState(false);
  const [matchMap, setMatchMap] = useState<Record<number, ReconciliationMatch>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ vendor: "", category: "other", amount: "", tax: "", type: "expense" as "income" | "expense" | "transfer" | "transfer-in" | "transfer-out", description: "" });
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  function load(p = page, col = sortCol, dir = sortDir) {
    setLoading(true);
    const fy = FY_OPTIONS.find((o) => o.value === dateRange);
    const date_from = dateRange === "custom" ? customFrom || undefined : fy?.from;
    const date_to = dateRange === "custom" ? customTo || undefined : fy?.to;
    Promise.all([
      api.getTransactions({ type: type || undefined, category: category === "all" ? undefined : category, date_from, date_to, source: source || undefined, source_ref: sourceRef || undefined, vendor: vendor || undefined, business: businessOnly || undefined, sort_by: col, sort_dir: dir, limit: PAGE_SIZE, offset: (p - 1) * PAGE_SIZE }),
      api.getReconciliationMatches(),
    ]).then(([{ items, total }, matches]) => {
      setItems(items);
      setTotal(total);
      const map: Record<number, ReconciliationMatch> = {};
      for (const m of matches) if (m.bank?.id) map[m.bank.id] = m;
      setMatchMap(map);
    }).finally(() => setLoading(false));
  }

  function resetAndLoad() { setPage(1); load(1); }

  useEffect(() => {
    api.getImportHistory().then((h) =>
      setImportFiles(h.filter((f) => f.source === "bank_csv").map((f) => f.source_ref))
    ).catch(() => {});
  }, []);
  useEffect(() => { resetAndLoad(); }, [type, category, dateRange, customFrom, customTo, source, vendor, sourceRef, businessOnly]);
  useEffect(() => { load(page); }, [page]);
  useEffect(() => { setPage(1); load(1, sortCol, sortDir); }, [sortCol, sortDir]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this transaction?")) return;
    await api.deleteTransaction(id);
    load(page);
  }

  function handleSort(col: keyof Transaction) {
    if (col === sortCol) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    await api.createTransaction({
      date: form.date,
      vendor: form.vendor,
      amount: parseFloat(form.amount) || 0,
      tax: parseFloat(form.tax) || 0,
      category: form.category,
      type: form.type,
      description: form.description,
      source: "manual",
    });
    setForm(EMPTY_FORM);
    setShowForm(false);
    load();
  }

  function startEdit(t: Transaction) {
    setEditingId(t.id);
    setEditForm({ vendor: t.vendor, category: t.category, amount: String(t.amount), tax: String(t.tax), type: t.type, description: t.description ?? "" });
  }

  async function saveEdit(id: number) {
    const updated = await api.updateTransaction(id, {
      vendor: editForm.vendor,
      category: editForm.category,
      amount: parseFloat(editForm.amount) || 0,
      tax: parseFloat(editForm.tax) || 0,
      type: editForm.type,
      description: editForm.description,
    });
    setItems((prev) => prev.map((t) => t.id === id ? updated : t));
    setEditingId(null);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">
          {pageTab === "transactions"
            ? <>Transactions <span className="text-base font-normal text-gray-400">({total})</span></>
            : "Vendor Rules"}
        </h2>
        <div className="flex gap-2">
          {pageTab === "transactions" && (
            <button onClick={() => setShowForm(!showForm)}
              className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors">
              + Add
            </button>
          )}
          <button onClick={() => setPageTab("transactions")}
            className={`text-sm px-4 py-2 rounded-lg border transition-colors ${pageTab === "transactions" ? "bg-gray-800 text-white border-gray-800" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
            Transactions
          </button>
          <button onClick={() => setPageTab("rules")}
            className={`text-sm px-4 py-2 rounded-lg border transition-colors ${pageTab === "rules" ? "bg-gray-800 text-white border-gray-800" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
            Vendor Rules
          </button>
        </div>
      </div>

      {pageTab === "rules" && <VendorRulesTab />}

      {pageTab === "transactions" && showForm && (
        <form onSubmit={handleCreate} className="bg-white border border-gray-100 rounded-xl p-6 shadow-sm grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Date</label>
            <input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Vendor</label>
            <input required value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Amount</label>
            <input required type="number" step="0.01" min="0" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Tax</label>
            <input type="number" step="0.01" min="0" value={form.tax} onChange={(e) => setForm({ ...form, tax: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Type</label>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as "income" | "expense" })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm">
              <option value="expense">Expense</option>
              <option value="income">Income</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Category</label>
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm">
              {FORM_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="col-span-2">
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div className="col-span-2 flex gap-3 pt-2">
            <button type="submit" className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700">Save</button>
            <button type="button" onClick={() => setShowForm(false)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
          </div>
        </form>
      )}

      {pageTab === "transactions" && <div className="flex flex-wrap gap-3 items-center">
        <select value={type} onChange={(e) => setType(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">All types</option>
          <option value="income">Income</option>
          <option value="expense">Expense</option>
          <option value="transfer-in">Transfer In</option>
          <option value="transfer-out">Transfer Out</option>
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
          ))}
        </select>
        <select value={dateRange} onChange={(e) => setDateRange(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {FY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          <option value="all">All time</option>
          <option value="custom">Custom range</option>
        </select>
        {dateRange === "custom" && (
          <>
            <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white" />
            <span className="text-gray-400 text-sm">to</span>
            <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white" />
          </>
        )}
        <input
          type="text"
          placeholder="Vendor…"
          value={vendor}
          onChange={(e) => setVendor(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white w-36"
        />
        {importFiles.length > 0 && (
          <select value={sourceRef} onChange={(e) => setSourceRef(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white max-w-[180px]">
            <option value="">All files</option>
            {importFiles.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        )}
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={businessOnly}
            onChange={(e) => setBusinessOnly(e.target.checked)}
            className="rounded"
          />
          Business only
        </label>
      </div>}

      {pageTab === "transactions" && loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-400">No transactions yet. Import some from the Import page.</p>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
              <tr>
                {(["date", "vendor", "category", "type"] as (keyof Transaction)[]).map((col) => (
                  <th key={col} className="px-4 py-3 text-left cursor-pointer select-none hover:text-gray-700" onClick={() => handleSort(col)}>
                    {col}{sortCol === col ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
                <th className="px-4 py-3 text-left text-gray-500">description</th>
                <th className="px-4 py-3 text-left text-gray-500">reconcile</th>
                <th className="px-4 py-3 text-right cursor-pointer select-none hover:text-gray-700" onClick={() => handleSort("amount")}>
                  Amount{sortCol === "amount" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
                <th className="px-4 py-3 text-right cursor-pointer select-none hover:text-gray-700" onClick={() => handleSort("tax")}>
                  Tax{sortCol === "tax" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
                <th className="px-4 py-3 text-center text-gray-500">Business</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((t) => {
                const editing = editingId === t.id;
                return (
                  <React.Fragment key={t.id}>
                  <tr className={`transition-colors ${editing ? "bg-blue-50" : "hover:bg-gray-50"}`}>
                    <td className="px-4 py-3 text-gray-600">{t.date}</td>

                    <td className="px-4 py-3">
                      {editing ? (
                        <input
                          value={editForm.vendor}
                          onChange={(e) => setEditForm({ ...editForm, vendor: e.target.value })}
                          className="w-full border border-blue-300 rounded px-2 py-1 text-sm font-medium"
                          autoFocus
                        />
                      ) : (
                        <div>
                          <span className="font-medium text-gray-800">{t.vendor}</span>
                        </div>
                      )}
                    </td>

                    <td className="px-4 py-3">
                      {editing ? (
                        <select
                          value={editForm.category}
                          onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}
                          className="w-full border border-blue-300 rounded px-2 py-1 text-sm"
                        >
                          {FORM_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      ) : (
                        <span className="capitalize text-gray-500">{t.category}</span>
                      )}
                    </td>

                    <td className="px-4 py-3">
                      {editing ? (
                        <select
                          value={editForm.type}
                          onChange={(e) => setEditForm({ ...editForm, type: e.target.value as "income" | "expense" | "transfer" })}
                          className="border border-blue-300 rounded px-2 py-1 text-sm"
                        >
                          <option value="income">income</option>
                          <option value="expense">expense</option>
                          <option value="transfer-in">transfer-in</option>
                          <option value="transfer-out">transfer-out</option>
                        </select>
                      ) : (
                        <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                          t.type === "income" ? "bg-green-100 text-green-700"
                          : t.type === "transfer-in" ? "bg-blue-50 text-blue-400"
                          : t.type === "transfer-out" ? "bg-gray-100 text-gray-400"
                          : "bg-red-100 text-red-700"
                        }`}>
                          {t.type}
                        </span>
                      )}
                    </td>

                    <td className="px-4 py-3 text-gray-500 max-w-xs">
                      {editing ? (
                        <input
                          value={editForm.description}
                          onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                          className="w-full border border-blue-300 rounded px-2 py-1 text-sm"
                        />
                      ) : (
                        <span className="text-xs truncate block">{t.description ?? ""}</span>
                      )}
                    </td>

                    <td className="px-4 py-3 text-xs max-w-[160px]">
                      {(() => {
                        const m = matchMap[t.id];
                        if (!m) return <span className="text-gray-300">—</span>;
                        const label = m.receipt?.vendor ?? "Receipt";
                        if (m.status === "confirmed")
                          return <span className="text-green-600 font-medium truncate block" title={label}>✓ {label}</span>;
                        return (
                          <span className="flex items-center gap-1">
                            <span className="text-amber-500 truncate" title={label}>~ {label}</span>
                            <button
                              onClick={async () => { await api.updateMatch(m.id, "confirmed"); load(page); }}
                              className="text-xs text-gray-300 hover:text-green-600 shrink-0"
                              title="Confirm match"
                            >✓</button>
                            <button
                              onClick={async () => { await api.updateMatch(m.id, "rejected"); load(page); }}
                              className="text-xs text-gray-300 hover:text-red-500 shrink-0"
                              title="Reject match"
                            >✕</button>
                          </span>
                        );
                      })()}
                    </td>

                    <td className={`px-4 py-3 text-right font-medium ${t.type === "income" ? "text-green-600" : t.type?.startsWith("transfer") ? "text-gray-400" : "text-gray-800"}`}>
                      {editing ? (
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={editForm.amount}
                          onChange={(e) => setEditForm({ ...editForm, amount: e.target.value })}
                          className="w-24 border border-blue-300 rounded px-2 py-1 text-sm text-right"
                        />
                      ) : (
                        fmt(t.amount)
                      )}
                    </td>

                    <td className="px-4 py-3 text-right text-gray-400">
                      {editing ? (
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          value={editForm.tax}
                          onChange={(e) => setEditForm({ ...editForm, tax: e.target.value })}
                          className="w-20 border border-blue-300 rounded px-2 py-1 text-sm text-right"
                        />
                      ) : (
                        t.tax ? fmt(t.tax) : "—"
                      )}
                    </td>

                    <td className="px-4 py-3 text-center">
                      {(t.source === "bank_csv" || t.source === "manual") ? (
                        <button
                          onClick={() => api.updateTransaction(t.id, { business: !(t.business ?? false) }).then((updated) => setItems((prev) => prev.map((x) => x.id === t.id ? updated : x)))}
                          title={(t.business ?? false) ? "Click to mark as personal" : "Click to mark as business"}
                          className={`text-xs font-medium px-2 py-0.5 rounded transition-colors ${
                            (t.business ?? false)
                              ? "bg-blue-100 text-blue-700 hover:bg-blue-200"
                              : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                          }`}
                        >
                          {(t.business ?? false) ? "Business" : "Personal"}
                        </button>
                      ) : (
                        <span className="text-xs text-gray-300 italic">Receipt</span>
                      )}
                    </td>

                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {editing ? (
                        <span className="flex justify-end gap-2">
                          <button onClick={() => saveEdit(t.id)} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Save</button>
                          <button onClick={() => setEditingId(null)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                        </span>
                      ) : (
                        <span className="flex justify-end gap-3">
                          <button onClick={() => startEdit(t)} className="text-gray-300 hover:text-blue-500 transition-colors text-xs">Edit</button>
                          <button onClick={() => handleDelete(t.id)} className="text-gray-300 hover:text-red-500 transition-colors text-xs">Delete</button>
                        </span>
                      )}
                    </td>
                  </tr>
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Page {page} of {Math.ceil(total / PAGE_SIZE)}</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ← Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(Math.ceil(total / PAGE_SIZE), p + 1))}
              disabled={page >= Math.ceil(total / PAGE_SIZE)}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
