"use client";
import { useEffect, useState } from "react";
import { api, Transaction } from "@/lib/api";

const CATEGORIES = ["all", "food", "transport", "utilities", "software", "marketing", "revenue", "salary", "office", "subscription", "other"];
const FORM_CATEGORIES = CATEGORIES.filter((c) => c !== "all");
const EMPTY_FORM = { date: "", vendor: "", amount: "", tax: "", category: "other", type: "expense" as "income" | "expense", description: "" };

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function TransactionsPage() {
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [type, setType] = useState("");
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(true);
  const [sortCol, setSortCol] = useState<keyof Transaction>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ vendor: "", category: "other", amount: "", tax: "" });

  function load() {
    setLoading(true);
    api
      .getTransactions({ type: type || undefined, category: category === "all" ? undefined : category })
      .then(({ items, total }) => { setItems(items); setTotal(total); })
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, [type, category]);

  async function handleDelete(id: number) {
    if (!confirm("Delete this transaction?")) return;
    await api.deleteTransaction(id);
    load();
  }

  function handleSort(col: keyof Transaction) {
    if (col === sortCol) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

  const sorted = [...items].sort((a, b) => {
    const av = a[sortCol] ?? "";
    const bv = b[sortCol] ?? "";
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
    return sortDir === "asc" ? cmp : -cmp;
  });

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

  async function handleTypeChange(id: number, newType: "income" | "expense") {
    await api.updateTransaction(id, { type: newType });
    load();
  }

  function startEdit(t: Transaction) {
    setEditingId(t.id);
    setEditForm({ vendor: t.vendor, category: t.category, amount: String(t.amount), tax: String(t.tax) });
  }

  async function saveEdit(id: number) {
    await api.updateTransaction(id, {
      vendor: editForm.vendor,
      category: editForm.category,
      amount: parseFloat(editForm.amount) || 0,
      tax: parseFloat(editForm.tax) || 0,
    });
    setEditingId(null);
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">Transactions <span className="text-base font-normal text-gray-400">({total})</span></h2>
        <button onClick={() => setShowForm(!showForm)}
          className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors">
          + Add
        </button>
      </div>

      {showForm && (
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

      <div className="flex gap-4">
        <select value={type} onChange={(e) => setType(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">All types</option>
          <option value="income">Income</option>
          <option value="expense">Expense</option>
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-400">No transactions yet. Import some from the Import page.</p>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
              <tr>
                {(["date", "vendor", "category", "type", "source"] as (keyof Transaction)[]).map((col) => (
                  <th key={col} className="px-4 py-3 text-left cursor-pointer select-none hover:text-gray-700" onClick={() => handleSort(col)}>
                    {col}{sortCol === col ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
                <th className="px-4 py-3 text-right cursor-pointer select-none hover:text-gray-700" onClick={() => handleSort("amount")}>
                  Amount{sortCol === "amount" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
                <th className="px-4 py-3 text-right cursor-pointer select-none hover:text-gray-700" onClick={() => handleSort("tax")}>
                  Tax{sortCol === "tax" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sorted.map((t) => {
                const editing = editingId === t.id;
                return (
                  <tr key={t.id} className={`transition-colors ${editing ? "bg-blue-50" : "hover:bg-gray-50"}`}>
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
                        <span className="font-medium text-gray-800">{t.vendor}</span>
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
                      <select
                        value={t.type}
                        onChange={(e) => handleTypeChange(t.id, e.target.value as "income" | "expense")}
                        className={`text-xs font-medium px-2 py-0.5 rounded border-0 cursor-pointer ${t.type === "income" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}
                      >
                        <option value="income">income</option>
                        <option value="expense">expense</option>
                      </select>
                    </td>

                    <td className="px-4 py-3 text-gray-400 capitalize">{t.source}</td>

                    <td className={`px-4 py-3 text-right font-medium ${t.type === "income" ? "text-green-600" : "text-gray-800"}`}>
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
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
