"use client";
import React, { useEffect, useState } from "react";
import { api, Transaction, ReconciliationMatch } from "@/lib/api";
import VendorRulesTab from "@/components/VendorRulesTab";

const CATEGORIES = ["all", "food", "grocery", "cafe", "transport", "travel", "utilities", "software", "marketing", "revenue", "salary", "refund", "office", "subscription", "shopping", "leisure", "material", "fee", "gym", "medical", "other"];

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

const SOURCE_LABELS: Record<string, string> = { email: "Email", pdf: "PDF", image: "Image" };

export default function ReceiptsPage() {
  const [pageTab, setPageTab] = useState<"receipts" | "rules">("receipts");
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [type, setType] = useState("");
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(true);
  const [dateRange, setDateRange] = useState<"all" | "custom" | string>(`fy:${fyStartYear()}`);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [vendor, setVendor] = useState("");
  const [receiptSource, setReceiptSource] = useState("");
  const [matchMap, setMatchMap] = useState<Record<number, ReconciliationMatch>>({});
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [sourceText, setSourceText] = useState<string>("");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  function load(p = page) {
    setLoading(true);
    const fy = FY_OPTIONS.find((o) => o.value === dateRange);
    const date_from = dateRange === "custom" ? customFrom || undefined : fy?.from;
    const date_to = dateRange === "custom" ? customTo || undefined : fy?.to;
    Promise.all([
      api.getTransactions({ type: type || undefined, category: category === "all" ? undefined : category, date_from, date_to, vendor: vendor || undefined, source: receiptSource || undefined, sort_by: "date", sort_dir: "desc", limit: PAGE_SIZE, offset: (p - 1) * PAGE_SIZE }),
      api.getReconciliationMatches(),
    ]).then(([{ items, total }, matches]) => {
      const receipts = receiptSource ? items : items.filter((t) => t.source !== "bank_csv");
      setItems(receipts);
      setTotal(total);
      const map: Record<number, ReconciliationMatch> = {};
      for (const m of matches) if (m.receipt?.id) map[m.receipt.id] = m;
      setMatchMap(map);
    }).finally(() => setLoading(false));
  }

  useEffect(() => { setPage(1); load(1); }, [type, category, dateRange, customFrom, customTo, vendor, receiptSource]);
  useEffect(() => { load(page); }, [page]);

  async function toggleSource(id: number) {
    if (sourceId === id) { setSourceId(null); return; }
    const res = await api.getSourceText(id);
    setSourceText(res.raw_text);
    setSourceId(id);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">
          {pageTab === "receipts"
            ? <>Receipts <span className="text-base font-normal text-gray-400">({total})</span></>
            : "Vendor Rules"}
        </h2>
        <div className="flex gap-2">
          <button onClick={() => setPageTab("receipts")}
            className={`text-sm px-4 py-2 rounded-lg border transition-colors ${pageTab === "receipts" ? "bg-gray-800 text-white border-gray-800" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
            Receipts
          </button>
          <button onClick={() => setPageTab("rules")}
            className={`text-sm px-4 py-2 rounded-lg border transition-colors ${pageTab === "rules" ? "bg-gray-800 text-white border-gray-800" : "border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
            Vendor Rules
          </button>
        </div>
      </div>

      {pageTab === "rules" && <VendorRulesTab />}

      {pageTab === "receipts" && <div className="flex flex-wrap gap-3 items-center">
        <select value={type} onChange={(e) => setType(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">All types</option>
          <option value="income">Income</option>
          <option value="expense">Expense</option>
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {CATEGORIES.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
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
        <select value={receiptSource} onChange={(e) => setReceiptSource(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">All sources</option>
          <option value="email">Email</option>
          <option value="pdf">PDF</option>
          <option value="image">Image</option>
          <option value="csv">Marketplace CSV</option>
        </select>
        <input type="text" placeholder="Vendor…" value={vendor} onChange={(e) => setVendor(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white w-36" />
      </div>}

      {pageTab === "receipts" && loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-gray-400">No receipts yet. Import emails or PDFs from the Import page.</p>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Vendor</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Source</th>
                <th className="px-4 py-3 text-left">Matched to</th>
                <th className="px-4 py-3 text-right">Amount</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((t) => {
                const m = matchMap[t.id];
                return (
                  <React.Fragment key={t.id}>
                    <tr className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-600">{t.date}</td>
                      <td className="px-4 py-3 font-medium text-gray-800">{t.vendor}</td>
                      <td className="px-4 py-3 text-gray-500 capitalize">{t.category}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded ${t.type === "income" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                          {t.type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{SOURCE_LABELS[t.source] ?? t.source}</td>
                      <td className="px-4 py-3 text-xs max-w-[140px]">
                        {m ? (
                          <span className={m.status === "confirmed" ? "text-green-600 font-medium truncate block" : "text-amber-500 truncate block"} title={m.bank?.vendor ?? ""}>
                            {m.status === "confirmed" ? "✓" : "~"} {m.bank?.vendor ?? "—"}
                          </span>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className={`px-4 py-3 text-right font-medium ${t.type === "income" ? "text-green-600" : "text-gray-800"}`}>
                        {fmt(t.amount)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => toggleSource(t.id)}
                          className={`text-xs transition-colors ${sourceId === t.id ? "text-blue-500 font-medium" : "text-gray-300 hover:text-blue-400"}`}
                        >{sourceId === t.id ? "▲ Close" : "Source"}</button>
                      </td>
                    </tr>
                    {sourceId === t.id && (
                      <tr className="bg-gray-50">
                        <td colSpan={8} className="px-4 pb-3 pt-1">
                          <div className="flex justify-end mb-1">
                            <button
                              onClick={() => setSourceId(null)}
                              className="text-xs text-blue-500 hover:text-blue-700 font-medium"
                            >▲ Close</button>
                          </div>
                          <pre className="text-xs text-gray-600 whitespace-pre-wrap break-words max-h-64 overflow-y-auto bg-white border border-gray-100 rounded p-3 font-mono leading-relaxed">
                            {sourceText || "(no source text)"}
                          </pre>
                        </td>
                      </tr>
                    )}
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
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40">← Prev</button>
            <button onClick={() => setPage((p) => Math.min(Math.ceil(total / PAGE_SIZE), p + 1))} disabled={page >= Math.ceil(total / PAGE_SIZE)}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40">Next →</button>
          </div>
        </div>
      )}
    </div>
  );
}
