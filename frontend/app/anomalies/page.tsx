"use client";
import { useEffect, useState } from "react";
import { api, Transaction } from "@/lib/api";

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function AnomaliesPage() {
  const [items, setItems] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [dismissing, setDismissing] = useState<number | null>(null);

  function load() {
    setLoading(true);
    api.getTransactions({ anomaly: true, sort_by: "date", sort_dir: "desc", limit: 200 })
      .then(({ items }) => setItems(items))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []);

  async function dismiss(id: number) {
    setDismissing(id);
    await api.dismissAnomaly(id);
    setDismissing(null);
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-800">Anomalies</h2>
          <p className="text-sm text-gray-400 mt-1">Transactions where the amount differs significantly from past records for the same vendor.</p>
        </div>
        {!loading && items.length > 0 && (
          <span className="bg-amber-100 text-amber-700 text-sm font-medium px-3 py-1 rounded-full">
            {items.length} flagged
          </span>
        )}
      </div>

      {loading ? (
        <p className="text-gray-400">Loading…</p>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center">
          <p className="text-green-600 font-medium">No anomalies detected</p>
          <p className="text-gray-400 text-sm mt-1">All transaction amounts look normal.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Vendor</th>
                <th className="px-4 py-3 text-right">Amount</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Reason</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-600">{t.date}</td>
                  <td className="px-4 py-3 font-medium text-gray-800">{t.vendor}</td>
                  <td className={`px-4 py-3 text-right font-medium ${t.type === "income" ? "text-green-600" : "text-gray-800"}`}>
                    {fmt(t.amount)}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${t.type === "income" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                      {t.type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-amber-600 max-w-sm">{t.anomaly_reason ?? "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => dismiss(t.id)}
                      disabled={dismissing === t.id}
                      className="text-xs text-gray-300 hover:text-gray-600 disabled:opacity-40"
                    >
                      {dismissing === t.id ? "Dismissing…" : "Dismiss"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
